"""State reducer: pure transitions over (state, rows, action)."""

import unittest

from hkg_flight.terminal.presenter import DEPARTURES, ARRIVALS, ALERTS, AIRLINES
from hkg_flight.terminal.state import (
    SELECTION_LOST_MESSAGE,
    AppState,
    dispatch,
    reconcile,
)


def make_rows(*ids):
    return [{"id": i, "record": {"id": i}} for i in ids]


def fresh(ids=("a", "b", "c")):
    state = AppState()
    rows = make_rows(*ids)
    reconcile(state, rows)
    return state, rows


class TestPageAndFocus(unittest.TestCase):
    def test_page_switch_resets_overlays(self):
        state, rows = fresh()
        state.help_open = True
        state.detail_id = "a"
        dispatch(state, rows, {"type": "page", "page": ARRIVALS})
        self.assertEqual(state.current, ARRIVALS)
        self.assertFalse(state.help_open)
        self.assertIsNone(state.detail_id)
        self.assertEqual(state.focus, "list")

    def test_page_switch_to_unknown_page_is_ignored(self):
        state, rows = fresh()
        dispatch(state, rows, {"type": "page", "page": "nope"})
        self.assertEqual(state.current, DEPARTURES)

    def test_aux_page_returns_to_last_flight_page(self):
        state, rows = fresh()
        dispatch(state, rows, {"type": "page", "page": ARRIVALS})
        dispatch(state, rows, {"type": "page", "page": ALERTS})
        dispatch(state, rows, {"type": "escape"})
        self.assertEqual(state.current, ARRIVALS)

    def test_tab_cycles_focus(self):
        state, rows = fresh()
        dispatch(state, rows, {"type": "tab"})
        self.assertEqual(state.focus, "search")
        dispatch(state, rows, {"type": "tab", "backward": True})
        self.assertEqual(state.focus, "list")


class TestMovement(unittest.TestCase):
    def test_down_and_up_clamp(self):
        state, rows = fresh()
        dispatch(state, rows, {"type": "move", "direction": "down"})
        self.assertEqual(state.pages[DEPARTURES].selected_index, 1)
        dispatch(state, rows, {"type": "move", "direction": "up"})
        dispatch(state, rows, {"type": "move", "direction": "up"})
        self.assertEqual(state.pages[DEPARTURES].selected_index, 0)

    def test_home_and_end(self):
        state, rows = fresh(("a", "b", "c", "d"))
        dispatch(state, rows, {"type": "move", "direction": "end"})
        self.assertEqual(state.pages[DEPARTURES].selected_index, 3)
        dispatch(state, rows, {"type": "move", "direction": "home"})
        self.assertEqual(state.pages[DEPARTURES].selected_index, 0)

    def test_page_move_uses_height(self):
        state, rows = fresh(tuple(str(i) for i in range(30)))
        dispatch(state, rows, {"type": "move", "direction": "pgdn", "height": 10})
        self.assertEqual(state.pages[DEPARTURES].selected_index, 10)

    def test_movement_ignored_with_no_rows(self):
        state = AppState()
        reconcile(state, [])
        dispatch(state, [], {"type": "move", "direction": "down"})
        self.assertEqual(state.pages[DEPARTURES].selected_index, 0)

    def test_scroll_window_follows_selection(self):
        state, rows = fresh(tuple(str(i) for i in range(30)))
        for _ in range(20):
            dispatch(state, rows, {"type": "move", "direction": "down", "height": 10})
        page = state.pages[DEPARTURES]
        self.assertLessEqual(page.offset, page.selected_index)
        self.assertLess(page.selected_index, page.offset + 10)


class TestSearch(unittest.TestCase):
    def test_search_edit_submit(self):
        state, rows = fresh()
        dispatch(state, rows, {"type": "slash"})
        self.assertEqual(state.focus, "search")
        dispatch(state, rows, {"type": "search_char", "char": "C"})
        dispatch(state, rows, {"type": "search_char", "char": "X"})
        self.assertEqual(state.pages[DEPARTURES].search_text, "CX")
        dispatch(state, rows, {"type": "search_backspace"})
        self.assertEqual(state.pages[DEPARTURES].search_text, "C")
        dispatch(state, rows, {"type": "search_submit"})
        self.assertEqual(state.focus, "list")
        self.assertEqual(state.pages[DEPARTURES].search_text, "C")

    def test_search_cancel_restores_pre_edit_text(self):
        state, rows = fresh()
        state.pages[DEPARTURES].search_text = "keep"
        dispatch(state, rows, {"type": "slash"})
        dispatch(state, rows, {"type": "search_char", "char": "X"})
        dispatch(state, rows, {"type": "search_cancel"})
        self.assertEqual(state.pages[DEPARTURES].search_text, "keep")

    def test_slash_is_ignored_on_airlines_page(self):
        state, rows = fresh()
        dispatch(state, rows, {"type": "page", "page": AIRLINES})
        dispatch(state, rows, {"type": "slash"})
        self.assertNotEqual(state.focus, "search")


