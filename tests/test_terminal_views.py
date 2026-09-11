"""View rendering: geometry, markup safety, layout tiers and body composition."""

import os
import re
import time
import unittest

from hkg_flight.terminal import views
from hkg_flight.terminal.presenter import DEPARTURES, ARRIVALS, ALERTS, AIRLINES
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

    def test_a_column_gets_its_minimum_before_anyone_gets_a_share(self):
        """A short field must not hoard space the long field needs.

        ``T1`` is three cells. Under a purely proportional split it was handed
        twenty cells on a phone-width row while the status column was squeezed
        into a truncated stub.
        """
        cells = [("T1", 1, 3), ("At gate 23:47 (06/09/2026)", 4, 26)]
        line = views.layout(cells, 55)
        self.assertIn("At gate 23:47 (06/09/2026)", line)
        self.assertEqual(views.text_width(line), 55)

    def test_minimums_are_dropped_when_they_cannot_all_fit(self):
        """A 20-column terminal still renders, falling back to the weights."""
        cells = [("A", 1, 20), ("B", 1, 20)]
        line = views.layout(cells, 20)
        self.assertLessEqual(views.text_width(line), 20)
        self.assertIn("A", line)
        self.assertIn("B", line)

    def test_a_two_tuple_still_means_weight_only(self):
        self.assertEqual(views.text_width(views.layout([("ab", 1), ("cd", 1)], 10)), 10)

    def test_compact_agrees_with_the_layout_tier(self):
        """The CLI has no height, so its width-only test must match the tier."""
        for width in (40, 45, 79, 80, 90, 130):
            tier = views.layout_tier(width, 30)
            self.assertEqual(views.is_compact(width), tier == "compact", width)

    def test_compact_boundary_is_exclusive(self):
        self.assertFalse(views.is_compact(views.COMPACT_BELOW))
        self.assertTrue(views.is_compact(views.COMPACT_BELOW - 1))


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

    def test_no_row_ever_exceeds_a_phone_width(self):
        """The whole point of the adaptive width: nothing wraps mid-value.

        On a phone-sized terminal a 78-cell row is wrapped by the shell, which
        splits values such as ``G30`` into ``G`` and ``30``.
        """
        records = [
            dict(make_flight(0), type="departure", gate="30", destination="NRT"),
            dict(make_flight(1), type="arrival", stand="W63", origin="SYD"),
        ]
        for width in (120, 78, 60, 45, 30, 20, 12, 8, 4, 1):
            for rec in records:
                lines = views.flight_row(rec, width, compact=views.is_compact(width))
                self.assertTrue(lines, width)
                for line in lines:
                    self.assertLessEqual(views.text_width(line), width, (width, line))
            self.assertLessEqual(views.text_width(views.flight_header(width)), width)
            self.assertLessEqual(views.text_width(views.rule(width)), width)
            self.assertLessEqual(views.text_width(views.date_separator("2026-09-11", width)), width)

    def test_compact_keeps_the_gate_whole(self):
        rec = dict(make_flight(0), type="departure", gate="30")
        lines = views.flight_row(rec, 45, compact=True)
        self.assertTrue(any("G30" in line for line in lines), lines)
        self.assertFalse(any(line.strip() == "G" for line in lines), lines)

    def test_compact_preserves_the_column_order_of_the_single_line_row(self):
        """Widening a terminal must not reorder the fields."""
        rec = dict(make_flight(0), type="departure", gate="30", destination="NRT")
        wide = views.flight_row(rec, 100)[0]
        line1, line2 = views.flight_row(rec, 45, compact=True)
        for value in (rec["time"], rec["flight_number"], rec["status"]):
            self.assertIn(value, line1)
        for value in ("NRT", "G30", rec["terminal"]):
            self.assertIn(value, line2)
        self.assertLess(wide.index(rec["flight_number"]), wide.index("NRT"))


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


