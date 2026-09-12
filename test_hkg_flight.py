"""
Core regression suite for hkg_flight.

Covers the standard-library backend: utilities, cache, normalization, alerts,
the API client, the poller, the web server and the CLI. Behaviour is asserted
through public interfaces; no test reaches into poller/session internals.
"""

import os
import re
import shutil
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta

from hkg_flight import cli
from hkg_flight.alerts import AlertManager
from hkg_flight.api import APIClient
from hkg_flight.cache import CacheSystem
from hkg_flight.poller import Poller
from hkg_flight.terminal import views
from hkg_flight.utils import (
    DEFAULT_WIDTH,
    HKT,
    MAX_WIDTH,
    board_dates,
    clean_text,
    gate_stand_text,
    make_flight_key,
    normalize_flight_number,
    normalize_flights,
    now_hkt,
    route_text,
    sort_flights,
    status_category,
    terminal_width,
    today_str,
    validate_date,
)
from hkg_flight.web import WebServer

TODAY = today_str()


def clock_at(hour, minute=0, day=None):
    """A fixed HKT clock reading, so no assertion depends on the wall clock.

    Tests that let the real clock decide whether the board spans one service
    date or two only pass outside the 22:00-01:59 band.
    """
    date_str = day or TODAY
    year, month, day_of_month = (int(part) for part in date_str.split("-"))
    return datetime(year, month, day_of_month, hour, minute, tzinfo=HKT)


def shift_day(date_str, days):
    """``date_str`` moved by ``days``, in the same YYYY-MM-DD form."""
    year, month, day_of_month = (int(part) for part in date_str.split("-"))
    return (date(year, month, day_of_month) + timedelta(days=days)).isoformat()


def payload(no, gate=None, stand=None, status="Scheduled", arrival=False,
            airline="CX", date_str=None, cargo=False, destination=None, origin=None):
    """Build one raw HKIA entry (arrivals carry origins, departures destinations)."""
    flight_obj = {
        "flight": [{"airline": airline, "no": no}],
        "time": "08:40",
        "status": status,
        "gate": gate,
        "stand": stand,
        "terminal": "T1",
        "destination": destination if destination is not None else ([] if arrival else ["NRT"]),
        "origin": origin if origin is not None else (["SYD"] if arrival else []),
    }
    return {"arrival": arrival, "cargo": cargo, "date": date_str or TODAY, "list": [flight_obj]}


class FakeAPI:
    """Minimal APIClient stand-in: serves a fixed payload or raises.

    ``data`` is either one payload for every date, or a ``{date: payload}``
    mapping. A board that spans midnight asks for two dates, and the two days
    have to be distinguishable or the merge cannot be checked.
    """

    def __init__(self, data=None, fail=False, cache=None):
        self.data = data
        self.fail = fail
        self.cache = cache
        self.calls = 0
        self.dates = []

    def fetch_flights(self, date_str):
        self.calls += 1
        self.dates.append(date_str)
        if self.fail:
            raise RuntimeError("network down")
        payload = self.data.get(date_str) if isinstance(self.data, dict) else self.data
        if payload is not None and self.cache is not None:
            self.cache.write_flights(date_str, payload)
        return payload

    def fetch_airlines_meta(self):
        return {"airlines": [{"code": "CX", "description": ["Cathay"]}],
                "source": "api", "ok": True, "error": None}


class TempCacheCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = CacheSystem(cache_dir=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------- utilities

class TestUtils(unittest.TestCase):
    def test_today_str_format(self):
        self.assertRegex(today_str(), r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(today_str(), date.today().isoformat())

    def test_validate_date(self):
        self.assertTrue(validate_date("2026-09-11"))
        for bad in ("2026-9-11", "11-09-2026", "", None, 20260911, "2026/09/11"):
            self.assertFalse(validate_date(bad), bad)

    def test_clean_text_strips_control_characters(self):
        self.assertEqual(clean_text("Dep\x00arted\x1b[31m"), "Departed[31m")
        self.assertEqual(clean_text(None), "")
        self.assertEqual(clean_text(""), "")

    def test_normalize_flight_number(self):
        self.assertEqual(normalize_flight_number("CX 759"), "CX759")
        self.assertEqual(normalize_flight_number("  cx759 "), "CX759")
        self.assertEqual(normalize_flight_number(None), "")

    def test_make_flight_key(self):
        self.assertEqual(
            make_flight_key("2026-09-11", "cx 759", "departure"), "2026-09-11_DEP_CX759")
        self.assertEqual(
            make_flight_key("2026-09-11", "cx 759", "arrival"), "2026-09-11_ARR_CX759")

    def test_flight_key_separates_the_two_directions(self):
        # One number can arrive and depart on the same day; they are two flights.
        self.assertNotEqual(
            make_flight_key("2026-09-11", "UA820", "arrival"),
            make_flight_key("2026-09-11", "UA820", "departure"))

    def test_route_text(self):
        self.assertEqual(route_text({"type": "departure", "destination": "NRT"}), "HKG -> NRT")
        self.assertEqual(route_text({"type": "arrival", "origin": "SYD"}), "SYD -> HKG")
        self.assertEqual(route_text({"type": "arrival", "origin": "SIN|LHR"}), "SIN/LHR -> HKG")

    def test_gate_stand_text(self):
        self.assertEqual(gate_stand_text({"type": "departure", "gate": "63"}), "Gate 63")
        self.assertEqual(gate_stand_text({"type": "departure"}), "--")
        self.assertEqual(gate_stand_text({"type": "arrival", "stand": "W63"}), "Stand W63")
        self.assertEqual(gate_stand_text({"type": "arrival"}), "--")

    def test_status_category(self):
        cases = {
            "Scheduled": "scheduled", "Boarding": "boarding", "Boarding Soon": "boarding_soon",
            "Final Call": "final_call", "Gate Closed": "gate_closed",
            "Departed 08:54": "departed", "Landed 06:52": "landed",
            "At gate 01:06 (11/09/2026)": "at_gate", "Est at 12:51": "estimated",
            "Cancelled": "cancelled", "Delayed": "delayed", "": "unknown", None: "unknown",
        }
        for raw, expected in cases.items():
            self.assertEqual(status_category(raw), expected, raw)


class TestBoardDates(unittest.TestCase):
    """The window rule: which service dates the board covers, and when.

    The clock is injected everywhere, so these assertions hold at any hour the
    suite happens to run.
    """

    @staticmethod
    def at(hour, minute=0, day=11):
        return datetime(2026, 9, day, hour, minute, tzinfo=HKT)

    def test_one_date_in_the_middle_of_the_day(self):
        for hour in (2, 12, 21):
            self.assertEqual(board_dates(self.at(hour)), ["2026-09-11"], hour)

    def test_the_late_band_carries_tomorrow(self):
        # At 23:30 the next flights to leave are tomorrow's.
        self.assertEqual(board_dates(self.at(22)), ["2026-09-11", "2026-09-12"])
        self.assertEqual(board_dates(self.at(23, 59)), ["2026-09-11", "2026-09-12"])

    def test_the_early_band_carries_yesterday(self):
        # At 01:30 the flights that just left are yesterday's.
        self.assertEqual(board_dates(self.at(0, 0, day=12)), ["2026-09-11", "2026-09-12"])
        self.assertEqual(board_dates(self.at(1, 59, day=12)), ["2026-09-11", "2026-09-12"])

    def test_the_band_edges_are_exact(self):
        # 21:59 is still a one-date board; 02:00 has already dropped yesterday.
        self.assertEqual(board_dates(self.at(21, 59)), ["2026-09-11"])
        self.assertEqual(board_dates(self.at(2, 0, day=12)), ["2026-09-12"])

    def test_the_window_always_contains_today_and_is_ordered(self):
        for hour in range(24):
            dates = board_dates(self.at(hour, 30))
            self.assertIn("2026-09-11", dates, hour)
            self.assertEqual(dates, sorted(dates), hour)
            self.assertLessEqual(len(dates), 2, hour)

    def test_the_window_never_reaches_further_than_one_day(self):
        for hour in range(24):
            for date_str in board_dates(self.at(hour, 30)):
                self.assertIn(date_str, ("2026-09-10", "2026-09-11", "2026-09-12"), hour)

    def test_defaults_to_the_real_clock(self):
        self.assertIn(today_str(), board_dates())


# ------------------------------------------------------------------- cache

class TestCacheSystem(TempCacheCase):
    def test_creates_directory(self):
        self.assertTrue(os.path.isdir(self.tmp))

    def test_flight_path_rejects_bad_dates(self):
        self.assertIsNone(self.cache.flight_path("nope"))
        self.assertTrue(self.cache.flight_path("2026-09-11").endswith("flights_2026-09-11.json"))

    def test_read_write_flights(self):
        data = [{"a": 1}]
        self.cache.write_flights(TODAY, data)
        self.assertEqual(self.cache.read_flights(TODAY), data)

    def test_missing_flight_file_is_a_miss(self):
        self.assertIsNone(self.cache.read_flights("2026-01-01"))

    def test_clear_flights(self):
        self.cache.write_flights(TODAY, [{"a": 1}])
        self.cache.clear_flights(TODAY)
        self.assertIsNone(self.cache.read_flights(TODAY))
        self.cache.clear_flights(TODAY)  # idempotent

    def test_corrupt_file_is_a_miss_not_a_crash(self):
        self.cache.write_flights(TODAY, [{"a": 1}])
        with open(self.cache.flight_path(TODAY), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertIsNone(self.cache.read_flights(TODAY))

    def test_flight_mtime(self):
        self.cache.write_flights(TODAY, [])
        self.assertIsInstance(self.cache.flight_mtime(TODAY), float)
        self.assertIsNone(self.cache.flight_mtime("2026-01-01"))

    def test_airlines_roundtrip(self):
        self.cache.write_airlines([{"code": "CX"}])
        self.assertEqual(self.cache.read_airlines(), [{"code": "CX"}])

    def test_alerts_roundtrip(self):
        self.cache.write_alerts([{"key": "k", "new_value": "63"}])
        self.assertEqual(self.cache.read_alerts(), [{"key": "k", "new_value": "63"}])

    def test_alerts_read_survives_garbage(self):
        with open(self.cache.alerts_path, "w", encoding="utf-8") as fh:
            fh.write("[1, 2, 3]")
        self.assertEqual(self.cache.read_alerts(), [])

    def test_alerts_read_accepts_the_legacy_shape(self):
        with open(self.cache.alerts_path, "w", encoding="utf-8") as fh:
            fh.write('{"active": [{"key": "k"}], "history": [{"key": "h"}]}')
        self.assertEqual(self.cache.read_alerts(), [{"key": "k"}])

    def test_cache_age_minutes(self):
        self.cache.write_airlines([])
        self.assertGreaterEqual(self.cache.cache_age_minutes(self.cache.airlines_path), 0)
        self.assertEqual(self.cache.cache_age_minutes(os.path.join(self.tmp, "nope")), -1)


# ------------------------------------------------------------ normalization

class TestNormalizeFlights(unittest.TestCase):
    def test_basic_record(self):
        rec = normalize_flights([payload("CX 759", gate="63")])[0]
        self.assertEqual(rec["flight_number"], "CX759")
        self.assertEqual(rec["airline_code"], "CX")
        self.assertEqual(rec["gate"], "63")
        self.assertEqual(rec["type"], "departure")
        self.assertEqual(rec["key"], f"{TODAY}_DEP_CX759")
        self.assertEqual(rec["status_category"], "scheduled")

    def test_cargo_is_skipped(self):
        self.assertEqual(normalize_flights([payload("CX759", cargo=True)]), [])

    def test_arrival_direction_and_route(self):
        rec = normalize_flights([payload("CX 100", arrival=True, stand="W63",
                                         origin=["SYD"])])[0]
        self.assertEqual(rec["type"], "arrival")
        self.assertEqual(rec["stand"], "W63")
        self.assertEqual(rec["origin"], "SYD")
        self.assertEqual(rec["destination"], "")

    def test_codeshares_are_preserved(self):
        entry = payload("CX 759")
        entry["list"][0]["flight"].append({"airline": "QR", "no": "8159"})
        rec = normalize_flights([entry])[0]
        self.assertEqual(rec["flight_number"], "CX759")
        self.assertIn("QR8159", rec["all_flight_numbers"])

    def test_numeric_only_flight_number_gets_the_airline_prefix(self):
        rec = normalize_flights([payload("759", airline="CX")])[0]
        self.assertEqual(rec["flight_number"], "CX759")

    def test_full_flight_number_is_left_alone(self):
        rec = normalize_flights([payload("K4 701", airline="CKS")])[0]
        self.assertEqual(rec["flight_number"], "K4701")

    def test_null_fields_become_empty_strings(self):
        rec = normalize_flights([payload("CX759")])[0]
        for field in ("gate", "stand", "aisle", "hall", "belt"):
            self.assertEqual(rec[field], "")

    def test_control_characters_are_stripped(self):
        rec = normalize_flights([payload("CX759", status="Dep\x00arted")])[0]
        self.assertEqual(rec["status"], "Departed")

    def test_malformed_payloads(self):
        self.assertEqual(normalize_flights(None), [])
        self.assertEqual(normalize_flights("nope"), [])
        self.assertEqual(normalize_flights([None, 1, {"list": None}]), [])
        self.assertEqual(normalize_flights([{"list": [{"flight": []}]}]), [])

    def test_sort_flights_orders_by_date_time_number(self):
        recs = [
            {"date": "2026-09-11", "time": "10:00", "flight_number": "CX2"},
            {"date": "2026-09-11", "time": "08:00", "flight_number": "CX3"},
            {"date": "2026-09-10", "time": "23:00", "flight_number": "CX1"},
        ]
        ordered = sort_flights(recs)
        self.assertEqual([r["flight_number"] for r in ordered], ["CX1", "CX3", "CX2"])


# ------------------------------------------------------------------ alerts

class TestAlertManager(TempCacheCase):
    def setUp(self):
        super().setUp()
        self.alerts = AlertManager(cache=self.cache)

    @staticmethod
    def flight(gate="62", stand="", status="Scheduled", day=None):
        date_str = day or TODAY
        return {"key": f"{date_str}_DEP_CX759", "flight_number": "CX759", "date": date_str,
                "time": "08:40", "type": "departure", "gate": gate, "stand": stand,
                "status": status}

    def test_starts_empty(self):
        self.assertEqual(self.alerts.active_count(), 0)
        self.assertEqual(self.alerts.get_active(), [])
        self.assertEqual(self.alerts.snapshot(), {"revision": 0, "alerts": []})

    def test_gate_change_raises_an_alert(self):
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate="63"))
        active = self.alerts.get_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["field"], "GATE")
        self.assertEqual(active[0]["old_value"], "62")
        self.assertEqual(active[0]["new_value"], "63")

    def test_stand_change_raises_an_alert(self):
        self.alerts.process_flight(self.flight(stand="W62"), self.flight(stand="W63"))
        self.assertEqual(self.alerts.get_active()[0]["field"], "STAND")

    def test_no_change_raises_nothing(self):
        same = self.flight(gate="62")
        self.alerts.process_flight(same, dict(same))
        self.assertEqual(self.alerts.active_count(), 0)

    def test_repeated_change_updates_rather_than_duplicates(self):
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate="63"))
        self.alerts.process_flight(self.flight(gate="63"), self.flight(gate="64"))
        active = self.alerts.get_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["new_value"], "64")

    def test_first_allocation_raises_nothing(self):
        self.alerts.process_flight(self.flight(gate=""), self.flight(gate="62"))
        self.assertEqual(self.alerts.active_count(), 0)

    def test_release_raises_an_alert(self):
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate=""))
        active = self.alerts.get_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["old_value"], "62")
        self.assertEqual(active[0]["new_value"], "")

    def test_reallocation_reports_the_original_baseline(self):
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate=""))
        self.alerts.process_flight(self.flight(gate=""), self.flight(gate="64"))
        active = self.alerts.get_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["old_value"], "62")
        self.assertEqual(active[0]["new_value"], "64")

    def test_returning_to_the_baseline_clears_the_alert(self):
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate="63"))
        self.alerts.process_flight(self.flight(gate="63"), self.flight(gate="62"))
        self.assertEqual(self.alerts.active_count(), 0)

    def test_cleared_when_flight_departs(self):
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate="63"))
        self.assertEqual(self.alerts.active_count(), 1)
        self.alerts.process_flight(self.flight(gate="63"), self.flight(gate="63", status="Departed 09:10"))
        self.assertEqual(self.alerts.active_count(), 0)

    def test_revision_advances_on_change(self):
        before = self.alerts.alerts_revision()
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate="63"))
        self.assertGreater(self.alerts.alerts_revision(), before)

    def test_reads_return_copies(self):
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate="63"))
        snapshot = self.alerts.snapshot()
        snapshot["alerts"][0]["new_value"] = "TAMPERED"
        self.assertNotEqual(self.alerts.get_active()[0]["new_value"], "TAMPERED")

    def test_alert_list_is_bounded(self):
        for i in range(600):
            old = self.flight(gate="1")
            new = self.flight(gate="2")
            old["key"] = new["key"] = f"{TODAY}_DEP_CX{i}"
            self.alerts.process_flight(old, new)
        self.assertLessEqual(self.alerts.active_count(), 500)

    def test_retain_dates_drops_other_days(self):
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate="63"))
        self.alerts.retain_dates(["2020-01-01"])
        self.assertEqual(self.alerts.active_count(), 0)

    def test_retain_dates_keeps_every_date_in_the_window(self):
        # A board that spans midnight carries two service dates; dropping
        # either one would delete alerts for flights still on screen.
        yesterday = "2020-01-01"
        for day in (yesterday, TODAY):
            self.alerts.process_flight(self.flight(gate="62", day=day),
                                       self.flight(gate="63", day=day))
        self.alerts.retain_dates([yesterday, TODAY])
        self.assertEqual(self.alerts.active_count(), 2)

    def test_retain_dates_keeps_the_baseline_of_a_surviving_alert(self):
        # The baseline is what makes a *later* change visible. Pruning it while
        # keeping the alert would make the flight look freshly allocated and
        # swallow its next move - the alert would report the wrong original.
        yesterday = "2020-01-01"
        self.alerts.process_flight(self.flight(gate="62", day=yesterday),
                                   self.flight(gate="63", day=yesterday))
        self.alerts.retain_dates([yesterday])
        self.alerts.process_flight(self.flight(gate="63", day=yesterday),
                                   self.flight(gate="64", day=yesterday))
        active = self.alerts.get_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["old_value"], "62")
        self.assertEqual(active[0]["new_value"], "64")

    def test_retain_dates_with_nothing_to_keep_is_a_no_op(self):
        # An empty window means "no information", not "drop everything".
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate="63"))
        self.alerts.retain_dates([])
        self.alerts.retain_dates([""])
        self.assertEqual(self.alerts.active_count(), 1)

    def test_alerts_persist_across_instances(self):
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate="63"))
        reopened = AlertManager(cache=self.cache)
        self.assertEqual(reopened.active_count(), 1)

    def test_none_inputs_are_ignored(self):
        self.alerts.process_flight(None, self.flight())
        self.alerts.process_flight(self.flight(), None)
        self.assertEqual(self.alerts.active_count(), 0)