class TestDetailAndFilter(unittest.TestCase):
    def test_enter_opens_detail_on_flight_page(self):
        state, rows = fresh()
        dispatch(state, rows, {"type": "enter"})
        self.assertEqual(state.detail_id, "a")
        self.assertEqual(state.focus, "detail")

    def test_enter_on_airlines_applies_filter_and_returns(self):
        state = AppState()
        state.current = AIRLINES
        airline_rows = [{"id": "CX", "record": {"code": "CX"}, "code": "CX", "name": "Cathay"}]
        reconcile(state, airline_rows)
        dispatch(state, airline_rows, {"type": "enter"})
        self.assertEqual(state.current, DEPARTURES)
        self.assertEqual(state.pages[DEPARTURES].airline_filter, "CX")

    def test_escape_closes_detail_then_clears_filter(self):
        state, rows = fresh()
        dispatch(state, rows, {"type": "enter"})
        dispatch(state, rows, {"type": "escape"})
        self.assertIsNone(state.detail_id)
        state.pages[DEPARTURES].search_text = "CX"
        dispatch(state, rows, {"type": "escape"})
        self.assertEqual(state.pages[DEPARTURES].search_text, "")

    def test_filter_panel_cycles_status(self):
        state, rows = fresh()
        dispatch(state, rows, {"type": "toggle_filter"})
        self.assertTrue(state.filter_open)
        self.assertEqual(state.focus, "filter")
        dispatch(state, rows, {"type": "filter_status", "direction": "next"})
        self.assertTrue(state.pages[DEPARTURES].status_filter)
        dispatch(state, rows, {"type": "toggle_filter"})
        self.assertFalse(state.filter_open)
        self.assertEqual(state.focus, "list")

    def test_help_toggles(self):
        state, rows = fresh()
        dispatch(state, rows, {"type": "help"})
        self.assertTrue(state.help_open)
        dispatch(state, rows, {"type": "help"})
        self.assertFalse(state.help_open)


class TestCommands(unittest.TestCase):
    def test_side_effect_commands_are_returned(self):
        state, rows = fresh()
        for action, expected in (
            ({"type": "refresh"}, "refresh"),
            ({"type": "web"}, "web_toggle"),
            ({"type": "quit"}, "quit"),
        ):
            _, commands = dispatch(state, rows, action)
            self.assertEqual(commands, [expected])

    def test_plain_move_returns_no_commands(self):
        state, rows = fresh()
        _, commands = dispatch(state, rows, {"type": "move", "direction": "down"})
        self.assertEqual(commands, [])


class TestReconcile(unittest.TestCase):
    def test_selection_follows_entity_not_position(self):
        state, rows = fresh(("a", "b", "c"))
        state.pages[DEPARTURES].selected_id = "c"
        reconcile(state, make_rows("c", "a", "b"))
        page = state.pages[DEPARTURES]
        self.assertEqual(page.selected_id, "c")
        self.assertEqual(page.selected_index, 0)

    def test_disappearing_selection_degrades_visibly(self):
        state, rows = fresh(("a", "b", "c"))
        state.pages[DEPARTURES].selected_id = "b"
        state.pages[DEPARTURES].selected_index = 1
        reconcile(state, make_rows("a", "c"))
        self.assertEqual(state.pages[DEPARTURES].selected_id, "c")
        self.assertEqual(state.message, SELECTION_LOST_MESSAGE)

    def test_empty_rows_clear_selection(self):
        state, rows = fresh()
        reconcile(state, [])
        page = state.pages[DEPARTURES]
        self.assertIsNone(page.selected_id)
        self.assertEqual(page.selected_index, 0)
        self.assertEqual(page.offset, 0)

    def test_first_selection_defaults_to_first_row(self):
        state = AppState()
        reconcile(state, make_rows("x", "y"))
        self.assertEqual(state.pages[DEPARTURES].selected_id, "x")


if __name__ == "__main__":
    unittest.main()
