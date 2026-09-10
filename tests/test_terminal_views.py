"""
Tests for the pure view renderer across terminal sizes (A6 structural
checks): no exceptions, no line wider than the terminal, key fields present,
and a size hint below the supported floor. Deterministic string checks.
"""

import unicodedata
import unittest

from hkg_flight.terminal.state import AppState, reconcile
from hkg_flight.terminal import views
from hkg_flight.terminal.presenter import (
    visible_rows, alert_rows, DEPARTURES, ALERTS,
)
from tests.fixtures.terminal.data import make_combined_snapshot


def cells(text):
    """Independent display-cell count: 2 for wide/full-width, 0 for combining."""
    total = 0
    for char in text:
        if unicodedata.combining(char) or unicodedata.category(char) in ("Mn", "Me"):
            continue
        total += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return total


def build_state(snapshot, page=DEPARTURES):
    state = AppState()
    state.current = page
    if page in (DEPARTURES,):
        rows = visible_rows(snapshot["flights"], page, "", "", "")
    else:
        rows = alert_rows(snapshot["alerts"]["alerts"], "")
    reconcile(state, rows)
    return state


def select(state, rows, index):
    """Move selection to ``index`` (both id and index, like state does)."""
    page = state.pages[state.current]
    page.selected_index = index
    page.selected_id = rows[index]["id"]
    return page


class TestViewSizes(unittest.TestCase):
    def setUp(self):
        self.snap = make_combined_snapshot(200)
        self.state = build_state(self.snap)

    def _render(self, width, height):
        return views.body_lines(self.state, self.snap, width, height, color=False)

    def test_no_line_exceeds_width(self):
        for width, height in [(40, 16), (60, 20), (80, 24), (120, 30), (160, 40)]:
            for line in self._render(width, height):
                self.assertLessEqual(cells(line), width, (width, height, line))

    def test_key_fields_present_at_normal_size(self):
        lines = self._render(80, 24)
        joined = "\n".join(lines)
        self.assertIn("FLIGHT", joined)
        self.assertIn("TIME", joined)

    def test_size_hint_below_floor(self):
        lines = self._render(30, 8)
        joined = "\n".join(lines).lower()
        self.assertIn("too small", joined)

    def test_layout_tiers(self):
        self.assertEqual(views.layout_tier(120, 30), "wide")
        self.assertEqual(views.layout_tier(80, 24), "normal")
        self.assertEqual(views.layout_tier(60, 20), "compact")
        self.assertEqual(views.layout_tier(30, 8), "size_hint")
        self.assertEqual(views.layout_tier(100, 16), "normal")

    def test_scroll_to_end_does_not_crash(self):
        page = self.state.pages[DEPARTURES]
        total = len(visible_rows(self.snap["flights"], DEPARTURES, "", "", ""))
        page.offset = total
        lines = self._render(80, 24)
        self.assertTrue(lines)


class TestViewColor(unittest.TestCase):
    def setUp(self):
        self.snap = make_combined_snapshot(10)
        self.state = build_state(self.snap)

    def test_no_markup_without_color(self):
        lines = views.body_lines(self.state, self.snap, 80, 24, color=False)
        joined = "\n".join(lines)
        self.assertNotIn("[green]", joined)

    def test_markup_with_color(self):
        lines = views.body_lines(self.state, self.snap, 80, 24, color=True)
        joined = "\n".join(lines)
        self.assertIn("[", joined)


class TestFreshness(unittest.TestCase):
    def _snap(self, **overrides):
        snap = make_combined_snapshot(5)
        snap["flights"].update(overrides)
        return snap

    def test_api_ok_when_recent(self):
        flights = self._snap(source="api", last_api_success_at="2026-09-09T08:00:00")["flights"]
        now = _epoch("2026-09-09T08:00:30")
        self.assertEqual(views.freshness(flights, now=now), "API OK")

    def test_stale_after_threshold(self):
        flights = self._snap(source="api", last_api_success_at="2026-09-09T08:00:00")["flights"]
        now = _epoch("2026-09-09T08:05:00")
        self.assertEqual(views.freshness(flights, now=now), "STALE")

    def test_cache_unknown_age(self):
        flights = self._snap(source="cache", cache_saved_at=None)["flights"]
        self.assertEqual(views.freshness(flights, now=None), "CACHE (age UNKNOWN)")

    def test_previous_date_marker(self):
        snap = self._snap(source="api", records_date="2026-09-08")
        header = views.header_line(snap, snap["web"], today="2026-09-09")
        self.assertIn("previous", header)