# --------------------------------------------------------------- API client

class TestAPIClient(TempCacheCase):
    def test_invalid_date_is_rejected_before_any_request(self):
        api = APIClient(cache=self.cache)
        api._get_json = lambda url: self.fail("must not issue a request")
        self.assertIsNone(api.fetch_flights("11-09-2026"))

    def test_rate_limit_spaces_calls(self):
        api = APIClient(min_interval=0.2)
        api._get_json = lambda url: []
        start = time.time()
        api.fetch_flights(TODAY)
        api.fetch_flights(TODAY)
        self.assertGreaterEqual(time.time() - start, 0.18)

    def test_successful_fetch_writes_through_to_cache(self):
        api = APIClient(cache=self.cache, min_interval=0)
        api._get_json = lambda url: [{"ok": True}]
        self.assertEqual(api.fetch_flights(TODAY), [{"ok": True}])
        self.assertEqual(self.cache.read_flights(TODAY), [{"ok": True}])

    def test_airlines_meta_reports_api_then_cache(self):
        api = APIClient(cache=self.cache, min_interval=0)
        api._get_json = lambda url: [{"code": "CX"}]
        self.assertEqual(api.fetch_airlines_meta()["source"], "api")

        second = APIClient(cache=self.cache, min_interval=0)
        second._get_json = lambda url: self.fail("should have used the cache")
        meta = second.fetch_airlines_meta()
        self.assertEqual(meta["source"], "cache")
        self.assertEqual(meta["airlines"], [{"code": "CX"}])

    def test_airlines_falls_back_to_cache_after_failure(self):
        self.cache.write_airlines([{"code": "CX"}])
        # Expire the airline cache so the API is actually attempted.
        api = APIClient(cache=self.cache, min_interval=0, airlines_cache_hours=0)
        api._get_json = lambda url: None
        meta = api.fetch_airlines_meta()
        self.assertEqual(meta["source"], "cache")
        self.assertEqual(meta["error"], "api_failed")

    def test_airlines_reports_none_when_everything_fails(self):
        api = APIClient(cache=self.cache, min_interval=0)
        api._get_json = lambda url: None
        meta = api.fetch_airlines_meta()
        self.assertEqual(meta["source"], "none")
        self.assertFalse(meta["ok"])

    def test_bypass_cache_skips_the_airline_cache(self):
        self.cache.write_airlines([{"code": "OLD"}])
        api = APIClient(cache=self.cache, min_interval=0, bypass_cache=True)
        api._get_json = lambda url: [{"code": "NEW"}]
        self.assertEqual(api.fetch_airlines_meta()["airlines"], [{"code": "NEW"}])

    def test_bypass_cache_does_not_fall_back_on_failure(self):
        self.cache.write_airlines([{"code": "OLD"}])
        api = APIClient(cache=self.cache, min_interval=0, bypass_cache=True)
        api._get_json = lambda url: None
        self.assertEqual(api.fetch_airlines_meta()["airlines"], [])

    def test_fetch_airlines_returns_a_plain_list(self):
        api = APIClient(cache=self.cache, min_interval=0)
        api._get_json = lambda url: [{"code": "CX"}]
        self.assertEqual(api.fetch_airlines(), [{"code": "CX"}])


