"""View rendering: geometry, markup safety, layout tiers and body composition."""

import time
import unittest

from hkg_flight.terminal import views
from hkg_flight.terminal.presenter import DEPARTURES, ALERTS, AIRLINES
from hkg_flight.terminal.state import AppState, reconcile
from tests.fixtures.terminal.data import (
    make_combined_snapshot,
    make_flight,
)


class TestGeometry(unittest.TestCase):
    def test_ascii_width(self):
        self.assertEqual(views.text_width("CX759"), 5)

    def test_cjk_counts_two_cells(self):
        self.assertEqual(views.text_width("北京"), 4)

    def test_markup_tags_count_zero(self):
        self.assertEqual(views.text_width("[green]CX759[/green]"), 5)

    def test_escaped_bracket_is_restored_for_width(self):
        self.assertEqual(views.text_width(views.escape_markup("a[b]")), 4)

    def test_truncate_short_text_is_unchanged(self):
        self.assertEqual(views.truncate("CX759", 10), "CX759")

    def test_truncate_adds_ellipsis_and_fits(self):
        cut = views.truncate("Departed 08:54", 8)
        self.assertTrue(cut.endswith(views.ELLIPSIS))
        self.assertLessEqual(views.text_width(cut), 8)

    def test_truncate_never_splits_a_wide_character(self):
        cut = views.truncate("北京首都", 5)
        self.assertLessEqual(views.text_width(cut), 5)

    def test_truncate_closes_markup_left_open(self):
        cut = views.truncate("[green]Departed 08:54[/green]", 12)
        self.assertTrue(cut.startswith("[green]"))
        self.assertTrue(cut.endswith("[/green]"))
        self.assertLessEqual(views.text_width(cut), 12)

    def test_zero_or_negative_width(self):
        self.assertEqual(views.truncate("abc", 0), "")
        self.assertEqual(views.truncate("abc", -1), "")

    def test_pad_to_exact_width(self):
        padded = views.pad("ab", 5)
        self.assertEqual(views.text_width(padded), 5)
        self.assertEqual(views.pad("abcdef", 3).endswith(views.ELLIPSIS), True)


class TestLayout(unittest.TestCase):
    def test_layout_fills_requested_width(self):
        line = views.layout(list(views.FLIGHT_COLUMNS), 78)
        self.assertLessEqual(views.text_width(line), 78)
        self.assertGreater(views.text_width(line), 60)

    def test_layout_is_monotonic_in_width(self):
        narrow = views.text_width(views.layout(list(views.FLIGHT_COLUMNS), 40))
        wide = views.text_width(views.layout(list(views.FLIGHT_COLUMNS), 100))
        self.assertLess(narrow, wide)

    def test_degenerate_widths_do_not_raise(self):
        self.assertEqual(views.layout(list(views.FLIGHT_COLUMNS), 0), "")
        self.assertEqual(views.layout([], 80), "")
        views.layout(list(views.FLIGHT_COLUMNS), 1)

    def test_layout_tiers(self):
        self.assertEqual(views.layout_tier(30, 20), "size_hint")
        self.assertEqual(views.layout_tier(100, 10), "size_hint")
        self.assertEqual(views.layout_tier(120, 30), "wide")
        self.assertEqual(views.layout_tier(90, 30), "normal")
        self.assertEqual(views.layout_tier(50, 20), "compact")