class TestColumnWidths(unittest.TestCase):
    """Real API values must survive the columns they are given."""

    # The longest status the HKIA feed produces, measured over 7 days of cache.
    LONGEST_STATUS = "At gate 23:47 (06/09/2026)"

    def rec(self, **kw):
        rec = {"time": "15:45", "flight_number": "CX256D", "type": "arrival",
               "stand": "W63", "terminal": "T1", "origin": "LHR",
               "status": self.LONGEST_STATUS, "status_category": "at_gate"}
        rec.update(kw)
        return rec

    def test_the_longest_real_status_survives_a_phone_width(self):
        # It used to be cut to "At gate 23:47 (06/09/2…" even at 100 columns:
        # the proportional weights starved STATUS while TIME and TERM sat on
        # space they could not use.
        for width in (48, 55, 60, 78, 100, 120):
            lines = views.flight_row(self.rec(), width, compact=views.is_compact(width))
            self.assertIn(self.LONGEST_STATUS, "\n".join(lines), width)

    def test_every_row_fills_exactly_the_requested_width(self):
        for width in (40, 55, 80, 120):
            for line in views.flight_row(self.rec(), width, compact=views.is_compact(width)):
                self.assertEqual(views.text_width(line), width, width)

    def test_header_columns_line_up_with_the_values(self):
        """The header and the rows share one column table, so they cannot drift."""
        rec = self.rec(time="11:11", flight_number="AA111", origin="BBB",
                       stand="G12", terminal="T9", status="Ssss")
        width = 100
        header = views.flight_header(width)
        row = views.flight_row(rec, width)[0]
        for label, value in (("TIME", "11:11"), ("FLIGHT", "AA111"), ("ROUTE", "← BBB"),
                             ("STATUS", "Ssss"), ("GATE/STAND", "G12"), ("TERM", "T9")):
            self.assertEqual(header.index(label), row.index(value), label)

    def test_a_header_label_is_never_truncated_away(self):
        """Every label fits the column, so the header never shows an ellipsis.

        The header only appears at ``COMPACT_BELOW`` and above (and in the wide
        split, whose list column is narrower than the terminal).
        """
        for width in (views.COMPACT_BELOW, 84, 100, 120):
            header = views.flight_header(width)
            self.assertNotIn(views.ELLIPSIS, header, width)
            for label in ("TIME", "FLIGHT", "ROUTE", "STATUS", "GATE/STAND", "TERM"):
                self.assertIn(label, header, (width, label))

    def test_the_alert_header_labels_all_fit(self):
        for width in (views.COMPACT_BELOW, 100, 120):
            header = views.alert_header(width)
            for label in ("CHANGED", "FLIGHT", "CHANGE", "STATUS"):
                self.assertIn(label, header, (width, label))