# ------------------------------------------------------------------ poller

class TestPoller(TempCacheCase):
    def make(self, data=None, fail=False, clock=None, **kw):
        api = FakeAPI(data, fail, cache=self.cache)
        return Poller(cache=self.cache, api=api, alert_manager=AlertManager(self.cache),
                      clock=clock or (lambda: clock_at(12)), **kw), api

    def test_first_refresh_publishes_a_snapshot(self):
        poller, _ = self.make([payload("CX 759", gate="63")])
        records = poller.refresh_now()
        self.assertEqual(len(records), 1)
        snap = poller.snapshot()
        self.assertEqual(snap["source"], "api")
        self.assertEqual(snap["records_date"], TODAY)
        self.assertEqual(snap["records_dates"], [TODAY])
        self.assertEqual(snap["revision"], 1)
        self.assertIsNone(snap["last_error"])
        self.assertFalse(snap["refreshing"])

    def test_snapshot_contains_the_expected_keys(self):
        poller, _ = self.make([payload("CX759")])
        poller.refresh_now()
        self.assertEqual(set(poller.snapshot()), {
            "revision", "records_date", "records_dates", "records", "source",
            "last_attempt_at", "last_api_success_at", "cache_saved_at", "last_error",
            "polling_enabled", "refreshing",
        })

    def test_a_midday_board_fetches_one_date(self):
        poller, api = self.make([payload("CX759")])
        poller.refresh_now()
        self.assertEqual(api.dates, [TODAY])
        self.assertEqual(poller.snapshot()["records_dates"], [TODAY])

    def test_a_late_board_fetches_today_and_tomorrow(self):
        tomorrow = shift_day(TODAY, 1)
        poller, api = self.make(
            {TODAY: [payload("CX759", date_str=TODAY)],
             tomorrow: [payload("UO612", date_str=tomorrow)]},
            clock=lambda: clock_at(23, 30))
        poller.refresh_now()
        snap = poller.snapshot()
        self.assertEqual(api.dates, [TODAY, tomorrow])
        self.assertEqual(snap["records_dates"], [TODAY, tomorrow])
        # The board's own date stays today: the window is what is covered, not
        # what the board is centred on.
        self.assertEqual(snap["records_date"], TODAY)
        self.assertEqual(sorted(r["date"] for r in snap["records"]), [TODAY, tomorrow])

    def test_an_early_board_fetches_yesterday_and_today(self):
        yesterday = shift_day(TODAY, -1)
        poller, api = self.make(
            {yesterday: [payload("CX759", date_str=yesterday)],
             TODAY: [payload("UO612", date_str=TODAY)]},
            clock=lambda: clock_at(1, 0))
        poller.refresh_now()
        snap = poller.snapshot()
        self.assertEqual(api.dates, [yesterday, TODAY])
        self.assertEqual(snap["records_dates"], [yesterday, TODAY])
        self.assertEqual(snap["records_date"], TODAY)
        self.assertEqual(sorted(r["date"] for r in snap["records"]), [yesterday, TODAY])

    def test_a_date_leaves_the_board_when_the_window_moves_on(self):
        tomorrow = shift_day(TODAY, 1)
        clock = {"now": clock_at(23, 30)}
        poller, _ = self.make(
            {TODAY: [payload("CX759", date_str=TODAY)],
             tomorrow: [payload("UO612", date_str=tomorrow)]},
            clock=lambda: clock["now"])
        poller.refresh_now()
        self.assertEqual(len(poller.snapshot()["records"]), 2)

        # 09:00 the next morning: only the new "today" is still current, and the
        # day that dropped out of the window must leave the board with it.
        clock["now"] = clock_at(9, day=tomorrow)
        poller.refresh_now()
        snap = poller.snapshot()
        self.assertEqual(snap["records_dates"], [tomorrow])
        self.assertEqual([r["date"] for r in snap["records"]], [tomorrow])

    def test_a_partly_cached_window_is_not_reported_as_live(self):
        tomorrow = shift_day(TODAY, 1)
        poller, api = self.make({TODAY: [payload("CX759", date_str=TODAY)]},
                                clock=lambda: clock_at(23, 30))
        poller.refresh_now()
        self.assertEqual(poller.snapshot()["source"], "api")

        # Tomorrow is on disk from an earlier run and the API can no longer
        # serve it: the board is half remembered, so it must not say "api".
        self.cache.write_flights(tomorrow, [payload("UO612", date_str=tomorrow)])
        api.data = {TODAY: [payload("CX759", date_str=TODAY)], tomorrow: None}
        poller.refresh_now()
        snap = poller.snapshot()
        self.assertEqual(snap["source"], "cache")
        self.assertEqual(snap["records_dates"], [TODAY, tomorrow])
        self.assertEqual(sorted(r["date"] for r in snap["records"]), [TODAY, tomorrow])

    def test_one_date_failing_still_leaves_the_other_on_the_board(self):
        tomorrow = shift_day(TODAY, 1)
        poller, api = self.make({TODAY: [payload("CX759", date_str=TODAY)]},
                                clock=lambda: clock_at(23, 30))

        class OneDateDown(FakeAPI):
            def fetch_flights(self, date_str):
                if date_str == tomorrow:
                    raise RuntimeError("only tomorrow is down")
                return super().fetch_flights(date_str)

        poller.api = OneDateDown({TODAY: [payload("CX759", date_str=TODAY)]},
                                 cache=self.cache)
        poller.refresh_now()
        snap = poller.snapshot()
        self.assertEqual(snap["records_dates"], [TODAY, tomorrow])
        self.assertEqual([r["date"] for r in snap["records"]], [TODAY])
        self.assertIsNotNone(snap["last_error"])

    def test_alerts_from_both_days_survive_a_refresh(self):
        yesterday = shift_day(TODAY, -1)
        poller, api = self.make(
            {yesterday: [payload("CX759", gate="62", date_str=yesterday)],
             TODAY: [payload("UO612", gate="62", date_str=TODAY)]},
            clock=lambda: clock_at(1, 0))
        poller.refresh_now()
        api.data = {
            yesterday: [payload("CX759", gate="63", date_str=yesterday)],
            TODAY: [payload("UO612", gate="63", date_str=TODAY)],
        }
        poller.refresh_now()
        active = poller.alert_manager.get_active()
        self.assertEqual(sorted(a["date"] for a in active), [yesterday, TODAY])

    def test_gate_change_raises_an_alert_through_the_poller(self):
        poller, api = self.make([payload("CX 759", gate="62")])
        poller.refresh_now()
        api.data = [payload("CX 759", gate="63")]
        poller.refresh_now()
        active = poller.alert_manager.get_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["new_value"], "63")

    def test_an_arrival_landing_does_not_clear_its_departure(self):
        # UA820 arrives from LAX and departs for BKK on the same day. The two
        # share a number; only the direction tells them apart, so the arrival
        # landing must not sweep away the departure's gate alert.
        poller, api = self.make([
            payload("UA 820", gate="62", destination=["BKK"]),
            payload("UA 820", arrival=True, stand="W63", origin=["LAX"]),
        ])
        poller.refresh_now()

        api.data = [
            payload("UA 820", gate="63", destination=["BKK"]),
            payload("UA 820", arrival=True, stand="W63", origin=["LAX"],
                    status="Landed"),
        ]
        poller.refresh_now()

        active = poller.alert_manager.get_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["type"], "departure")
        self.assertEqual(active[0]["new_value"], "63")

    def test_failed_api_falls_back_to_cache(self):
        poller, api = self.make([payload("CX 759", gate="62")])
        poller.refresh_now()
        api.fail = True
        poller.refresh_now()
        snap = poller.snapshot()
        self.assertEqual(snap["source"], "cache")
        self.assertEqual(len(snap["records"]), 1)
        self.assertIsNotNone(snap["cache_saved_at"])
        self.assertIsNotNone(snap["last_error"])

    def test_failed_api_without_cache_keeps_memory_data(self):
        poller, api = self.make([payload("CX 759")])
        poller.refresh_now()
        self.cache.clear_flights(TODAY)
        api.fail = True
        poller.refresh_now()
        snap = poller.snapshot()
        self.assertEqual(snap["source"], "memory")
        self.assertEqual(len(snap["records"]), 1)

    def test_no_data_at_all_reports_none(self):
        poller, _ = self.make(None, fail=True)
        poller.refresh_now()
        snap = poller.snapshot()
        self.assertEqual(snap["source"], "none")
        self.assertEqual(snap["records"], [])
        self.assertIsNotNone(snap["last_error"])

    def test_failed_refresh_still_advances_the_revision(self):
        poller, api = self.make([payload("CX759")])
        poller.refresh_now()
        before = poller.revision()
        api.fail = True
        poller.refresh_now()
        self.assertGreater(poller.revision(), before)

    def test_request_refresh_coalesces(self):
        poller, _ = self.make([payload("CX759")])
        self.assertEqual(poller.request_refresh(), "accepted")
        self.assertEqual(poller.request_refresh(), "already_running")

    def test_stop_is_idempotent_and_rejects_new_work(self):
        poller, _ = self.make([payload("CX759")], enabled=False)
        poller.start()
        self.assertTrue(poller.stop())
        self.assertTrue(poller.stop())
        self.assertEqual(poller.request_refresh(), "closed")

    def test_records_are_isolated_between_reads(self):
        poller, _ = self.make([payload("CX759")])
        poller.refresh_now()
        self.assertIsNot(poller.board_records, poller.board_records)
        self.assertIsNot(poller.snapshot()["records"], poller.snapshot()["records"])

    def test_background_start_refreshes_once(self):
        poller, api = self.make([payload("CX759")], enabled=False)
        try:
            poller.start()
            deadline = time.time() + 5
            while poller.revision() == 0 and time.time() < deadline:
                time.sleep(0.02)
            self.assertEqual(poller.revision(), 1)
            self.assertEqual(api.calls, 1)
        finally:
            poller.stop()

    def test_blocking_start_refreshes_before_returning(self):
        poller, api = self.make([payload("CX759")], enabled=False)
        try:
            poller.start(blocking=True)
            self.assertEqual(poller.revision(), 1)
            self.assertEqual(api.calls, 1)
        finally:
            poller.stop()


