"""
Tests for the terminal feed: poller atomic snapshots, request coalescing,
source/timestamps metadata, airline failure metadata and alerts revision.
"""

import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from hkg_flight.cache import CacheSystem
from hkg_flight.api import APIClient
from hkg_flight.alerts import AlertManager
from hkg_flight.poller import Poller
from hkg_flight.utils import today_str


class TestPollerSnapshot(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache = CacheSystem(cache_dir=self.temp_dir)
        self.api = MagicMock()
        self.alert_manager = AlertManager(cache=self.cache)
        self.poller = Poller(cache=self.cache, api=self.api,
                             alert_manager=self.alert_manager, poll_interval=60)

    def tearDown(self):
        self.poller.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_snapshot_is_defensive_copy(self):
        self.api.fetch_flights.return_value = []
        self.poller.refresh_today()
        snap = self.poller.snapshot()
        snap["records"].append({"flight_number": "MUTATED"})
        self.assertEqual(self.poller.snapshot()["records"], [])

    def test_revision_advances_even_on_failure(self):
        self.api.fetch_flights.return_value = []
        self.poller.refresh_today()
        first = self.poller.snapshot()["revision"]
        self.api.fetch_flights.return_value = None
        self.poller.refresh_today()
        second = self.poller.snapshot()["revision"]
        self.assertEqual(second, first + 1)
        self.assertEqual(self.poller.snapshot()["source"], "memory")

    def test_empty_list_is_success_not_failure(self):
        self.api.fetch_flights.return_value = []
        self.poller.refresh_today()
        snap = self.poller.snapshot()
        self.assertEqual(snap["source"], "api")
        self.assertIsNotNone(snap["last_api_success_at"])
        self.assertIsNone(snap["last_error"])

    def test_cache_fallback_sets_source_and_saved_at(self):
        date = today_str()
        self.cache.write_flights(date, [{"flight_number": "CACHED"}])
        self.api.fetch_flights.return_value = None
        self.poller.refresh_today()
        snap = self.poller.snapshot()
        self.assertEqual(snap["source"], "cache")
        self.assertIsNotNone(snap["cache_saved_at"])
        self.assertIsNone(snap["last_api_success_at"])

    def test_request_refresh_states(self):
        self.poller.start_background()
        try:
            result = self.poller.request_refresh()
            self.assertIn(result, ("accepted", "already_running"))
        finally:
            self.poller.stop()
        self.poller.stop()
        self.assertEqual(self.poller.request_refresh(), "closed")

    def test_no_duplicate_in_flight_refresh(self):
        import threading
        started = threading.Event()
        release = threading.Event()
        calls = []

        def slow_fetch(date):
            calls.append(date)
            started.set()
            release.wait(timeout=5)
            return []

        self.api.fetch_flights = MagicMock(side_effect=slow_fetch)
        thread = threading.Thread(target=self.poller._do_refresh)
        thread.start()
        started.wait(5)
        try:
            # A manual request while one refresh is running coalesces.
            self.assertEqual(self.poller.request_refresh(), "already_running")
        finally:
            release.set()
            thread.join(5)
        self.assertEqual(len(calls), 1)

    def test_refresh_slot_is_released_after_completion(self):
        """A finished refresh must release the slot again (no stuck slot)."""
        self.api.fetch_flights.return_value = []
        self.poller.refresh_today()
        self.assertFalse(self.poller.snapshot()["refreshing"])
        self.assertEqual(self.poller.request_refresh(), "accepted")

    def test_no_poll_still_first_refreshes_once(self):
        poller = Poller(cache=self.cache, api=self.api,
                        alert_manager=self.alert_manager, poll_interval=60, enabled=False)
        poller.start_background()
        try:
            deadline = 5.0
            import time
            start = time.time()
            while time.time() - start < deadline:
                if poller.snapshot()["revision"] >= 1:
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(poller.snapshot()["revision"], 1)
        finally:
            poller.stop()


class TestAlertRevision(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache = CacheSystem(cache_dir=self.temp_dir)
        self.alert_manager = AlertManager(cache=self.cache)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_revision_increments_on_change_and_clear(self):
        old = {"key": "2026-09-09_CX759", "flight_number": "CX759", "date": "2026-09-09",
               "time": "08:40", "type": "departure", "status": "Scheduled",
               "gate": "62", "stand": ""}
        new = dict(old, gate="63")
        base = self.alert_manager.alerts_revision()
        self.alert_manager.process_flight(old, new)
        self.assertEqual(self.alert_manager.alerts_revision(), base + 1)
        self.alert_manager.process_flight(new, dict(new, status="Departed"))
        self.assertEqual(self.alert_manager.alerts_revision(), base + 2)

    def test_snapshot_is_defensive(self):
        snap = self.alert_manager.snapshot()
        snap["alerts"].append({"key": "x"})
        self.assertEqual(self.alert_manager.snapshot()["alerts"], [])


class TestAirlineMetadata(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache = CacheSystem(cache_dir=self.temp_dir)
        self.client = APIClient(cache=self.cache)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_fresh_airlines_ok(self):
        self.client._request_json = MagicMock(return_value=[{"code": "CX"}])
        meta = self.client.fetch_airlines_meta()
        self.assertTrue(meta["ok"])
        self.assertEqual(meta["source"], "api")
        self.assertEqual(meta["airlines"], [{"code": "CX"}])

    def test_airline_failure_metadata_distinguishes_from_empty(self):
        self.client._request_json = MagicMock(return_value=None)
        meta = self.client.fetch_airlines_meta()
        self.assertFalse(meta["ok"])
        self.assertEqual(meta["source"], "none")
        self.assertEqual(meta["airlines"], [])


class TestCacheMtime(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache = CacheSystem(cache_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_flight_mtime_none_for_missing_file(self):
        self.assertIsNone(self.cache.flight_mtime("2020-01-01"))

    def test_flight_mtime_is_epoch(self):
        self.cache.write_flights("2026-09-09", [])
        self.assertIsInstance(self.cache.flight_mtime("2026-09-09"), float)


if __name__ == "__main__":
    unittest.main(verbosity=2)
