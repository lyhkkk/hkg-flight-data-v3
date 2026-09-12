"""State reducer: pure transitions over (state, rows, action)."""

import unittest

from hkg_flight.terminal.presenter import DEPARTURES, ARRIVALS, ALERTS, AIRLINES
from hkg_flight.terminal.state import (
    SELECTION_LOST_MESSAGE,
    AppState,
    dispatch,
    park,
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


def timed_rows(*times):
    return [{"id": "r%d" % i, "record": {"id": "r%d" % i, "time": t}}
            for i, t in enumerate(times)]


def clock_rows(count, step=5):
    """``count`` rows five minutes apart from midnight."""
    return timed_rows(*["%02d:%02d" % (i // 60, i % 60)
                        for i in range(0, count * step, step)])


class TestTimeAnchor(unittest.TestCase):
    """Parking on the clock, and handing the list back to it."""

    def test_park_puts_the_current_flight_at_the_top(self):
        state = AppState()
        rows = timed_rows("08:00", "10:00", "12:00", "14:00")
        park(state, rows, 11 * 60)
        page = state.pages[DEPARTURES]
        self.assertEqual(page.offset, 2)
        self.assertEqual(page.selected_index, 2)
        self.assertEqual(page.selected_id, "r2")
        self.assertEqual(page.anchor_minutes, 11 * 60)

    def test_park_on_a_board_that_is_all_in_the_past_shows_the_tail(self):
        state = AppState()
        rows = timed_rows("01:00", "02:00", "03:00")
        park(state, rows, 23 * 60)
        self.assertEqual(state.pages[DEPARTURES].offset, 2)

    def test_park_on_an_empty_board_is_harmless(self):
        state = AppState()
        park(state, [], 12 * 60)
        page = state.pages[DEPARTURES]
        self.assertEqual(page.offset, 0)
        self.assertIsNone(page.selected_id)

    def test_reconcile_follows_the_clock_while_it_is_auto(self):
        state = AppState()
        rows = timed_rows("08:00", "10:00", "12:00", "14:00")
        park(state, rows, 9 * 60)
        reconcile(state, rows, 13 * 60)
        self.assertEqual(state.pages[DEPARTURES].offset, 3)

    def test_reconcile_leaves_a_pinned_page_where_the_user_left_it(self):
        state = AppState()
        rows = timed_rows("08:00", "10:00", "12:00", "14:00")
        park(state, rows, 9 * 60)
        dispatch(state, rows, {"type": "move", "direction": "down"})
        before = state.pages[DEPARTURES].selected_id
        reconcile(state, rows, 13 * 60)
        self.assertEqual(state.pages[DEPARTURES].selected_id, before)

    def test_reconcile_without_a_clock_keeps_the_id_matching_behaviour(self):
        # The plain adapter and the tests call reconcile with no clock; the
        # selection must still be found by identity.
        state = AppState()
        rows = timed_rows("08:00", "10:00", "12:00")
        park(state, rows, 10 * 60)
        reconcile(state, rows)
        self.assertEqual(state.pages[DEPARTURES].selected_id, "r1")

    def test_moving_the_cursor_pins_the_anchor(self):
        state = AppState()
        rows = timed_rows("08:00", "10:00", "12:00")
        park(state, rows, 9 * 60)
        self.assertTrue(state.pages[DEPARTURES].anchor_auto)
        dispatch(state, rows, {"type": "move", "direction": "down"})
        self.assertFalse(state.pages[DEPARTURES].anchor_auto)

    def test_home_and_end_pin_the_anchor_too(self):
        for direction in ("home", "end"):
            state = AppState()
            rows = timed_rows("08:00", "10:00", "12:00")
            park(state, rows, 9 * 60)
            dispatch(state, rows, {"type": "move", "direction": direction})
            self.assertFalse(state.pages[DEPARTURES].anchor_auto, direction)

    def test_anchor_step_advances_by_exactly_one_screen(self):
        # The regression this guards: stepping the *selection* let the
        # renderer's keep-the-selection-visible rule pull the viewport back to
        # within a row, so a "page down" moved the screen by one row instead.
        state = AppState()
        rows = clock_rows(120)
        park(state, rows, 0)
        page = state.pages[DEPARTURES]
        self.assertEqual(page.offset, 0)
        for expected in (20, 40):
            dispatch(state, rows,
                     {"type": "anchor_step", "direction": "next", "capacity": 20})
            self.assertEqual(page.offset, expected)
        dispatch(state, rows,
                 {"type": "anchor_step", "direction": "prev", "capacity": 20})
        self.assertEqual(page.offset, 20)

    def test_consecutive_screens_are_contiguous(self):
        state = AppState()
        rows = clock_rows(120)
        park(state, rows, 0)
        page = state.pages[DEPARTURES]
        screens = []
        for _ in range(5):
            screens.append(list(range(page.offset, page.offset + 20)))
            dispatch(state, rows,
                     {"type": "anchor_step", "direction": "next", "capacity": 20})
        flat = [index for screen in screens for index in screen]
        self.assertEqual(len(flat), len(set(flat)), "screens must not overlap")
        self.assertEqual(flat, sorted(flat), "screens must run forward")

    def test_anchor_step_clamps_at_both_ends(self):
        state = AppState()
        rows = clock_rows(120)
        park(state, rows, 0)
        page = state.pages[DEPARTURES]
        dispatch(state, rows,
                 {"type": "anchor_step", "direction": "prev", "capacity": 20})
        self.assertEqual(page.offset, 0)
        for _ in range(20):
            dispatch(state, rows,
                     {"type": "anchor_step", "direction": "next", "capacity": 20})
        self.assertEqual(page.offset, len(rows) - 1)

    def test_anchor_step_records_the_new_top_row_and_pins(self):
        state = AppState()
        rows = timed_rows("08:00", "08:05", "08:10", "08:15")
        park(state, rows, 0)
        dispatch(state, rows,
                 {"type": "anchor_step", "direction": "next", "capacity": 2})
        page = state.pages[DEPARTURES]
        self.assertEqual(page.offset, 2)
        self.assertEqual(page.anchor_minutes, 8 * 60 + 10)
        self.assertFalse(page.anchor_auto)

    def test_anchor_now_hands_the_list_back_to_the_clock(self):
        state = AppState()
        rows = timed_rows("08:00", "10:00", "12:00", "14:00")
        park(state, rows, 9 * 60)
        dispatch(state, rows,
                 {"type": "anchor_step", "direction": "next", "capacity": 2})
        self.assertFalse(state.pages[DEPARTURES].anchor_auto)
        dispatch(state, rows, {"type": "anchor_now", "minutes": 13 * 60})
        page = state.pages[DEPARTURES]
        self.assertTrue(page.anchor_auto)
        self.assertEqual(page.offset, 3)
        self.assertEqual(page.anchor_minutes, 13 * 60)

    def test_anchor_actions_do_nothing_off_the_flight_pages(self):
        state = AppState()
        rows = timed_rows("08:00", "10:00")
        dispatch(state, rows, {"type": "page", "page": ALERTS})
        dispatch(state, rows,
                 {"type": "anchor_step", "direction": "next", "capacity": 5})
        dispatch(state, rows, {"type": "anchor_now", "minutes": 600})
        self.assertEqual(state.pages[ALERTS].offset, 0)
        self.assertIsNone(state.pages[ALERTS].anchor_minutes)


PREV = "2026-09-11"
DAY = "2026-09-12"
NEXT = "2026-09-13"


def dated_rows(*day_times):
    """Rows carrying a service date, in display order."""
    return [{"id": "%s %s" % (day, time), "record": {"date": day, "time": time}}
            for day, time in day_times]


class TestTimeAnchorAcrossDates(unittest.TestCase):
    """The anchor names a moment, so it carries a date as well as a time."""

    def board(self):
        return dated_rows((PREV, "08:00"), (PREV, "09:00"),
                          (DAY, "08:00"), (DAY, "09:00"),
                          (NEXT, "00:05"))

    def test_park_records_the_date_it_parked_on(self):
        state = AppState()
        park(state, self.board(), 8 * 60, DAY)
        page = state.pages[DEPARTURES]
        self.assertEqual(page.anchor_minutes, 8 * 60)
        self.assertEqual(page.anchor_date, DAY)
        self.assertEqual(page.offset, 2)

    def test_without_the_date_the_same_minutes_land_a_day_earlier(self):
        # The negative control: this is the bug the date exists to prevent.
        state = AppState()
        park(state, self.board(), 8 * 60)
        self.assertEqual(state.pages[DEPARTURES].offset, 0)

    def test_stepping_past_midnight_records_the_new_date(self):
        state = AppState()
        rows = dated_rows((DAY, "23:50"), (NEXT, "00:05"))
        park(state, rows, 23 * 60 + 30, DAY)
        page = state.pages[DEPARTURES]
        self.assertEqual(page.offset, 0)
        dispatch(state, rows, {"type": "anchor_step", "direction": "next", "capacity": 1})
        self.assertEqual(page.offset, 1)
        self.assertEqual(page.anchor_minutes, 5)
        self.assertEqual(page.anchor_date, NEXT)

    def test_stepping_back_over_midnight_records_the_earlier_date(self):
        state = AppState()
        rows = dated_rows((PREV, "23:50"), (DAY, "00:05"))
        park(state, rows, 5, DAY)
        page = state.pages[DEPARTURES]
        self.assertEqual(page.offset, 1)
        dispatch(state, rows, {"type": "anchor_step", "direction": "prev", "capacity": 1})
        self.assertEqual(page.offset, 0)
        self.assertEqual(page.anchor_minutes, 23 * 60 + 50)
        self.assertEqual(page.anchor_date, PREV)

    def test_anchor_now_takes_the_date_from_the_action(self):
        state = AppState()
        rows = dated_rows((DAY, "08:00"), (NEXT, "00:05"))
        park(state, rows, 8 * 60, DAY)
        dispatch(state, rows, {"type": "anchor_step", "direction": "next", "capacity": 1})
        dispatch(state, rows, {"type": "anchor_now", "minutes": 8 * 60, "date": DAY})
        page = state.pages[DEPARTURES]
        self.assertTrue(page.anchor_auto)
        self.assertEqual(page.offset, 0)
        self.assertEqual(page.anchor_date, DAY)

    def test_reconcile_carries_the_date_while_auto(self):
        state = AppState()
        rows = self.board()
        park(state, rows, 0, DAY)
        reconcile(state, rows, 8 * 60, DAY)
        page = state.pages[DEPARTURES]
        self.assertEqual(page.offset, 2)
        self.assertEqual(page.anchor_date, DAY)

    def test_a_row_without_a_date_still_takes_part(self):
        # A payload that omits the date must not take a flight off the board.
        state = AppState()
        rows = [{"id": "x", "record": {"time": "08:00"}}]
        park(state, rows, 7 * 60, DAY)
        self.assertEqual(state.pages[DEPARTURES].offset, 0)


if __name__ == "__main__":
    unittest.main()
