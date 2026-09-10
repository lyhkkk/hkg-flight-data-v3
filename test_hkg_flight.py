"""
Core regression suite for hkg_flight.

Covers the standard-library backend: utilities, cache, normalization, alerts,
the API client, the poller, the web server and the CLI. Behaviour is asserted
through public interfaces; no test reaches into poller/session internals.
"""

import os
import shutil
import tempfile
import time
import unittest
from datetime import date

from hkg_flight import cli
from hkg_flight.alerts import AlertManager
from hkg_flight.api import APIClient
from hkg_flight.cache import CacheSystem
from hkg_flight.poller import Poller
from hkg_flight.utils import (
    clean_text,
    gate_stand_text,
    make_flight_key,
    normalize_flight_number,
    normalize_flights,
    route_text,
    sort_flights,
    status_category,
    today_str,
    validate_date,
)
from hkg_flight.web import WebServer

TODAY = today_str()


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
    """Minimal APIClient stand-in: serves a fixed payload or raises."""

    def __init__(self, data=None, fail=False, cache=None):
        self.data = data
        self.fail = fail
        self.cache = cache
        self.calls = 0

    def fetch_flights(self, date_str):
        self.calls += 1
        if self.fail:
            raise RuntimeError("network down")
        if self.data is not None and self.cache is not None:
            self.cache.write_flights(date_str, self.data)
        return self.data

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
        self.assertEqual(make_flight_key("2026-09-11", "cx 759"), "2026-09-11_CX759")

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

    def test_alerts_roundtrip_normalizes_shape(self):
        self.cache.write_alerts({"active": [{"k": 1}], "history": [{"k": 2}], "extra": 9})
        self.assertEqual(self.cache.read_alerts(), {"active": [{"k": 1}], "history": [{"k": 2}]})

    def test_alerts_read_survives_garbage(self):
        with open(self.cache.alerts_path, "w", encoding="utf-8") as fh:
            fh.write("[1,2,3]")
        self.assertEqual(self.cache.read_alerts(), {"active": [], "history": []})

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
        self.assertEqual(rec["key"], f"{TODAY}_CX759")
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
    def flight(gate="62", stand="", status="Scheduled"):
        return {"key": f"{TODAY}_CX759", "flight_number": "CX759", "date": TODAY,
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

    def test_cleared_when_flight_departs(self):
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate="63"))
        self.alerts.process_flight(self.flight(gate="63"), self.flight(gate="63", status="Departed 09:10"))
        self.assertEqual(self.alerts.active_count(), 0)
        self.assertEqual(len(self.alerts.get_history()), 1)

    def test_revision_advances_on_change(self):
        before = self.alerts.alerts_revision()
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate="63"))
        self.assertGreater(self.alerts.alerts_revision(), before)

    def test_reads_return_copies(self):
        self.alerts.process_flight(self.flight(gate="62"), self.flight(gate="63"))
        snapshot = self.alerts.snapshot()
        snapshot["alerts"][0]["new_value"] = "TAMPERED"
        self.assertNotEqual(self.alerts.get_active()[0]["new_value"], "TAMPERED")

    def test_history_is_bounded(self):
        for i in range(600):
            self.alerts.process_flight(self.flight(gate="1"), self.flight(gate="2"))
            self.alerts.process_flight(self.flight(gate="2"), self.flight(gate="2", status="Departed"))
        self.assertLessEqual(len(self.alerts.get_history()), 500)

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
    def make(self, data=None, fail=False, **kw):
        api = FakeAPI(data, fail, cache=self.cache)
        return Poller(cache=self.cache, api=api, alert_manager=AlertManager(self.cache), **kw), api

    def test_first_refresh_publishes_a_snapshot(self):
        poller, _ = self.make([payload("CX 759", gate="63")])
        records = poller.refresh_today()
        self.assertEqual(len(records), 1)
        snap = poller.snapshot()
        self.assertEqual(snap["source"], "api")
        self.assertEqual(snap["records_date"], TODAY)
        self.assertEqual(snap["revision"], 1)
        self.assertIsNone(snap["last_error"])
        self.assertFalse(snap["refreshing"])

    def test_snapshot_contains_the_expected_keys(self):
        poller, _ = self.make([payload("CX759")])
        poller.refresh_today()
        self.assertEqual(set(poller.snapshot()), {
            "revision", "records_date", "records", "source", "last_attempt_at",
            "last_api_success_at", "cache_saved_at", "last_error", "polling_enabled",
            "refreshing",
        })

    def test_gate_change_raises_an_alert_through_the_poller(self):
        poller, api = self.make([payload("CX 759", gate="62")])
        poller.refresh_today()
        api.data = [payload("CX 759", gate="63")]
        poller.refresh_today()
        active = poller.alert_manager.get_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["new_value"], "63")

    def test_failed_api_falls_back_to_cache(self):
        poller, api = self.make([payload("CX 759", gate="62")])
        poller.refresh_today()
        api.fail = True
        poller.refresh_today()
        snap = poller.snapshot()
        self.assertEqual(snap["source"], "cache")
        self.assertEqual(len(snap["records"]), 1)
        self.assertIsNotNone(snap["cache_saved_at"])
        self.assertIsNotNone(snap["last_error"])

    def test_failed_api_without_cache_keeps_memory_data(self):
        poller, api = self.make([payload("CX 759")])
        poller.refresh_today()
        self.cache.clear_flights(TODAY)
        api.fail = True
        poller.refresh_today()
        snap = poller.snapshot()
        self.assertEqual(snap["source"], "memory")
        self.assertEqual(len(snap["records"]), 1)

    def test_no_data_at_all_reports_none(self):
        poller, _ = self.make(None, fail=True)
        poller.refresh_today()
        snap = poller.snapshot()
        self.assertEqual(snap["source"], "none")
        self.assertEqual(snap["records"], [])
        self.assertIsNotNone(snap["last_error"])

    def test_failed_refresh_still_advances_the_revision(self):
        poller, api = self.make([payload("CX759")])
        poller.refresh_today()
        before = poller.revision()
        api.fail = True
        poller.refresh_today()
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
        poller.refresh_today()
        self.assertIsNot(poller.today_records, poller.today_records)
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
        self.poller = Poller(cache=self.cache, api=self.api,
                             alert_manager=AlertManager(self.cache))
        self.poller.refresh_today()
        self.server = WebServer(self.poller, self.api, self.poller.alert_manager, port=18095)

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
        self.assertEqual(cli._search_dates(None), [TODAY])