class TestDisplayGeometry(unittest.TestCase):
    """R08: display cells, not len(). CJK / combining / controls / 40x16."""

    def setUp(self):
        self.snap = make_combined_snapshot(200)
        self.state = build_state(self.snap)
        self.rows = visible_rows(self.snap["flights"], DEPARTURES, "", "", "")

    def _render(self, width, height, **kwargs):
        return views.body_lines(self.state, self.snap, width, height, False, **kwargs)

    # -- primitives ----------------------------------------------------
    def test_display_width_counts_cjk_as_two_cells(self):
        self.assertEqual(views.display_width("北京"), 4)
        self.assertEqual(views.display_width("PEK"), 3)
        self.assertEqual(views.display_width("北京PEK"), 7)

    def test_display_width_ignores_markup_and_controls(self):
        self.assertEqual(views.display_width("[green]OK[/green]"), 2)
        self.assertEqual(views.display_width("A\x07B\x1bC"), 3)
        self.assertEqual(views.sanitize("A\x07\x1b[31mB"), "A[31mB")

    def test_truncate_never_leaves_markup_open(self):
        out = views.truncate("[green]abcdefgh", 4)
        self.assertIn("[green]", out)
        self.assertIn("[/green]", out)
        self.assertLess(out.index("[green]"), out.index("[/green]"))
        self.assertLessEqual(views.display_width(out), 4)

    def test_truncate_keeps_combining_marks_with_their_base(self):
        text = "é" * 10
        out = views.truncate(text, 4)
        self.assertEqual(out.count("e"), out.count("́"))
        self.assertFalse(out.startswith("́"))
        self.assertLessEqual(views.display_width(out), 4)

    # -- 40x16 ---------------------------------------------------------
    def test_body_is_bounded_at_40x16(self):
        lines = self._render(40, 16)
        self.assertTrue(lines)
        self.assertLessEqual(len(lines), 16 - 3)
        for line in lines:
            self.assertLessEqual(cells(line), 40, line)

    def test_compact_rows_use_two_lines_and_stay_bounded(self):
        for width, height in [(40, 16), (60, 20), (79, 18)]:
            lines = self._render(width, height)
            self.assertLessEqual(len(lines), max(1, height - 3), (width, height))
            for line in lines:
                self.assertLessEqual(cells(line), width, (width, height, line))

    def test_cjk_route_is_truncated_to_cells(self):
        record = self.rows[0]["record"]
        record["destination"] = "北京" * 12
        lines = self._render(40, 16)
        for line in lines:
            self.assertLessEqual(cells(line), 40, line)
        self.assertTrue(any(views.ELLIPSIS in line for line in lines))

    def test_control_characters_never_reach_the_terminal(self):
        record = self.rows[0]["record"]
        record["status"] = "OK\x07\x1b[31mRED\x1b[0m\x9b"
        joined = "\n".join(self._render(80, 24))
        for bad in ("\x07", "\x1b", "\x9b"):
            self.assertNotIn(bad, joined)

    def test_combining_route_stays_inside_width(self):
        record = self.rows[0]["record"]
        record["destination"] = "é" * 40
        for line in self._render(40, 16):
            self.assertLessEqual(cells(line), 40, line)

    # -- selection -----------------------------------------------------
    def test_selection_is_visible_in_compact_mode(self):
        select(self.state, self.rows, 40)
        lines = self._render(40, 16)
        self.assertTrue(any(line.startswith(">") for line in lines), lines)

    def test_selection_is_visible_at_end_of_list(self):
        select(self.state, self.rows, len(self.rows) - 1)
        lines = self._render(40, 16)
        self.assertTrue(any(line.startswith(">") for line in lines), lines)

    def test_selection_is_visible_at_normal_size(self):
        select(self.state, self.rows, len(self.rows) // 2)
        lines = self._render(80, 24)
        self.assertTrue(any(line.startswith(">") for line in lines), lines)

    # -- detail --------------------------------------------------------
    def test_detail_overlay_is_bounded(self):
        self.state.detail_id = self.rows[0]["id"]
        lines = self._render(80, 24)
        self.assertTrue(lines)
        self.assertLessEqual(len(lines), 24 - 3)
        for line in lines:
            self.assertLessEqual(cells(line), 80, line)

    def test_detail_overlay_scrolls_instead_of_dropping_tail(self):
        state = build_state(self.snap, page=ALERTS)
        rows = alert_rows(self.snap["alerts"]["alerts"], "")
        select(state, rows, 0)
        state.detail_id = rows[0]["id"]
        first = views.body_lines(state, self.snap, 80, 16, False, detail_scroll=0)
        later = views.body_lines(state, self.snap, 80, 16, False, detail_scroll=4)
        self.assertLessEqual(len(first), 13)
        self.assertNotEqual(first[0], later[0])
        self.assertTrue(any("more" in line for line in first), first)

    def test_wide_body_panes_stay_bounded(self):
        self.state.detail_id = self.rows[0]["id"]
        lines = self._render(140, 30)
        self.assertLessEqual(len(lines), 30 - 3)
        for line in lines:
            self.assertLessEqual(cells(line), 140, line)


def _epoch(iso):
    from datetime import datetime
    return datetime.fromisoformat(iso).timestamp()


if __name__ == "__main__":
    unittest.main(verbosity=2)
