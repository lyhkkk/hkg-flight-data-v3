"""Presenter behaviour: stable identity, ordering, whitelist search."""

import unittest

from hkg_flight.terminal.presenter import (
    DEPARTURES,
    ARRIVALS,
    alert_rows,
    airline_rows,
    detail_lines,
    duplicate_ordinals,
    matches_filters,
    row_identity,
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


if __name__ == "__main__":
    unittest.main()