# --------------------------------------------------------------- web server

class TestWebServer(TempCacheCase):
    def setUp(self):
        super().setUp()
        self.api = FakeAPI([payload("CX 759", gate="63")], cache=self.cache)
        # A fixed clock: with a real one the poller covers two service dates
        # between 22:00 and 02:00 and the counts below would change with the hour.
        self.poller = Poller(cache=self.cache, api=self.api,
                             alert_manager=AlertManager(self.cache),
                             clock=lambda: clock_at(12))
        self.poller.refresh_now()
        self.server = WebServer(self.poller, self.api, self.poller.alert_manager, port=18095)

    def make_window_server(self, port=18096):
        """A server whose poller covers two service dates, plus a third on disk."""
        tomorrow = shift_day(TODAY, 1)
        older = shift_day(TODAY, -2)
        api = FakeAPI({
            TODAY: [payload("CX 759", gate="63", date_str=TODAY)],
            tomorrow: [payload("UO 612", gate="205", date_str=tomorrow)],
            older: [payload("HX 100", gate="41", date_str=older)],
        }, cache=self.cache)
        poller = Poller(cache=self.cache, api=api,
                        alert_manager=AlertManager(self.cache),
                        clock=lambda: clock_at(23, 30))
        poller.refresh_now()
        return WebServer(poller, api, poller.alert_manager, port=port), tomorrow, older

    def tearDown(self):
        self.server.stop()
        super().tearDown()

    def test_start_and_stop(self):
        self.assertTrue(self.server.start())
        self.assertTrue(self.server.running())
        self.server.stop()
        self.assertFalse(self.server.running())

    def test_api_flights_rejects_a_bad_date(self):
        with self.assertRaises(ValueError):
            self.server.api_flights({"date": ["not-a-date"]})

    def test_api_flights_returns_today_from_the_poller(self):
        records = self.server.api_flights({})
        self.assertEqual(len(records), 1)

    def test_api_flights_filters_by_type(self):
        self.assertEqual(self.server.api_flights({"type": ["arrival"]}), [])

    def test_api_search_matches_flight_number(self):
        self.assertEqual(len(self.server.api_search({"flight": ["CX759"]})), 1)
        self.assertEqual(self.server.api_search({"flight": ["ZZ999"]}), [])
        self.assertEqual(self.server.api_search({"flight": [""]}), [])

    def test_api_search_rejects_a_bad_date(self):
        with self.assertRaises(ValueError):
            self.server.api_search({"flight": ["CX759"], "date": ["bad"]})

    def test_stats_and_alerts_endpoints(self):
        self.assertEqual(self.server.get_stats()["alerts"], 0)
        self.assertEqual(self.server.api_alerts(), [])

    def test_web_ui_is_served(self):
        html = self.server.web_ui()
        self.assertIn("<table>", html)
        self.assertIn("HKG Flight Data", html)

    def test_stats_report_the_board_clock_in_hong_kong(self):
        # The clock is sent from the server because a viewer's browser may be
        # in any time zone, and the board is Hong Kong's.
        expected = now_hkt()
        stats = self.server.get_stats()
        self.assertEqual(stats["hkt_now"],
                         "{:02d}:{:02d}".format(*divmod(stats["hkt_minutes"], 60)))
        self.assertLessEqual(
            abs(stats["hkt_minutes"] - (expected.hour * 60 + expected.minute)), 1)
        self.assertTrue(stats["time"].endswith("+08:00"), stats["time"])

    def test_every_element_the_dashboard_script_wires_actually_exists(self):
        # A renamed id leaves the dashboard dead with no error on the server
        # side; this is the cheapest way to notice.
        html = self.server.web_ui()
        wired = set(re.findall(r'\$\("([^"]+)"\)', html))
        self.assertTrue(wired)
        for element_id in sorted(wired):
            self.assertIn('id="%s"' % element_id, html, element_id)

    def test_the_dashboard_does_not_cap_the_rows_it_renders(self):
        # The table used to render the first 400 rows while the tab counted
        # them all, so a full day looked truncated and the two disagreed.
        self.assertNotIn("rows.slice(", self.server.web_ui())

    def test_api_flights_without_a_date_returns_the_whole_window(self):
        server, tomorrow, _ = self.make_window_server()
        try:
            records = server.api_flights({})
            self.assertEqual(sorted(r["date"] for r in records), [TODAY, tomorrow])
        finally:
            server.stop()

    def test_the_window_arrives_sorted_by_date_then_time(self):
        # The dashboard's anchor scans the rows in the order they arrive, so
        # unsorted rows would park the viewport on the wrong day.
        server, _, _ = self.make_window_server()
        try:
            keys = [(r["date"], r["time"]) for r in server.api_flights({})]
            self.assertEqual(keys, sorted(keys))
        finally:
            server.stop()

    def test_an_explicit_date_inside_the_window_is_served_from_it(self):
        server, tomorrow, _ = self.make_window_server()
        try:
            records = server.api_flights({"date": [tomorrow]})
            self.assertEqual([r["date"] for r in records], [tomorrow])
        finally:
            server.stop()

    def test_an_explicit_date_outside_the_window_is_fetched_live(self):
        server, tomorrow, older = self.make_window_server()
        try:
            records = server.api_flights({"date": [older]})
            self.assertEqual([r["date"] for r in records], [older])
            # Serving it live must not quietly change what the board covers.
            self.assertEqual(server.poller.snapshot()["records_dates"], [TODAY, tomorrow])
        finally:
            server.stop()

    def test_stats_report_the_window_and_the_boards_own_date(self):
        server, tomorrow, _ = self.make_window_server()
        try:
            stats = server.get_stats()
            self.assertEqual(stats["dates"], [TODAY, tomorrow])
            self.assertEqual(stats["date"], TODAY)
            self.assertEqual(stats["hkt_date"], now_hkt().date().isoformat())
        finally:
            server.stop()