class TestRows(unittest.TestCase):
    def test_flight_row_fits_and_marks_selection(self):
        rec = make_flight(0)
        plain = views.flight_row(rec, 78)[0]
        selected = views.flight_row(rec, 78, selected=True)[0]
        self.assertLessEqual(views.text_width(plain), 78)
        self.assertTrue(selected.startswith("> "))
        self.assertFalse(plain.startswith("> "))

    def test_flight_row_carries_key_fields(self):
        rec = make_flight(0)
        line = views.flight_row(rec, 78)[0]
        self.assertIn(rec["flight_number"], line)
        self.assertIn(rec["time"], line)

    def test_compact_row_is_two_lines(self):
        lines = views.flight_row(make_flight(0), 78, compact=True)
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertLessEqual(views.text_width(line), 78)

    def test_status_colour_wraps_only_when_requested(self):
        rec = make_flight(1)  # boarding
        self.assertIn("[", views.flight_row(rec, 78, color=True)[0])
        self.assertNotIn("[", views.flight_row(rec, 78, color=False)[0])

    def test_data_brackets_cannot_inject_markup(self):
        rec = dict(make_flight(1), status="Board[red]ing", status_category="boarding")
        line = views.flight_row(rec, 78, color=True)[0]
        self.assertIn(r"\[red]", line)
        self.assertLessEqual(views.text_width(line), 78)

    def test_header_aligns_with_rows(self):
        self.assertLessEqual(views.text_width(views.flight_header(78)), 78)

    def test_stand_is_shown_verbatim(self):
        # HKIA stands already carry their letter (W63, D201); an extra "S" made
        # the cell read "SW63".
        rec = dict(make_flight(1), type="arrival", stand="W63")
        self.assertEqual(views.gate_stand_short(rec), "W63")
        line = views.flight_row(rec, 78)[0]
        self.assertIn("W63", line)
        self.assertNotIn("SW63", line)

    def test_gate_gains_its_letter_because_the_api_sends_a_bare_number(self):
        rec = dict(make_flight(0), type="departure", gate="68")
        self.assertEqual(views.gate_stand_short(rec), "G68")

    def test_missing_position_renders_as_dashes(self):
        self.assertEqual(views.gate_stand_short({"type": "arrival"}), "--")
        self.assertEqual(views.gate_stand_short({"type": "departure"}), "--")

    def test_route_cell_marks_the_direction(self):
        dep = dict(make_flight(0), type="departure", destination="NRT")
        arr = dict(make_flight(1), type="arrival", origin="SYD")
        self.assertEqual(views.route_short(dep), "→ NRT")
        self.assertEqual(views.route_short(arr), "← SYD")

    def test_date_separator_names_the_day_and_fills_the_width(self):
        line = views.date_separator("2026-09-11", 78)
        self.assertIn("2026-09-11", line)
        self.assertEqual(views.text_width(line), 78)


class TestFreshness(unittest.TestCase):
    def base(self, **kw):
        flights = {"source": "none", "polling_enabled": True}
        flights.update(kw)
        return flights

    def test_labels(self):
        now = time.time()
        self.assertEqual(views.freshness(self.base(source="api", last_api_success_at="2026-09-09T08:00:00")), "API OK")
        self.assertEqual(views.freshness(self.base(source="cache", cache_saved_at=now), now=now), "CACHE")
        self.assertEqual(views.freshness(self.base(source="cache", cache_saved_at=0.0), now=now), "STALE")
        self.assertEqual(views.freshness(self.base(source="cache")), "CACHE (age UNKNOWN)")
        self.assertEqual(views.freshness(self.base(source="memory")), "ERROR")
        self.assertEqual(views.freshness(self.base()), "no data")
        self.assertEqual(views.freshness(self.base(source="api", refreshing=True)), "LOADING")
        self.assertEqual(views.freshness(self.base(polling_enabled=False)), "MANUAL")

    def test_stale_detection(self):
        flights = self.base(source="api", last_api_success_at="2026-09-09T08:00:00")
        epoch = views._to_epoch("2026-09-09T08:00:00")
        self.assertEqual(views.freshness(flights, now=epoch + 10_000, poll_interval=30), "STALE")
        self.assertEqual(views.freshness(flights, now=epoch + 1, poll_interval=30), "API OK")

    def test_status_line_reports_error(self):
        snap = {"flights": {"source": "none", "last_error": "boom", "records_date": ""}}
        self.assertIn("boom", views.status_line(snap))


