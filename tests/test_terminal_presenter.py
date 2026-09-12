"""Presenter behaviour: stable identity, ordering, whitelist search."""

import unittest

from hkg_flight.terminal.presenter import (
    DEPARTURES,
    ARRIVALS,
    alert_rows,
    airline_rows,
    anchor_index,
    detail_lines,
    duplicate_ordinals,
    matches_filters,
    row_identity,
    row_minutes,
    tokenize,
    visible_rows,
)
from tests.fixtures.terminal.data import (
    make_alert,
    make_alerts,
    make_airlines,
    make_flight,
    make_flights,
)


def snapshot(records):
    return {"records": records}


class TestRowIdentity(unittest.TestCase):
    def test_identity_is_stable_across_operational_updates(self):
        rec = make_flight(0)
        before = row_identity(rec)
        updated = dict(rec, gate="999", stand="X9", status="Departed 09:00",
                       status_category="departed", terminal="T2", belt="7")
        self.assertEqual(row_identity(updated), before)

    def test_identity_differs_for_different_schedule(self):
        self.assertNotEqual(row_identity(make_flight(0)), row_identity(make_flight(1)))

    def test_duplicate_segments_get_distinct_deterministic_ordinals(self):
        recs = [make_flight(1), make_flight(1), make_flight(1)]
        self.assertEqual(duplicate_ordinals(recs), [0, 1, 2])
        # Same dataset -> same ordinals, every time.
        self.assertEqual(duplicate_ordinals(recs), [0, 1, 2])
        ids = {row_identity(r, o) for r, o in zip(recs, duplicate_ordinals(recs))}
        self.assertEqual(len(ids), 3)


class TestVisibleRows(unittest.TestCase):
    def setUp(self):
        self.records = make_flights(20)

    def test_departures_and_arrivals_are_partitioned(self):
        dep = visible_rows(snapshot(self.records), DEPARTURES, "")
        arr = visible_rows(snapshot(self.records), ARRIVALS, "")
        self.assertTrue(dep and arr)
        self.assertTrue(all(r["record"]["type"] == "departure" for r in dep))
        self.assertTrue(all(r["record"]["type"] == "arrival" for r in arr))

    def test_rows_are_sorted_by_time(self):
        rows = visible_rows(snapshot(self.records), DEPARTURES, "")
        times = [r["record"]["time"] for r in rows]
        self.assertEqual(times, sorted(times))

    def test_row_id_does_not_depend_on_search_text(self):
        unfiltered = visible_rows(snapshot(self.records), DEPARTURES, "")
        filtered = visible_rows(snapshot(self.records), DEPARTURES, "CX")
        ids = {r["id"] for r in unfiltered}
        self.assertTrue({r["id"] for r in filtered} <= ids)

    def test_search_matches_flight_number(self):
        rows = visible_rows(snapshot(self.records), DEPARTURES, "CX")
        self.assertTrue(rows)
        self.assertTrue(all("CX" in r["record"]["flight_number"] for r in rows))

    def test_search_normalizes_spaces_in_flight_number(self):
        rec = make_flight(0)
        number = rec["flight_number"]
        spaced = f"{number[:2]} {number[2:]}"
        rows = visible_rows(snapshot([rec]), DEPARTURES, spaced)
        self.assertEqual(len(rows), 1)

    def test_search_matches_route_terminal_and_status(self):
        rec = make_flight(0)
        dep = visible_rows(snapshot([rec]), DEPARTURES, "")
        self.assertTrue(dep)
        for term in (rec["destination"], rec["terminal"], rec["status"]):
            if not term:
                continue
            self.assertEqual(len(visible_rows(snapshot([rec]), DEPARTURES, term)), 1,
                             f"expected a match for {term!r}")

    def test_search_matches_codeshare_number(self):
        rec = next(r for r in self.records if "|" in r["all_flight_numbers"])
        codeshare = rec["all_flight_numbers"].split("|")[1]
        rows = visible_rows(snapshot([rec]), DEPARTURES, codeshare)
        self.assertEqual(len(rows), 1)

    def test_terms_are_anded(self):
        rec = make_flight(0)
        self.assertEqual(len(visible_rows(snapshot([rec]), DEPARTURES, rec["flight_number"])), 1)
        self.assertEqual(
            len(visible_rows(snapshot([rec]), DEPARTURES, f"{rec['flight_number']} NOPE")), 0)

    def test_structured_filters(self):
        rec = make_flight(0)
        self.assertTrue(matches_filters(rec, airline=rec["airline_code"]))
        self.assertTrue(matches_filters(rec, status=rec["status_category"]))
        self.assertFalse(matches_filters(rec, status="cancelled-not-real"))

    def test_empty_search_returns_everything(self):
        dep = visible_rows(snapshot(self.records), DEPARTURES, "")
        self.assertEqual(len(dep), sum(1 for r in self.records if r["type"] == "departure"))