# --------------------------------------------------------------------- CLI

class TestCLISearch(unittest.TestCase):
    @staticmethod
    def api(records):
        """A stand-in that always returns ``records`` for any date."""
        class _API:
            def fetch_flights(self, date_str):
                return records
        return _API()

    def test_search_by_flight_number(self):
        api = self.api([payload("CX 759", gate="63")])
        results = cli.search_flights(api, "CX759", TODAY)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["flight_number"], "CX759")

    def test_search_by_airline_code(self):
        api = self.api([payload("CX 759"), payload("UO 612", airline="HKE")])
        results = cli.search_flights(api, "CX", TODAY)
        self.assertEqual([r["flight_number"] for r in results], ["CX759"])

    def test_search_by_gate(self):
        api = self.api([payload("CX 759", gate="63"), payload("UO 612", gate="205")])
        self.assertEqual(len(cli.search_flights(api, "G63", TODAY)), 1)

    def test_search_by_stand(self):
        api = self.api([payload("CX 100", stand="W63", arrival=True)])
        self.assertEqual(len(cli.search_flights(api, "W63", TODAY)), 1)

    def test_short_flight_number_is_not_a_stand(self):
        self.assertFalse(cli._is_stand("BA15"))
        self.assertFalse(cli._is_stand("SQ2"))
        self.assertTrue(cli._is_stand("W63"))
        self.assertTrue(cli._is_gate("G28"))
        self.assertTrue(cli._is_airline_code("CX"))

    def test_stand_query_without_a_match_falls_back_to_flight_number(self):
        api = self.api([payload("D7 123", airline="D7")])
        results = cli.search_flights(api, "D7", TODAY)
        self.assertEqual(len(results), 1)

    def test_codeshare_search_is_opt_in(self):
        entry = payload("CX 759")
        entry["list"][0]["flight"].append({"airline": "QR", "no": "8159"})
        api = self.api([entry])
        self.assertEqual(cli.search_flights(api, "QR8159", TODAY), [])
        self.assertEqual(len(cli.search_flights(api, "QR8159", TODAY, include_codeshare=True)), 1)

    def test_no_match_returns_empty(self):
        api = self.api([payload("CX759")])
        self.assertEqual(cli.search_flights(api, "ZZ999", TODAY), [])

    def test_one_number_arriving_and_departing_is_not_deduplicated(self):
        # Real HKIA turnaround flights: UA820 lands from LAX and leaves for BKK
        # on the same day. They share a number but are two flights.
        api = self.api([
            payload("UA 820", arrival=True, stand="W63", origin=["LAX"]),
            payload("UA 820", gate="63", destination=["BKK"]),
        ])
        results = cli.search_flights(api, "UA820", TODAY)
        self.assertEqual([r["type"] for r in results], ["arrival", "departure"])

    def test_flights_for_date_filters_direction(self):
        api = self.api([payload("CX 759"), payload("CX 100", arrival=True)])
        self.assertEqual(len(cli.flights_for_date(api, TODAY, "departure")), 1)
        self.assertEqual(len(cli.flights_for_date(api, TODAY, "arrival")), 1)
        self.assertEqual(len(cli.flights_for_date(api, TODAY)), 2)

    def test_flights_for_date_handles_api_failure(self):
        self.assertEqual(cli.flights_for_date(FakeAPI(None), TODAY), [])

    def test_search_dates_respects_an_explicit_date(self):
        self.assertEqual(cli._search_dates("2026-09-11"), ["2026-09-11"])

    def test_search_dates_covers_today_by_default(self):
        noon = datetime(2026, 9, 11, 12, 0, tzinfo=HKT)
        self.assertEqual(cli._search_dates(None, noon), ["2026-09-11"])

    def test_search_dates_spans_midnight(self):
        # A query at 23:30 must still find the 00:05 departure tomorrow.
        late = datetime(2026, 9, 11, 23, 30, tzinfo=HKT)
        self.assertEqual(cli._search_dates(None, late), ["2026-09-11", "2026-09-12"])
        early = datetime(2026, 9, 12, 1, 0, tzinfo=HKT)
        self.assertEqual(cli._search_dates(None, early), ["2026-09-11", "2026-09-12"])

    def test_search_dates_is_the_board_rule_not_a_copy_of_it(self):
        # A search and the board it searches must never disagree about which
        # days are "now": one rule, one owner.
        for hour in range(24):
            when = datetime(2026, 9, 11, hour, 30, tzinfo=HKT)
            self.assertEqual(cli._search_dates(None, when), board_dates(when), hour)