class TestCLIRendering(TempCacheCase):
    def test_table_output_is_one_row_per_flight(self):
        import contextlib
        import io

        records = normalize_flights([payload("CX 759", gate="63"), payload("UO 612")])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.print_flight_table(records, "Test")
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        data_rows = [ln for ln in lines if "CX759" in ln or "UO612" in ln]
        self.assertEqual(len(data_rows), 2)

    def test_paginate_records_navigation(self):
        records = normalize_flights([payload(f"CX {i}", gate=str(i)) for i in range(25)])
        replies = iter(["n", "p", "2", "q"])
        last = cli.paginate_records(records, "Test", page_size=10,
                                    input_func=lambda _p="": next(replies))
        self.assertEqual(last, 2)

    def test_paginate_empty(self):
        self.assertEqual(cli.paginate_records([], "Test"), 0)

    def test_paginate_handles_eof(self):
        records = normalize_flights([payload("CX 759")])

        def raise_eof(_prompt=""):
            raise EOFError

        cli.paginate_records(records, "Test", input_func=raise_eof)


class TestClearCache(TempCacheCase):
    def test_clears_only_owned_files(self):
        self.cache.write_flights(TODAY, [])
        self.cache.write_airlines([])
        self.cache.write_alerts({"active": [], "history": []})
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
        poller.refresh_today()

        api.data = [payload("CX 759", gate="63")]
        poller.refresh_today()
        self.assertEqual(alerts.active_count(), 1)

        api.data = [payload("CX 759", gate="63", status="Departed 09:10")]
        poller.refresh_today()
        self.assertEqual(alerts.active_count(), 0)
        self.assertEqual(len(alerts.get_history()), 1)


if __name__ == "__main__":
    unittest.main()