class TestTokenize(unittest.TestCase):
    def test_lowercases_and_splits(self):
        self.assertEqual(tokenize("  CX  759 "), ["cx", "759"])

    def test_empty(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize(None), [])


class TestAlertsAndAirlines(unittest.TestCase):
    def test_alerts_are_newest_first(self):
        alerts = make_alerts(10)
        rows = alert_rows(alerts, "")
        raised = [r["record"]["raised_at"] for r in rows]
        self.assertEqual(raised, sorted(raised, reverse=True))

    def test_alert_search_matches_change_fields(self):
        alert = make_alert(0)
        rows = alert_rows([alert], alert["flight_number"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(alert_rows([alert], "definitely-not-there")), 0)

    def test_airlines_sorted_by_code(self):
        rows = airline_rows(make_airlines(12), "")
        codes = [r["code"] for r in rows]
        self.assertEqual(codes, sorted(codes))

    def test_airline_search_matches_code_and_name(self):
        rows = airline_rows(make_airlines(5), "")
        self.assertTrue(rows)
        first = rows[0]
        self.assertEqual(len(airline_rows(make_airlines(5), first["code"])), 1)


class TestDetailLines(unittest.TestCase):
    def test_labels_and_optional_fields(self):
        rec = make_flight(1)  # arrival, may carry stand/hall/belt
        lines = detail_lines(rec)
        labels = [label for label, _ in lines]
        self.assertIn("Flight", labels)
        self.assertIn("Route", labels)
        self.assertIn("Gate/Stand", labels)
        self.assertEqual(len(dict(lines)), len(lines), "labels must be unique")

    def test_codeshares_are_listed(self):
        rec = next(r for r in make_flights(20) if "|" in r["all_flight_numbers"])
        labels = dict(detail_lines(rec))
        self.assertIn("Codeshare", labels)


class TestAnchorIndexAcrossDates(unittest.TestCase):
    """A board that spans midnight: the anchor is a ``(date, time)`` position.

    Rows are ordered by ``(date, time)``, so comparing time-of-day alone parks
    the viewport on yesterday's flight at the same hour - a whole day in the
    past, which is what the 22:00-01:59 window would otherwise show.
    """

    PREV = "2026-09-11"
    DAY = "2026-09-12"
    NEXT = "2026-09-13"

    @classmethod
    def rows(cls, *day_times):
        return [{"id": "%s %s" % (day, time), "record": {"date": day, "time": time}}
                for day, time in day_times]

    def board(self):
        """Yesterday and today - the window at 01:30 in the morning."""
        return self.rows((self.PREV, "01:30"), (self.PREV, "08:00"), (self.PREV, "23:50"),
                         (self.DAY, "01:30"), (self.DAY, "08:00"), (self.DAY, "23:50"))

    def test_the_date_is_what_stops_the_anchor_falling_a_day_behind(self):
        # The negative control for the test below: with no date, the very same
        # rows anchor on yesterday's 08:00.
        self.assertEqual(anchor_index(self.board(), 8 * 60), 1)

    def test_the_anchor_lands_on_todays_row_of_the_same_hour(self):
        self.assertEqual(anchor_index(self.board(), 8 * 60, self.DAY), 4)
        self.assertEqual(anchor_index(self.board(), 1 * 60 + 30, self.DAY), 3)
        self.assertEqual(anchor_index(self.board(), 0, self.DAY), 3)

    def test_a_time_before_todays_first_row_lands_on_todays_first_row(self):
        rows = self.rows((self.DAY, "08:00"), (self.DAY, "09:00"))
        self.assertEqual(anchor_index(rows, 0, self.DAY), 0)

    def test_todays_last_row_wins_over_an_earlier_hour_tomorrow(self):
        # At 23:30 the next flight is today's 23:50, not tomorrow's 00:05: the
        # list is ordered by date first, and so is the anchor.
        rows = self.rows((self.DAY, "23:50"), (self.NEXT, "00:05"))
        self.assertEqual(anchor_index(rows, 23 * 60 + 30, self.DAY), 0)

    def test_tomorrow_is_reachable_once_today_is_exhausted(self):
        rows = self.rows((self.DAY, "23:50"), (self.NEXT, "00:05"))
        self.assertEqual(anchor_index(rows, 23 * 60 + 55, self.DAY), 1)

    def test_everything_in_the_past_still_returns_the_end(self):
        self.assertEqual(anchor_index(self.board(), 23 * 60 + 55, self.DAY), 6)

    def test_a_row_with_no_date_belongs_to_the_day_being_anchored(self):
        # The payload omitted the date, the schedule did not; refusing the row
        # over a missing field would take a flight off the board.
        rows = [{"id": "x", "record": {"time": "08:00"}}]
        self.assertEqual(anchor_index(rows, 7 * 60, self.DAY), 0)
        self.assertEqual(anchor_index(rows, 9 * 60, self.DAY), 1)

    def test_a_board_of_one_date_behaves_exactly_as_before(self):
        # Passing the date must not change a one-date board: every row is on
        # that date, so the comparison reduces to the time.
        rows = self.rows((self.DAY, "08:00"), (self.DAY, "09:30"), (self.DAY, "11:00"))
        for minutes in (0, 8 * 60, 9 * 60 + 31, 23 * 60):
            self.assertEqual(anchor_index(rows, minutes),
                             anchor_index(rows, minutes, self.DAY), minutes)


class TestAnchorIndex(unittest.TestCase):
    """The anchor is the earliest row at or after the clock - and nothing else."""

    @staticmethod
    def rows(*times):
        return [{"id": "r%d" % i, "record": {"time": t}}
                for i, t in enumerate(times)]

    def test_finds_the_first_row_at_or_after_the_clock(self):
        rows = self.rows("08:00", "09:30", "11:00", "13:45")
        self.assertEqual(anchor_index(rows, 0), 0)
        self.assertEqual(anchor_index(rows, 9 * 60 + 30), 1)
        self.assertEqual(anchor_index(rows, 9 * 60 + 31), 2)

    def test_a_row_exactly_on_the_clock_counts(self):
        self.assertEqual(anchor_index(self.rows("12:00"), 12 * 60), 0)

    def test_everything_in_the_past_returns_the_end(self):
        # The caller clamps to the tail, so a board with nothing left shows its
        # last flights rather than an empty screen.
        rows = self.rows("01:00", "02:00")
        self.assertEqual(anchor_index(rows, 23 * 60), 2)

    def test_an_empty_list_returns_zero(self):
        self.assertEqual(anchor_index([], 12 * 60), 0)

    def test_rows_without_a_readable_time_are_skipped(self):
        rows = self.rows("", "garbage", "25:00", "12:60", "10:00")
        self.assertEqual(anchor_index(rows, 9 * 60), 4)

    def test_a_row_without_a_time_never_becomes_the_anchor(self):
        # Those rows sort to the front (their sort key is ""), so the anchor
        # must scan rather than trust the order.
        self.assertEqual(anchor_index(self.rows("", "13:00"), 12 * 60), 1)

    def test_row_minutes_reads_a_well_formed_time(self):
        self.assertEqual(row_minutes({"time": "07:05"}), 7 * 60 + 5)
        self.assertEqual(row_minutes({"time": " 07:05 "}), 7 * 60 + 5)
        self.assertEqual(row_minutes({"time": "00:00"}), 0)
        self.assertEqual(row_minutes({"time": "23:59"}), 23 * 60 + 59)

    def test_row_minutes_reads_an_unpadded_time(self):
        # A real departure time either way; refusing it over its padding would
        # take a flight off the board.
        self.assertEqual(row_minutes({"time": "7:05"}), 7 * 60 + 5)
        self.assertEqual(row_minutes({"time": "7:5"}), 7 * 60 + 5)

    def test_row_minutes_rejects_anything_else(self):
        for bad in ("", "   ", "12", "12:", "abc", "25:00", "12:60",
                    "-1:00", "1:234", "12:5x", None, 705):
            self.assertIsNone(row_minutes({"time": bad}), bad)
        self.assertIsNone(row_minutes({}))


if __name__ == "__main__":
    unittest.main()