class TestCLIRendering(TempCacheCase):
    @staticmethod
    def _table_output(records, title="Test", columns=DEFAULT_WIDTH):
        """Capture table output with the terminal width pinned.

        ``COLUMNS`` is set explicitly so the assertions do not depend on the
        window the suite happens to run in.
        """
        import contextlib
        import io
        from unittest import mock

        buf = io.StringIO()
        env = {"COLUMNS": str(columns)}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(buf):
            cli.print_flight_table(records, title)
        return buf.getvalue()

    def test_table_output_is_one_row_per_flight(self):
        records = normalize_flights([payload("CX 759", gate="63"), payload("UO 612")])
        lines = [ln for ln in self._table_output(records).splitlines() if ln.strip()]
        data_rows = [ln for ln in lines if "CX759" in ln or "UO612" in ln]
        self.assertEqual(len(data_rows), 2)

    def test_table_divides_the_days_when_the_set_spans_more_than_one(self):
        # `query` looks at two dates across midnight; without a divider the same
        # scheduled time on consecutive days reads as a duplicated row.
        records = normalize_flights([
            payload("CX 759", gate="63", date_str="2026-09-11"),
            payload("CX 759", gate="64", date_str="2026-09-12"),
        ])
        out = self._table_output(records)
        self.assertIn("-- 2026-09-11 ", out)
        self.assertIn("-- 2026-09-12 ", out)

    def test_no_date_divider_when_everything_is_one_day(self):
        records = normalize_flights([payload("CX 759", gate="63")])
        self.assertNotIn("-- ", self._table_output(records))

    def test_every_line_fits_the_terminal_at_any_width(self):
        """A line wider than the terminal is what wraps ``G30`` into ``G`` + ``30``."""
        from hkg_flight.terminal import views
        records = normalize_flights([
            payload("CX 759", gate="30"),
            payload("UA 862", gate="69"),
        ])
        for columns in (120, 100, 78, 60, 45, 30, 20):
            out = self._table_output(records, columns=columns)
            for line in out.splitlines():
                self.assertLessEqual(views.text_width(line), columns, (columns, line))

    def test_a_phone_width_switches_to_the_two_line_row(self):
        records = normalize_flights([payload("CX 759", gate="30")])
        narrow = self._table_output(records, columns=45)
        wide = self._table_output(records, columns=100)
        # Compact drops the column header and spends two lines on the flight;
        # the wide form keeps the header and fits the flight on one line.
        self.assertNotIn("GATE/STAND", narrow)
        self.assertIn("GATE/STAND", wide)
        self.assertEqual(len([ln for ln in narrow.splitlines() if "CX759" in ln]), 1)
        self.assertTrue(any("G30" in ln and "CX759" not in ln for ln in narrow.splitlines()))
        self.assertTrue(any("G30" in ln and "CX759" in ln for ln in wide.splitlines()))

    def test_the_gate_is_never_split_across_lines(self):
        records = normalize_flights([payload("CX 759", gate="30")])
        out = self._table_output(records, columns=45)
        for line in out.splitlines():
            self.assertNotEqual(line.strip(), "G", line)
            self.assertNotEqual(line.strip(), "30", line)

    @staticmethod
    def _pager_run(records, **kwargs):
        """Drive the pager with stdout captured, width pinned.

        The pager prints whole flight tables. Letting them reach the console
        both floods the suite's output and ties the test to whatever code page
        the console uses - a cp1252 console cannot encode the route arrows
        (``→``) the rows carry, and the write would raise inside the pager.
        """
        import contextlib
        import io
        from unittest import mock

        buf = io.StringIO()
        env = {"COLUMNS": str(DEFAULT_WIDTH)}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(buf):
            page = cli.paginate_records(records, "Test", **kwargs)
        return page, buf.getvalue()

    def test_paginate_records_navigation(self):
        records = normalize_flights([payload(f"CX {i}", gate=str(i)) for i in range(25)])
        replies = iter(["n", "p", "2", "q"])
        page, out = self._pager_run(records, page_size=10,
                                    input_func=lambda _p="": next(replies))
        self.assertEqual(page, 2)
        self.assertIn("showing 11-20", out)

    def test_paginate_empty(self):
        page, out = self._pager_run([])
        self.assertEqual(page, 0)
        self.assertIn("No flights found.", out)

    def test_paginate_handles_eof(self):
        records = normalize_flights([payload("CX 759")])

        def raise_eof(_prompt=""):
            raise EOFError

        page, out = self._pager_run(records, input_func=raise_eof)
        self.assertEqual(page, 1)
        self.assertIn("CX759", out)

    def test_an_unencodable_route_arrow_does_not_abort_output(self):
        """cp1252 consoles cannot encode ``→``; the CLI must degrade, not raise."""
        import io
        import sys
        from unittest import mock

        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="cp1252", newline="\n")
        with mock.patch.object(sys, "stdout", stream), \
                mock.patch.object(sys, "stderr", stream):
            cli.make_output_robust()
            print("  → NRT")           # must not raise
            stream.flush()

        rendered = buffer.getvalue().decode("cp1252")
        self.assertEqual(rendered, "  ? NRT\n")
        # The replacement has to stay one cell wide, or the row would render
        # wider than the width the views were handed.
        self.assertEqual(views.text_width(rendered.rstrip("\n")),
                         views.text_width("  → NRT"))

    def test_the_arrow_is_unencodable_without_the_fix(self):
        """Negative control: the same write raises before ``make_output_robust``."""
        import io
        import sys
        from unittest import mock

        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="cp1252", newline="\n")
        with mock.patch.object(sys, "stdout", stream):
            with self.assertRaises(UnicodeEncodeError):
                print("  → NRT")

    def test_the_entry_point_hardens_output_before_printing(self):
        """``main`` must harden the streams itself, not rely on the caller."""
        import io
        import sys
        from unittest import mock

        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="cp1252", newline="\n")
        with mock.patch.object(sys, "stdout", stream), \
                mock.patch.object(sys, "stderr", stream):
            with self.assertRaises(SystemExit):     # --help exits after printing
                cli.main(["--help"])
            self.assertEqual(stream.errors, "replace")