class TestHeaderNavFooter(unittest.TestCase):
    def setUp(self):
        self.snap = make_combined_snapshot(30)
        self.state = AppState()
        reconcile(self.state, [{"id": "x", "record": {}}])

    def test_header_reports_source_and_web(self):
        text = views.header_line(self.snap, {"status": "on", "port": 8080})
        self.assertIn("HKG FLIGHT", text)
        self.assertIn("Web :8080 ON", text)

    def test_header_flags_previous_date(self):
        snap = make_combined_snapshot(5, date="2026-09-08")
        self.assertIn("(previous)", views.header_line(snap, {"status": "off", "port": 8080},
                                                      today="2026-09-09"))

    def test_nav_marks_current_page_and_counts_alerts(self):
        text = views.nav_line(self.state, 3, True, "off")
        self.assertIn("[1 Departures]", text)
        self.assertIn("Alerts 3", text)
        self.assertIn("Poll ON", text)

    def test_footer_changes_with_focus(self):
        self.state.focus = "search"
        self.assertIn("typing", views.footer_line("normal", self.state))
        self.state.focus = "list"
        self.assertIn("Search", views.footer_line("normal", self.state))

    def test_search_line_reports_match_counts(self):
        text = views.search_line(self.state, self.snap)
        self.assertIn("Matches", text)


class TestBodyLines(unittest.TestCase):
    def build(self, current=DEPARTURES, count=30, **snap_kw):
        snap = make_combined_snapshot(count, **snap_kw)
        state = AppState()
        state.current = current
        reconcile(state, [{"id": "x", "record": {}}])
        return state, snap

    def test_size_hint_for_tiny_terminals(self):
        state, snap = self.build()
        lines = views.body_lines(state, snap, 30, 10, False)
        self.assertIn("too small", lines[0])

    def test_list_body_has_header_and_rows(self):
        state, snap = self.build()
        lines = views.body_lines(state, snap, 100, 30, False)
        self.assertTrue(lines)
        for line in lines:
            self.assertLessEqual(views.text_width(line), 100)

    def test_help_block_renders(self):
        state, snap = self.build()
        state.help_open = True
        lines = views.body_lines(state, snap, 100, 30, False)
        self.assertIn("HELP", lines[0])

    def test_filter_block_renders(self):
        state, snap = self.build()
        state.filter_open = True
        lines = views.body_lines(state, snap, 100, 30, False)
        self.assertIn("FILTER", lines[0])

    def test_wide_tier_splits_list_and_detail(self):
        state, snap = self.build()
        state.detail_id = "anything"
        lines = views.body_lines(state, snap, 130, 30, False)
        self.assertTrue(any("|" in line for line in lines))

    def test_narrow_detail_overlay(self):
        state, snap = self.build()
        state.detail_id = "anything"
        lines = views.body_lines(state, snap, 100, 30, False)
        self.assertTrue(lines)

    def test_empty_state_message(self):
        state, snap = self.build(count=0)
        lines = views.body_lines(state, snap, 100, 30, False)
        self.assertTrue(any("No matches" in line or "Cannot load" in line for line in lines))

    def test_alerts_and_airlines_pages(self):
        for page in (ALERTS, AIRLINES):
            state, snap = self.build(current=page)
            lines = views.body_lines(state, snap, 100, 30, False)
            self.assertTrue(lines, page)
            for line in lines:
                self.assertLessEqual(views.text_width(line), 100)

    def test_wide_tier_alerts_and_airlines(self):
        """The wide split layout must render every page, not just flights."""
        for page in (ALERTS, AIRLINES):
            state, snap = self.build(current=page)
            state.detail_id = "anything"
            lines = views.body_lines(state, snap, 130, 30, False)
            self.assertTrue(lines, page)
            for line in lines:
                self.assertLessEqual(views.text_width(line), 130)


if __name__ == "__main__":
    unittest.main()