class TestWidgetsFitTheTerminal(unittest.TestCase):
    """Nothing the front-end hands to a widget may exceed its width.

    Textual wraps at the last word, so a line one cell too wide does not clip -
    it moves a whole value onto the next row. That is how "(12/09/2026)" ended
    up on a line of its own.
    """

    def build(self, current=DEPARTURES):
        snap = make_combined_snapshot(30)
        state = AppState()
        state.current = current
        reconcile(state, [{"id": "x", "record": {}}])
        return state, snap

    def widgets(self, state, snap, width, height):
        yield "header", views.header_line(snap, snap["web"], width=width)
        yield "nav", views.nav_line(state, 12, True, "off", width=width)
        yield "search", views.search_line(state, snap, width=width)
        yield "footer", views.footer_line(views.layout_tier(width, height), state, width=width)
        for index, line in enumerate(views.body_lines(state, snap, width, height, False)):
            yield f"body[{index}]", line

    def test_nothing_exceeds_a_phone_width(self):
        for width in (120, 100, 80, 79, 60, 55, 45, 30, 20):
            for page in (DEPARTURES, ARRIVALS, ALERTS, AIRLINES):
                state, snap = self.build(page)
                for name, line in self.widgets(state, snap, width, 30):
                    self.assertLessEqual(views.text_width(line), width,
                                         (width, page, name, line))

    def test_the_body_never_returns_more_lines_than_it_has(self):
        # Both tiers: the compact tier floors its row count, which can hide an
        # off-by-one in the chrome reserve, so the single-line tier must be
        # checked too (that is where ``height - 3`` overflowed by one row).
        for width in (55, 100):
            for height in (16, 20, 24, 30, 40):
                for page in (DEPARTURES, ARRIVALS, ALERTS, AIRLINES):
                    state, snap = self.build(page)
                    lines = views.body_lines(state, snap, width, height, False)
                    self.assertLessEqual(len(lines), max(1, height - views.CHROME_ROWS),
                                         (width, height, page, len(lines)))

    def test_bars_measure_the_same_as_their_length(self):
        """A bar containing something tag-shaped would measure short and wrap.

        ``text_width`` strips rich markup; these strings are printed raw.
        """
        for width in range(10, 80):
            for page in (DEPARTURES, ALERTS):
                state, snap = self.build(page)
                for name, line in self.widgets(state, snap, width, 30):
                    if name == "body[0]" or name.startswith("body"):
                        continue
                    self.assertEqual(views.text_width(line), len(line), (width, name, line))

    def test_the_compact_list_has_no_placeholder_header(self):
        state, snap = self.build()
        narrow = "\n".join(views.body_lines(state, snap, 55, 30, False))
        self.assertNotIn("COMPACT", narrow)
        self.assertNotIn("COMPACT", "\n".join(views.body_lines(state, snap, 45, 30, False)))
        # The wide tier still carries a real column header.
        self.assertIn("FLIGHT", "\n".join(views.body_lines(state, snap, 100, 30, False)))

    def test_the_nav_falls_back_to_short_labels(self):
        state, snap = self.build()
        wide = views.nav_line(state, 0, True, "off", width=120)
        self.assertIn("Departures", wide)
        narrow = views.nav_line(state, 99, True, "off", width=45)
        self.assertLessEqual(views.text_width(narrow), 45)
        self.assertIn("Dep", narrow)
        self.assertNotIn("Departures", narrow)

    def test_the_footer_keeps_quit_on_a_phone(self):
        state = AppState()
        for width in (20, 30, 45, 55, 80, 120):
            footer = views.footer_line("compact", state, width=width)
            self.assertLessEqual(views.text_width(footer), width, width)
            self.assertIn("q", footer, width)

    def test_search_line_drops_the_empty_label(self):
        state, snap = self.build()
        # make_combined_snapshot(30) alternates directions, so 15 are departures.
        self.assertEqual(views.search_line(state, snap, width=78), "Matches 15 / Total 15")
        state.pages[DEPARTURES].search_text = "CX"
        self.assertIn("Search: CX", views.search_line(state, snap, width=78))


class TestFitLadder(unittest.TestCase):
    def test_picks_the_longest_form_that_fits(self):
        forms = ("abcdefgh", "abcd", "ab")
        self.assertEqual(views.fit(forms, 8), "abcdefgh")
        self.assertEqual(views.fit(forms, 7), "abcd")
        self.assertEqual(views.fit(forms, 2), "ab")
        self.assertEqual(views.fit(forms, 1), "")

    def test_an_unformattable_form_is_skipped(self):
        self.assertEqual(views.fit(("{missing}", "ok"), 10), "ok")


class TestThemeMatchesTheRenderer(unittest.TestCase):
    """theme.tcss and views must agree on how much room each widget has.

    The renderer is handed the terminal width, so a widget's content width has
    to equal the terminal width: any horizontal padding makes Textual re-wrap
    every line at its last word.
    """

    CHROME = ("#header", "#nav", "#search_row", "#footer")
    FULL_WIDTH = CHROME + ("#body",)

    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(views.__file__), "theme.tcss")
        with open(path, encoding="utf-8") as handle:
            cls.css = handle.read()

    def block(self, selector):
        match = re.search(re.escape(selector) + r"\s*\{(.*?)\}", self.css, re.S)
        self.assertIsNotNone(match, selector)
        return match.group(1)

    def test_no_full_width_widget_pads_horizontally(self):
        for selector in self.FULL_WIDTH:
            for declaration in re.findall(r"padding:\s*([^;]+);", self.block(selector)):
                self.assertEqual([part.strip() for part in declaration.split()], ["0", "0"],
                                 f"{selector} padding {declaration!r} narrows the content width")

    def test_each_chrome_widget_is_one_row(self):
        for selector in self.CHROME:
            self.assertRegex(self.block(selector), r"height:\s*1\s*;", selector)

    def test_the_body_takes_the_remaining_rows(self):
        self.assertRegex(self.block("#body"), r"height:\s*1fr\s*;")

    def test_the_chrome_row_count_matches_views(self):
        self.assertEqual(len(self.CHROME), views.CHROME_ROWS)


if __name__ == "__main__":
    unittest.main()
