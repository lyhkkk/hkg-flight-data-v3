"""
Tests for the terminal state reducer: focus, search, page switch, Esc,
airline-apply, selection preservation and fallback.
"""

import unittest

from hkg_flight.terminal.state import (
    AppState, dispatch, reconcile, SELECTION_LOST_MESSAGE,
)
from hkg_flight.terminal.presenter import (
    DEPARTURES, ARRIVALS, ALERTS, AIRLINES, visible_rows,
    ROW_ID_FIELDS, MUTABLE_OPERATION_FIELDS, DUPLICATE_MARKER,
    row_identity, duplicate_ordinals,
)
from tests.fixtures.terminal.data import (
    make_flight, make_flights_snapshot, make_airlines,
)


def make_state(snapshot, page=DEPARTURES):
    state = AppState()
    state.current = page
    rows = visible_rows(snapshot, page, "", "", "")
    reconcile(state, rows)
    return state, rows


class TestPageSwitchAndFocus(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_flights_snapshot(40)
        self.state, self.rows = make_state(self.snapshot)

    def test_digit_keys_switch_pages(self):
        for key, page in [("1", DEPARTURES), ("2", ARRIVALS), ("5", ALERTS), ("6", AIRLINES)]:
            state, commands = dispatch(self.state, self.rows, {"type": "page", "page": page})
            self.assertEqual(state.current, page)
            self.assertEqual(state.focus, "list")
            self.assertEqual(commands, [])

    def test_slash_enters_search(self):
        state, _ = dispatch(self.state, self.rows, {"type": "slash"})
        self.assertEqual(state.focus, "search")

    def test_digits_wq_are_text_while_searching(self):
        dispatch(self.state, self.rows, {"type": "slash"})
        for char in "CX261WQ":
            self.state, _ = dispatch(self.state, self.rows, {"type": "search_char", "char": char})
        self.assertEqual(self.state.pages[DEPARTURES].search_text, "CX261WQ")
        self.assertEqual(self.state.current, DEPARTURES)
        self.assertEqual(self.state.focus, "search")

    def test_tab_cycles_focus(self):
        state = self.state
        state, _ = dispatch(state, self.rows, {"type": "tab"})
        self.assertEqual(state.focus, "search")
        state, _ = dispatch(state, self.rows, {"type": "tab"})
        self.assertEqual(state.focus, "list")

    def test_tab_backward(self):
        state = self.state
        state, _ = dispatch(state, self.rows, {"type": "tab", "backward": True})
        self.assertEqual(state.focus, "search")


class TestEscSemantics(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_flights_snapshot(40)
        self.state, self.rows = make_state(self.snapshot)

    def test_esc_in_search_cancels_edit_only(self):
        dispatch(self.state, self.rows, {"type": "slash"})
        self.state, _ = dispatch(self.state, self.rows, {"type": "search_char", "char": "C"})
        self.state, _ = dispatch(self.state, self.rows, {"type": "search_char", "char": "X"})
        self.state, _ = dispatch(self.state, self.rows, {"type": "escape"})
        self.assertEqual(self.state.pages[DEPARTURES].search_text, "")
        self.assertEqual(self.state.focus, "list")
        self.assertEqual(self.state.current, DEPARTURES)

    def test_esc_closes_detail_then_clears_filter_then_nothing(self):
        # open detail
        self.state, _ = dispatch(self.state, self.rows, {"type": "enter"})
        self.assertTrue(self.state.detail_id)
        # Esc closes detail
        self.state, _ = dispatch(self.state, self.rows, {"type": "escape"})
        self.assertIsNone(self.state.detail_id)
        # Esc clears filter (no filter set here -> nothing more, still departures)
        self.state, _ = dispatch(self.state, self.rows, {"type": "escape"})
        self.assertEqual(self.state.current, DEPARTURES)

    def test_auxiliary_page_esc_returns_to_flight_page(self):
        self.state.current = ARRIVALS
        self.state.return_page = ARRIVALS
        self.state, _ = dispatch(self.state, self.rows, {"type": "page", "page": ALERTS})
        self.assertEqual(self.state.return_page, ARRIVALS)
        self.state, _ = dispatch(self.state, self.rows, {"type": "escape"})
        self.assertEqual(self.state.current, ARRIVALS)

    def test_esc_clears_filter_before_returning(self):
        self.state.current = ALERTS
        self.state.return_page = DEPARTURES
        self.state.pages[ALERTS].search_text = "CX"
        self.state, _ = dispatch(self.state, self.rows, {"type": "escape"})
        self.assertEqual(self.state.current, ALERTS)
        self.assertEqual(self.state.pages[ALERTS].search_text, "")
        # next Esc: no overlay, no filter -> return to flight page
        self.state, _ = dispatch(self.state, self.rows, {"type": "escape"})
        self.assertEqual(self.state.current, DEPARTURES)


class TestAirlineApplyAndFilter(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_flights_snapshot(40)
        self.state, self.rows = make_state(self.snapshot)
        self.state.return_page = DEPARTURES

    def test_enter_on_airlines_applies_filter_and_returns(self):
        from hkg_flight.terminal.presenter import airline_rows
        airlines = make_airlines(5)
        air_rows = airline_rows(airlines, "")
        self.state.current = AIRLINES
        self.state.pages[AIRLINES].selected_id = air_rows[0]["id"]
        self.state.pages[AIRLINES].selected_index = 0
        self.state, _ = dispatch(self.state, air_rows, {"type": "enter"})
        self.assertEqual(self.state.current, DEPARTURES)
        self.assertEqual(self.state.pages[DEPARTURES].airline_filter, air_rows[0]["code"])

    def test_filter_status_cycles(self):
        self.state, _ = dispatch(self.state, self.rows, {"type": "toggle_filter"})
        self.assertTrue(self.state.filter_open)
        self.assertEqual(self.state.focus, "filter")
        self.state, _ = dispatch(self.state, self.rows, {"type": "filter_status", "direction": "next"})
        self.assertEqual(self.state.pages[DEPARTURES].status_filter, "scheduled")
        self.state, _ = dispatch(self.state, self.rows, {"type": "toggle_filter"})
        self.assertFalse(self.state.filter_open)


class TestSelectionReconcile(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_flights_snapshot(40)
        self.state, self.rows = make_state(self.snapshot)

    def test_selection_preserved_across_refresh(self):
        original = self.state.pages[DEPARTURES].selected_id
        new_snapshot = make_flights_snapshot(40)
        new_rows = visible_rows(new_snapshot, DEPARTURES, "", "", "")
        reconcile(self.state, new_rows)
        self.assertEqual(self.state.pages[DEPARTURES].selected_id, original)

    def test_selection_falls_back_when_item_disappears(self):
        self.state.pages[DEPARTURES].selected_index = 2
        self.state.pages[DEPARTURES].selected_id = self.rows[2]["id"]
        new_rows = self.rows[:2]
        reconcile(self.state, new_rows)
        self.assertEqual(self.state.pages[DEPARTURES].selected_index, 1)
        self.assertTrue(self.state.message)

    def test_move_home_end(self):
        self.state, _ = dispatch(self.state, self.rows, {"type": "move", "direction": "end", "height": 10})
        self.assertEqual(self.state.pages[DEPARTURES].selected_index, len(self.rows) - 1)
        self.state, _ = dispatch(self.state, self.rows, {"type": "move", "direction": "home", "height": 10})
        self.assertEqual(self.state.pages[DEPARTURES].selected_index, 0)


class TestQuitAndCommands(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_flights_snapshot(5)
        self.state, self.rows = make_state(self.snapshot)

    def test_quit_yields_quit_command(self):
        _, commands = dispatch(self.state, self.rows, {"type": "quit"})
        self.assertEqual(commands, ["quit"])

    def test_refresh_yields_refresh_command(self):
        _, commands = dispatch(self.state, self.rows, {"type": "refresh"})
        self.assertEqual(commands, ["refresh"])


class TestStableIdentity(unittest.TestCase):
    """R02: identity is built from schedule fields only, duplicates included."""

    def setUp(self):
        self.snapshot = make_flights_snapshot(40)

    def test_mutable_fields_are_excluded_from_the_contract(self):
        for field in MUTABLE_OPERATION_FIELDS:
            self.assertNotIn(field, ROW_ID_FIELDS, field)
        for field in ROW_ID_FIELDS:
            self.assertNotIn(field, MUTABLE_OPERATION_FIELDS, field)

    def test_identity_ignores_every_mutable_field(self):
        base = row_identity(make_flight(0))
        for field in MUTABLE_OPERATION_FIELDS:
            updated = make_flight(0)
            updated[field] = "CHANGED"
            self.assertEqual(row_identity(updated), base, field)

    def test_identity_changes_with_every_schedule_field(self):
        base = row_identity(make_flight(0))
        for field in ROW_ID_FIELDS:
            updated = make_flight(0)
            updated[field] = "CHANGED"
            self.assertNotEqual(row_identity(updated), base, field)

    def test_same_day_duplicate_segments_stay_distinct(self):
        rows = visible_rows(self.snapshot, ARRIVALS, "", "", "")
        ids = [row["id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertTrue([i for i in ids if DUPLICATE_MARKER in i], ids)

    def test_duplicate_ids_survive_mutable_updates(self):
        rows = visible_rows(self.snapshot, ARRIVALS, "", "", "")
        before = [row["id"] for row in rows]
        for row in rows:
            row["record"].update(
                stand="ZZ9", belt="99", status="Boarding",
                status_category="boarding", gate="1", terminal="T2",
                hall="Z", aisle="Q")
        after = [row["id"] for row in visible_rows(self.snapshot, ARRIVALS, "", "", "")]
        self.assertEqual(after, before)

    def test_duplicate_ordinals_are_deterministic(self):
        records = [make_flight(0), make_flight(0), make_flight(1), make_flight(0)]
        self.assertEqual(duplicate_ordinals(records), [0, 1, 0, 2])
        # Same input, same output -- never a random or per-refresh counter.
        self.assertEqual(duplicate_ordinals(records), [0, 1, 0, 2])

    def test_identity_is_independent_of_search_filter(self):
        unfiltered = {r["id"]: r["record"] for r in
                      visible_rows(self.snapshot, DEPARTURES, "", "", "")}
        searched = visible_rows(self.snapshot, DEPARTURES, "CX", "", "")
        self.assertTrue(searched)
        for row in searched:
            self.assertIn(row["id"], unfiltered)
            self.assertIs(unfiltered[row["id"]], row["record"])


class TestReconcileContinuity(unittest.TestCase):
    """Selection / detail / filter stay continuous; deletion degrades visibly."""

    def setUp(self):
        self.snapshot = make_flights_snapshot(40)
        self.state, self.rows = make_state(self.snapshot)
        self.page = self.state.pages[DEPARTURES]

    def _select(self, index):
        self.page.selected_index = index
        self.page.selected_id = self.rows[index]["id"]
        return self.page.selected_id

    def test_selection_survives_status_and_gate_change(self):
        target = self._select(3)
        self.state.detail_id = target
        for row in self.rows:
            row["record"].update(status="Boarding", status_category="boarding", gate="63")
        reconcile(self.state, visible_rows(self.snapshot, DEPARTURES, "", "", ""))
        self.assertEqual(self.page.selected_id, target)
        self.assertEqual(self.page.selected_index, 3)
        self.assertEqual(self.state.detail_id, target)
        self.assertEqual(self.state.message, "")
        self.assertIsNone(self.state.lost_selection_id)

    def test_selection_survives_reordering(self):
        target = self._select(3)
        reordered = list(reversed(self.rows))
        reconcile(self.state, reordered)
        self.assertEqual(self.page.selected_id, target)
        self.assertEqual(self.page.selected_index, len(reordered) - 4)
        self.assertEqual(self.state.message, "")

    def test_selection_survives_search_typing(self):
        target = self._select(2)
        number = self.rows[2]["record"]["flight_number"]
        searched = visible_rows(self.snapshot, DEPARTURES, number, "", "")
        self.assertTrue(any(r["id"] == target for r in searched))
        reconcile(self.state, searched)
        self.assertEqual(self.page.selected_id, target)
        self.assertEqual(self.state.message, "")

    def test_selection_survives_status_filter_when_flight_still_matches(self):
        target = self._select(2)
        category = self.rows[2]["record"].get("status_category", "")
        if not category:
            self.skipTest("target row has no status_category")
        filtered = visible_rows(self.snapshot, DEPARTURES, "", "", category)
        self.assertTrue(any(r["id"] == target for r in filtered))
        reconcile(self.state, filtered)
        self.assertEqual(self.page.selected_id, target)
        self.assertEqual(self.state.message, "")

    def test_deleted_record_degrades_visibly_and_is_never_reused(self):
        lost = self._select(2)
        remaining = self.rows[:2] + self.rows[3:]
        reconcile(self.state, remaining)
        self.assertNotEqual(self.page.selected_id, lost)
        self.assertEqual(self.page.selected_id, remaining[2]["id"])
        self.assertEqual(self.page.selected_index, 2)
        self.assertEqual(self.state.message, SELECTION_LOST_MESSAGE)
        self.assertEqual(self.state.lost_selection_id, lost)

    def test_reconcile_never_clears_selection_while_rows_exist(self):
        for subset in (self.rows, self.rows[1:], self.rows[:1], list(reversed(self.rows))):
            reconcile(self.state, subset)
            self.assertIsNotNone(self.page.selected_id)
            self.assertIn(self.page.selected_id, [r["id"] for r in subset])

    def test_detail_of_a_deleted_flight_is_not_repointed(self):
        lost = self._select(1)
        self.state.detail_id = lost
        remaining = self.rows[:1] + self.rows[2:]
        reconcile(self.state, remaining)
        # The detail id is left pointing at the entity that went away; the
        # renderer turns that into "Flight no longer available." instead of
        # silently showing a different flight.
        self.assertEqual(self.state.detail_id, lost)
        self.assertNotIn(lost, [r["id"] for r in remaining])


if __name__ == "__main__":
    unittest.main(verbosity=2)