class TestAdaptiveWidth(unittest.TestCase):
    """The CLI renders at the real terminal width so nothing ever wraps."""

    def test_columns_pins_the_width(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"COLUMNS": "45"}):
            self.assertEqual(terminal_width(), 45)

    def test_width_is_capped_so_rows_stay_readable(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"COLUMNS": "400"}):
            self.assertEqual(terminal_width(), MAX_WIDTH)

    def test_unusable_columns_falls_back_and_stays_positive(self):
        from unittest import mock
        for value in ("0", "-5", "abc", ""):
            with mock.patch.dict(os.environ, {"COLUMNS": value}):
                with mock.patch("shutil.get_terminal_size",
                                return_value=os.terminal_size((0, 0))):
                    self.assertGreaterEqual(terminal_width(), 1, value)

    def test_pager_prompt_steps_down_a_ladder(self):
        long_form = cli.pager_prompt(1, 3, 78)
        self.assertIn("Enter/N", long_form)
        medium = cli.pager_prompt(1, 3, 40)
        self.assertNotIn("Enter/N", medium)
        self.assertIn("next", medium)
        short = cli.pager_prompt(1, 3, 20)
        self.assertNotIn("next", short)
        self.assertIn("1/3", short)
        self.assertEqual(short, cli.pager_prompt(1, 3, 10))  # 10 cells: exactly fits
        self.assertEqual(cli.pager_prompt(1, 3, 9), "")

    def test_ladder_forms_contain_nothing_that_looks_like_markup(self):
        """A literal ``[n]`` is invisible to the width maths, so a form overflows.

        The CLI prints these strings raw but measures them with
        ``views.text_width``, which strips rich markup. Bracket notation
        therefore measures short and gets chosen at a width where the form does
        not actually fit.
        """
        from hkg_flight.terminal import views
        for form in cli._PAGER_FORMS + cli._CODESHARE_FORMS:
            rendered = form.format(page=1, total=3)
            self.assertEqual(views.text_width(rendered), len(rendered), rendered)

    def test_pager_prompt_never_wraps(self):
        from hkg_flight.terminal import views
        for width in (120, 78, 62, 60, 45, 30, 28, 20, 12, 10):
            prompt = cli.pager_prompt(2, 7, width)
            self.assertLessEqual(views.text_width(prompt), width, width)

    def test_codeshare_hint_never_wraps(self):
        from hkg_flight.terminal import views
        for width in (120, 78, 60, 49, 45, 30, 27, 20, 10):
            hint = views.fit(cli._CODESHARE_FORMS, width)
            self.assertLessEqual(views.text_width(hint), width, width)


class TestClearCache(TempCacheCase):
    def test_clears_only_owned_files(self):
        self.cache.write_flights(TODAY, [])
        self.cache.write_airlines([])
        self.cache.write_alerts([])
        outsider = os.path.join(self.tmp, "important.txt")
        with open(outsider, "w", encoding="utf-8") as fh:
            fh.write("keep me")

        cli.clear_cache(self.cache, confirm=True)

        self.assertIsNone(self.cache.read_flights(TODAY))
        self.assertEqual(self.cache.read_airlines(), [])
        self.assertTrue(os.path.exists(outsider), "unrelated files must survive")

    def test_clears_one_date(self):
        self.cache.write_flights(TODAY, [])
        cli.clear_cache(self.cache, date_str=TODAY)
        self.assertIsNone(self.cache.read_flights(TODAY))

    def test_confirmation_can_cancel(self):
        self.cache.write_flights(TODAY, [])
        import builtins
        original = builtins.input
        builtins.input = lambda _p="": "no"
        try:
            cli.clear_cache(self.cache, confirm=False)
        finally:
            builtins.input = original
        self.assertIsNotNone(self.cache.read_flights(TODAY))


# ------------------------------------------------------------- integration

class TestIntegration(TempCacheCase):
    def test_cache_then_retrieve(self):
        api = APIClient(cache=self.cache, min_interval=0)
        api._get_json = lambda url: [payload("CX 759", gate="63")]
        api.fetch_flights(TODAY)
        cached = self.cache.read_flights(TODAY)
        self.assertEqual(len(normalize_flights(cached)), 1)

    def test_alert_lifecycle_end_to_end(self):
        api = FakeAPI([payload("CX 759", gate="62")], cache=self.cache)
        alerts = AlertManager(self.cache)
        poller = Poller(cache=self.cache, api=api, alert_manager=alerts)
        poller.refresh_now()

        api.data = [payload("CX 759", gate="63")]
        poller.refresh_now()
        self.assertEqual(alerts.active_count(), 1)

        api.data = [payload("CX 759", gate="63", status="Departed 09:10")]
        poller.refresh_now()
        self.assertEqual(alerts.active_count(), 0)


if __name__ == "__main__":
    unittest.main()
