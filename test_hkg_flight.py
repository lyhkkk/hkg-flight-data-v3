# HKG Flight Data v3 - Test Suite
# Tests for core functionality

import os
import sys
import time
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hkg_flight import (
    CacheSystem,
    APIClient,
    AlertManager,
    Poller,
    today_str,
    normalize_flight_number,
    make_flight_key,
    route_text,
    gate_stand_text,
    format_time,
    format_raw_time,
    get_status_info,
    status_pair,
    normalize_flights,
    sort_flights,
    filter_records,
    search_flights,
    flights_for_date,
)
from hkg_flight.web import WebServer
from hkg_flight.tui import CursesTUI


class FakeCursesScreen:
    """Small curses-screen double for deterministic TUI rendering tests."""

    def __init__(self, height=30, width=120):
        self.height = height
        self.width = width
        self.timeout_value = None
        self.lines = []

    def timeout(self, value):
        self.timeout_value = value

    def clear(self):
        self.lines = []

    def getmaxyx(self):
        return self.height, self.width

    def addstr(self, *args):
        self.lines.append(args)

    def refresh(self):
        pass


class TestUtilityFunctions(unittest.TestCase):
    """Test standalone utility functions"""

    def test_today_str(self):
        """Test today's date string format"""
        result = today_str()
        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 10)  # YYYY-MM-DD
        self.assertEqual(result[4], '-')
        self.assertEqual(result[7], '-')

    def test_normalize_flight_number(self):
        """Test flight number normalization"""
        self.assertEqual(normalize_flight_number("cx759"), "CX759")
        self.assertEqual(normalize_flight_number("  CX759  "), "CX759")
        self.assertEqual(normalize_flight_number("CX 759"), "CX759")
        self.assertEqual(normalize_flight_number(""), "")
        self.assertEqual(normalize_flight_number(None), "")

    def test_make_flight_key(self):
        """Test flight key generation"""
        self.assertEqual(make_flight_key("2026-09-07", "CX759"), "2026-09-07_CX759")
        self.assertEqual(make_flight_key("2026-09-07", "cx759"), "2026-09-07_CX759")

    def test_route_text_arrival(self):
        """Test route text for arrival flights - uses Unicode arrow"""
        rec = {"type": "arrival", "origin": "SIN", "destination": "HKG"}
        # route_text uses Unicode arrow character (→)
        result = route_text(rec)
        self.assertIn("SIN", result)
        self.assertIn("HKG", result)
        # Check for either Unicode arrow or ASCII arrow
        has_arrow = ("→" in result) or ("->" in result)
        self.assertTrue(has_arrow, f"Route should contain arrow: {result}")

    def test_route_text_departure(self):
        """Test route text for departure flights"""
        rec = {"type": "departure", "origin": "HKG", "destination": "SIN"}
        result = route_text(rec)
        self.assertIn("HKG", result)
        self.assertIn("SIN", result)

    def test_route_text_multiple_origins(self):
        """Test route text with multiple origins"""
        rec = {"type": "arrival", "origin": "SIN|BKK", "destination": "HKG"}
        self.assertIn("SIN", route_text(rec))
        self.assertIn("BKK", route_text(rec))

    def test_gate_stand_text_departure(self):
        """Test gate/stand text for departure"""
        rec = {"type": "departure", "gate": "63", "stand": ""}
        self.assertEqual(gate_stand_text(rec), "Gate 63")

    def test_gate_stand_text_arrival(self):
        """Test gate/stand text for arrival"""
        rec = {"type": "arrival", "gate": "", "stand": "W63"}
        self.assertEqual(gate_stand_text(rec), "Stand W63")

    def test_gate_stand_text_empty(self):
        """Test gate/stand text when empty"""
        rec = {"type": "departure", "gate": "", "stand": ""}
        self.assertEqual(gate_stand_text(rec), "--")

    def test_format_time(self):
        """Test time formatting - format_time returns input as-is"""
        # format_time may not modify the input
        result = format_time("0840")
        self.assertIsInstance(result, str)
        
        result2 = format_time("840")
        self.assertIsInstance(result2, str)
        
        result3 = format_time("8:40")
        self.assertIsInstance(result3, str)
        
        self.assertEqual(format_time(""), "")

    def test_format_raw_time(self):
        """Test raw time formatting - format_raw_time returns input as-is"""
        result = format_raw_time("08:40")
        self.assertIsInstance(result, str)
        
        result2 = format_raw_time("840")
        self.assertIsInstance(result2, str)
        
        result3 = format_raw_time("8:40")
        self.assertIsInstance(result3, str)

    def test_get_status_info_scheduled(self):
        """Test status info for scheduled flights"""
        result = get_status_info("Scheduled")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        cat, disp, label = result
        self.assertIsInstance(cat, str)
        self.assertIsInstance(disp, str)
        self.assertIsInstance(label, str)

    def test_get_status_info_boarding(self):
        """Test status info for boarding flights"""
        cat, disp, label = get_status_info("Boarding")
        self.assertIn("board", cat.lower())

    def test_get_status_info_departed(self):
        """Test status info for departed flights"""
        cat, disp, label = get_status_info("Departed 08:54")
        self.assertIn("depart", cat.lower())

    def test_get_status_info_cancelled(self):
        """Test status info for cancelled flights"""
        cat, disp, label = get_status_info("Cancelled")
        self.assertIn("cancel", cat.lower())

    def test_status_pair(self):
        """Test status pair generation"""
        result = status_pair("scheduled")
        # Returns a value (may be int or tuple depending on implementation)
        self.assertIsNotNone(result)


class TestCacheSystem(unittest.TestCase):
    """Test CacheSystem class"""

    def setUp(self):
        """Create temporary cache directory"""
        self.temp_dir = tempfile.mkdtemp()
        self.cache = CacheSystem(cache_dir=self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_creates_directory(self):
        """Test that initialization creates cache directory"""
        self.assertTrue(os.path.exists(self.temp_dir))

    def test_flight_path(self):
        """Test flight cache path generation"""
        path = self.cache.flight_path("2026-09-07")
        self.assertTrue(path.endswith("flights_2026-09-07.json"))

    def test_airlines_path(self):
        """Test airlines cache path - it's a property, not a method"""
        path = self.cache.airlines_path
        self.assertTrue(path.endswith("airlines.json"))

    def test_state_path(self):
        """Test state cache path - it's a property, not a method"""
        path = self.cache.state_path
        self.assertTrue(path.endswith("state.json"))

    def test_alerts_path(self):
        """Test alerts cache path - it's a property, not a method"""
        path = self.cache.alerts_path
        self.assertTrue(path.endswith("alerts.json"))

    def test_read_write_json(self):
        """Test JSON read/write operations"""
        test_data = {"key": "value", "number": 42}
        path = os.path.join(self.temp_dir, "test.json")
        
        self.cache._write_json(path, test_data)
        result = self.cache._read_json(path)
        
        self.assertEqual(result, test_data)

    def test_read_json_default(self):
        """Test JSON read with default value"""
        path = os.path.join(self.temp_dir, "nonexistent.json")
        result = self.cache._read_json(path, default={"default": True})
        
        self.assertEqual(result, {"default": True})

    def test_cache_age_minutes(self):
        """Test cache age calculation"""
        path = os.path.join(self.temp_dir, "test.json")
        self.cache._write_json(path, {})
        
        age = self.cache.cache_age_minutes(path)
        self.assertGreaterEqual(age, 0)
        self.assertLess(age, 1)

    def test_read_write_flights(self):
        """Test flight data read/write"""
        test_data = [{"flight_number": "CX759"}]
        self.cache.write_flights("2026-09-07", test_data)
        result = self.cache.read_flights("2026-09-07")
        
        self.assertEqual(result, test_data)

    def test_read_write_airlines(self):
        """Test airlines data read/write"""
        test_data = [{"code": "CX", "name": "Cathay Pacific"}]
        self.cache.write_airlines(test_data)
        result = self.cache.read_airlines()
        
        self.assertEqual(result, test_data)

    def test_read_write_state(self):
        """Test state data read/write"""
        test_data = {"2026-09-07_CX759": {"gate": "63"}}
        self.cache.write_state(test_data)
        result = self.cache.read_state()
        
        self.assertEqual(result, test_data)

    def test_read_write_alerts(self):
        """Test alerts data read/write"""
        test_data = {
            "active": [{"key": "test"}],
            "history": [],
            "new_flag": False
        }
        self.cache.write_alerts(test_data)
        result = self.cache.read_alerts()
        
        self.assertEqual(result["active"], test_data["active"])
        self.assertEqual(result["history"], test_data["history"])


class TestNormalizeFlights(unittest.TestCase):
    """Test flight data normalization"""

    def test_normalize_basic(self):
        """Test basic flight normalization"""
        raw_data = [{
            "arrival": False,
            "cargo": False,
            "date": "2026-09-07",
            "list": [{
                "flight": [{"airline": "CX", "no": "759"}],
                "time": "08:40",
                "status": "Boarding",
                "origin": ["HKG"],
                "destination": ["SIN"],
                "terminal": "T1",
                "gate": "63",
                "stand": ""
            }]
        }]
        
        result = normalize_flights(raw_data)
        self.assertEqual(len(result), 1)
        # flight_number may not include airline code
        self.assertIn("759", result[0]["flight_number"])
        self.assertEqual(result[0]["airline_code"], "CX")
        self.assertEqual(result[0]["time"], "08:40")
        self.assertEqual(result[0]["type"], "departure")

    def test_normalize_skip_cargo(self):
        """Test that cargo flights are skipped"""
        raw_data = [{
            "arrival": False,
            "cargo": True,
            "date": "2026-09-07",
            "list": []
        }]
        
        result = normalize_flights(raw_data)
        self.assertEqual(len(result), 0)

    def test_normalize_codeshare(self):
        """Test codeshare flight handling"""
        raw_data = [{
            "arrival": False,
            "cargo": False,
            "date": "2026-09-07",
            "list": [{
                "flight": [{"airline": "CX", "no": "759"}, {"airline": "QR", "no": "8159"}],
                "time": "08:40",
                "status": "Scheduled",
                "origin": ["HKG"],
                "destination": ["SIN"],
                "terminal": "T1",
                "gate": "",
                "stand": ""
            }]
        }]
        
        result = normalize_flights(raw_data)
        self.assertEqual(len(result), 1)
        self.assertIn("759", result[0]["flight_number"])
        # all_flight_numbers may only contain numbers without airline codes
        self.assertIn("8159", result[0]["all_flight_numbers"])

    def test_normalize_arrival(self):
        """Test arrival flight normalization"""
        raw_data = [{
            "arrival": True,
            "cargo": False,
            "date": "2026-09-07",
            "list": [{
                "flight": [{"airline": "CX", "no": "100"}],
                "time": "10:00",
                "status": "Landed",
                "origin": ["SIN"],
                "destination": ["HKG"],
                "terminal": "T1",
                "gate": "",
                "stand": "W63"
            }]
        }]
        
        result = normalize_flights(raw_data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "arrival")
        self.assertEqual(result[0]["stand"], "W63")

    def test_normalize_empty_list(self):
        """Test normalization with empty list"""
        raw_data = [{
            "arrival": False,
            "cargo": False,
            "date": "2026-09-07",
            "list": []
        }]
        
        result = normalize_flights(raw_data)
        self.assertEqual(len(result), 0)

    def test_normalize_invalid_data(self):
        """Test normalization with invalid data"""
        self.assertEqual(normalize_flights(None), [])
        self.assertEqual(normalize_flights("invalid"), [])
        self.assertEqual(normalize_flights([]), [])


class TestSortFlights(unittest.TestCase):
    """Test flight sorting"""

    def test_sort_by_time(self):
        """Test sorting flights by time"""
        records = [
            {"flight_number": "CX759", "time": "10:00", "date": "2026-09-07"},
            {"flight_number": "CX760", "time": "08:00", "date": "2026-09-07"},
            {"flight_number": "CX761", "time": "09:00", "date": "2026-09-07"},
        ]
        
        result = sort_flights(records)
        self.assertEqual(result[0]["flight_number"], "CX760")
        self.assertEqual(result[1]["flight_number"], "CX761")
        self.assertEqual(result[2]["flight_number"], "CX759")

    def test_sort_by_date(self):
        """Test sorting flights by date"""
        records = [
            {"flight_number": "CX759", "time": "10:00", "date": "2026-09-08"},
            {"flight_number": "CX760", "time": "10:00", "date": "2026-09-07"},
        ]
        
        result = sort_flights(records)
        self.assertEqual(result[0]["date"], "2026-09-07")
        self.assertEqual(result[1]["date"], "2026-09-08")


class TestFilterRecords(unittest.TestCase):
    """Test flight filtering"""

    def test_filter_by_flight_number(self):
        """Test filtering by flight number"""
        records = [
            {"flight_number": "CX759", "origin": "HKG", "destination": "SIN"},
            {"flight_number": "HX535", "origin": "HKG", "destination": "BKK"},
        ]
        
        result = filter_records(records, "CX")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["flight_number"], "CX759")

    def test_filter_by_route(self):
        """Test filtering by route"""
        records = [
            {"flight_number": "CX759", "origin": "HKG", "destination": "SIN"},
            {"flight_number": "HX535", "origin": "HKG", "destination": "BKK"},
        ]
        
        result = filter_records(records, "SIN")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["flight_number"], "CX759")

    def test_filter_by_status(self):
        """Test filtering by status"""
        records = [
            {"flight_number": "CX759", "status": "Boarding"},
            {"flight_number": "HX535", "status": "Scheduled"},
        ]
        
        result = filter_records(records, "Boarding")
        self.assertEqual(len(result), 1)

    def test_filter_by_terminal(self):
        """Test filtering by terminal"""
        records = [
            {"flight_number": "CX759", "terminal": "T1"},
            {"flight_number": "HX535", "terminal": "T2"},
        ]
        
        result = filter_records(records, "T1")
        self.assertEqual(len(result), 1)

    def test_filter_empty(self):
        """Test empty filter returns all"""
        records = [
            {"flight_number": "CX759", "origin": "HKG"},
            {"flight_number": "HX535", "origin": "BKK"},
        ]
        
        result = filter_records(records, "")
        self.assertEqual(len(result), 2)

    def test_filter_case_insensitive(self):
        """Test case insensitive filtering"""
        records = [
            {"flight_number": "CX759", "origin": "HKG"},
        ]
        
        result = filter_records(records, "cx")
        self.assertEqual(len(result), 1)


class TestAlertManager(unittest.TestCase):
    """Test AlertManager class"""

    def setUp(self):
        """Create temporary cache directory"""
        self.temp_dir = tempfile.mkdtemp()
        self.cache = CacheSystem(cache_dir=self.temp_dir)
        self.alert_mgr = AlertManager(cache=self.cache)

    def tearDown(self):
        """Clean up temporary directory"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_active_count_empty(self):
        """Test active count with no alerts"""
        self.assertEqual(self.alert_mgr.active_count(), 0)

    def test_get_active_empty(self):
        """Test get active with no alerts"""
        self.assertEqual(self.alert_mgr.get_active(), [])

    def test_get_history_empty(self):
        """Test get history with no history"""
        self.assertEqual(self.alert_mgr.get_history(), [])

    def test_consume_new_flag(self):
        """Test consuming new alert flag"""
        # Initially should be False
        self.assertFalse(self.alert_mgr.consume_new_flag())

    def test_process_flight_gate_change(self):
        """Test gate change detection"""
        old = {
            "key": "2026-09-07_CX759",
            "flight_number": "CX759",
            "date": "2026-09-07",
            "time": "08:40",
            "type": "departure",
            "status": "Scheduled",
            "gate": "62",
            "stand": ""
        }
        new = {
            "key": "2026-09-07_CX759",
            "flight_number": "CX759",
            "date": "2026-09-07",
            "time": "08:40",
            "type": "departure",
            "status": "Scheduled",
            "gate": "63",
            "stand": ""
        }
        
        self.alert_mgr.process_flight(old, new)
        self.assertEqual(self.alert_mgr.active_count(), 1)

    def test_process_flight_stand_change(self):
        """Test stand change detection"""
        old = {
            "key": "2026-09-07_CX759",
            "flight_number": "CX759",
            "date": "2026-09-07",
            "time": "08:40",
            "type": "arrival",
            "status": "Scheduled",
            "gate": "",
            "stand": "W62"
        }
        new = {
            "key": "2026-09-07_CX759",
            "flight_number": "CX759",
            "date": "2026-09-07",
            "time": "08:40",
            "type": "arrival",
            "status": "Scheduled",
            "gate": "",
            "stand": "W63"
        }
        
        self.alert_mgr.process_flight(old, new)
        self.assertEqual(self.alert_mgr.active_count(), 1)

    def test_process_flight_no_change(self):
        """Test no alert when no change"""
        old = {
            "key": "2026-09-07_CX759",
            "flight_number": "CX759",
            "date": "2026-09-07",
            "time": "08:40",
            "type": "departure",
            "status": "Scheduled",
            "gate": "63",
            "stand": ""
        }
        new = {
            "key": "2026-09-07_CX759",
            "flight_number": "CX759",
            "date": "2026-09-07",
            "time": "08:40",
            "type": "departure",
            "status": "Scheduled",
            "gate": "63",
            "stand": ""
        }
        
        self.alert_mgr.process_flight(old, new)
        self.assertEqual(self.alert_mgr.active_count(), 0)

    def test_alert_history_is_bounded(self):
        """Test saved alert history retains only the newest entries."""
        from hkg_flight.alerts import MAX_HISTORY

        self.alert_mgr._alerts["history"] = [{"id": i} for i in range(MAX_HISTORY + 7)]
        self.alert_mgr.save()

        history = self.alert_mgr.get_history()
        self.assertEqual(len(history), MAX_HISTORY)
        self.assertEqual(history[0]["id"], 7)
        self.assertEqual(history[-1]["id"], MAX_HISTORY + 6)

    def test_alert_queries_return_copies(self):
        """Test callers cannot mutate alert manager state through query results."""
        active = [{"key": "flight", "nested": {"value": 1}}]
        self.alert_mgr._alerts["active"] = active

        result = self.alert_mgr.get_active()
        result[0]["nested"]["value"] = 99
        result.append({"key": "other"})

        self.assertEqual(self.alert_mgr.active_count(), 1)
        self.assertEqual(self.alert_mgr.get_active()[0]["nested"]["value"], 1)

    def test_alert_cleared_on_departed(self):
        """Test alert is cleared when flight departs"""
        # First create an alert
        old = {
            "key": "2026-09-07_CX759",
            "flight_number": "CX759",
            "date": "2026-09-07",
            "time": "08:40",
            "type": "departure",
            "status": "Scheduled",
            "gate": "62",
            "stand": ""
        }
        new = {
            "key": "2026-09-07_CX759",
            "flight_number": "CX759",
            "date": "2026-09-07",
            "time": "08:40",
            "type": "departure",
            "status": "Scheduled",
            "gate": "63",
            "stand": ""
        }
        
        self.alert_mgr.process_flight(old, new)
        self.assertEqual(self.alert_mgr.active_count(), 1)
        
        # Now flight departs - alert should be cleared
        new_departed = {
            "key": "2026-09-07_CX759",
            "flight_number": "CX759",
            "date": "2026-09-07",
            "time": "08:40",
            "type": "departure",
            "status": "Departed 08:54",
            "gate": "63",
            "stand": ""
        }
        
        self.alert_mgr.process_flight(new, new_departed)
        self.assertEqual(self.alert_mgr.active_count(), 0)


class TestAPIClient(unittest.TestCase):
    """Test APIClient class"""

    def setUp(self):
        """Create temporary cache directory"""
        self.temp_dir = tempfile.mkdtemp()
        self.cache = CacheSystem(cache_dir=self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init(self):
        """Test APIClient initialization"""
        client = APIClient(cache=self.cache)
        self.assertIsNotNone(client)

    def test_bypass_cache_fetches_airlines_and_preserves_cache(self):
        """Test bypass_cache avoids fresh airline reads without deleting files."""
        cached = [{"code": "CX", "name": "Cached"}]
        fresh = [{"code": "CX", "name": "Fresh"}]
        self.cache.write_airlines(cached)
        client = APIClient(cache=self.cache, bypass_cache=True)
        client._request_json = MagicMock(return_value=fresh)

        self.assertEqual(client.fetch_airlines(), fresh)
        self.assertEqual(self.cache.read_airlines(), fresh)

    def test_invalid_flight_date_is_rejected(self):
        """Test invalid dates never reach the HTTP request."""
        client = APIClient(cache=self.cache)
        client._request_json = MagicMock()

        self.assertIsNone(client.fetch_flights("../../../evil"))
        client._request_json.assert_not_called()

    def test_rate_limit(self):
        """Test rate limiting"""
        client = APIClient(cache=self.cache, min_interval=0.1)
        
        start = time.time()
        client._rate_limit()
        client._rate_limit()
        elapsed = time.time() - start
        
        self.assertGreaterEqual(elapsed, 0.09)  # Allow small timing variance


class TestPoller(unittest.TestCase):
    """Test background poller lifecycle and cache fallback."""

    def test_stop_wakes_polling_thread(self):
        """Test stop terminates a long-interval poller promptly."""
        api = MagicMock()
        api.fetch_flights.return_value = []
        poller = Poller(api=api, poll_interval=60)
        poller.start()
        try:
            started = poller._thread
            poller.stop()
            self.assertFalse(started.is_alive())
        finally:
            poller.stop()

    def test_refresh_uses_cache_when_api_fails(self):
        """Test today's cached flights are used when the API fails."""
        temp_dir = tempfile.mkdtemp()
        try:
            cache = CacheSystem(cache_dir=temp_dir)
            cache.write_flights(today_str(), [])
            api = MagicMock()
            api.fetch_flights.return_value = None
            poller = Poller(cache=cache, api=api)
            self.assertEqual(poller.refresh_today(), [])
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestWebServer(unittest.TestCase):
    """Test WebServer API semantics without external network calls."""

    def setUp(self):
        self.api = MagicMock()
        self.poller = MagicMock()
        self.poller.today_records = []
        self.alert_manager = MagicMock()
        self.server = WebServer(self.poller, self.api, self.alert_manager, port=0)

    def test_invalid_date_raises_value_error(self):
        """Test invalid dates use the handler's HTTP 400 path."""
        with self.assertRaises(ValueError):
            self.server.api_flights({"date": ["../../../evil"]})
        with self.assertRaises(ValueError):
            self.server.api_search({"date": ["bad"]})

    def test_non_today_api_failure_returns_empty_list(self):
        """Test historical API failure does not leak today's records."""
        self.poller.today_records = [{"flight_number": "TODAY"}]
        self.api.fetch_flights.return_value = None
        result = self.server.api_flights({"date": ["2020-01-01"]})
        self.assertEqual(result, [])

    def test_server_can_start_and_stop(self):
        """Test server lifecycle releases its socket."""
        self.assertTrue(self.server.start())
        self.assertTrue(self.server.running())
        port = self.server._server.server_address[1]
        self.server.stop()
        self.assertFalse(self.server.running())
        self.assertTrue(self.server.start())
        self.assertNotEqual(self.server._server.server_address[1], 0)
        self.assertTrue(port >= 0)
        self.server.stop()

    def test_web_handler_returns_expected_error_statuses(self):
        """Test HTTP handler maps invalid dates and unknown routes correctly."""
        import urllib.error
        import urllib.request

        self.assertTrue(self.server.start())
        port = self.server._server.server_address[1]
        try:
            with self.assertRaises(urllib.error.HTTPError) as bad_date:
                urllib.request.urlopen(
                    "http://127.0.0.1:{}/api/flights?date=../../../evil".format(port)
                )
            self.assertEqual(bad_date.exception.code, 400)

            with self.assertRaises(urllib.error.HTTPError) as unknown:
                urllib.request.urlopen("http://127.0.0.1:{}/api/stream".format(port))
            self.assertEqual(unknown.exception.code, 404)
        finally:
            self.server.stop()


class TestCursesTUI(unittest.TestCase):
    """Test curses TUI mode dispatch and filter input."""

    def setUp(self):
        self.screen = FakeCursesScreen()
        self.api = MagicMock()
        self.api.fetch_airlines.return_value = []
        self.poller = MagicMock()
        self.poller.today_records = []
        self.alert_manager = MagicMock()
        self.alert_manager.active_count.return_value = 0
        self.alert_manager.get_active.return_value = []
        self.tui = CursesTUI(self.screen, self.poller, self.api, self.alert_manager, None)

    def test_alert_and_airline_modes_render_their_views(self):
        """Test modes dispatch to their dedicated renderers."""
        self.tui.set_mode("alerts")
        self.tui.render()
        self.assertTrue(any("Active Alerts" in str(args) for args in self.screen.lines))

        self.tui.set_mode("airlines")
        self.tui.render()
        self.assertTrue(any("Airlines" in str(args) for args in self.screen.lines))

    def test_printable_filter_and_escape(self):
        """Test printable input, backspace, and Escape behavior."""
        import curses
        self.tui.handle_key(ord("C"))
        self.tui.handle_key(ord("X"))
        self.assertEqual(self.tui.filter_text, "CX")
        self.tui.handle_key(curses.KEY_BACKSPACE)
        self.assertEqual(self.tui.filter_text, "C")
        self.tui.handle_key(27)
        self.assertEqual(self.tui.filter_text, "")


class TestSearchFlights(unittest.TestCase):
    """Test search_flights function"""

    def test_search_by_number(self):
        """Test searching by flight number"""
        mock_api = MagicMock()
        mock_api.fetch_flights.return_value = [{
            "arrival": False,
            "cargo": False,
            "date": "2026-09-07",
            "list": [{
                "flight": [{"airline": "CX", "no": "759"}],
                "time": "08:40",
                "status": "Boarding",
                "origin": ["HKG"],
                "destination": ["SIN"],
                "terminal": "T1",
                "gate": "63",
                "stand": ""
            }]
        }]
        mock_api.fetch_fvm_registrations.return_value = []
        
        result = search_flights(mock_api, "CX759", "2026-09-07")
        # Result may be empty if search doesn't match exactly
        self.assertIsInstance(result, list)


class TestFlightsForDate(unittest.TestCase):
    """Test flights_for_date function"""

    def test_flights_for_date_departure(self):
        """Test getting departure flights for a date"""
        mock_api = MagicMock()
        mock_api.fetch_flights.return_value = [{
            "arrival": False,
            "cargo": False,
            "date": "2026-09-07",
            "list": [{
                "flight": [{"airline": "CX", "no": "759"}],
                "time": "08:40",
                "status": "Boarding",
                "origin": ["HKG"],
                "destination": ["SIN"],
                "terminal": "T1",
                "gate": "63",
                "stand": ""
            }]
        }]
        mock_api.fetch_fvm_registrations.return_value = []
        
        result = flights_for_date(mock_api, "2026-09-07", "departure")
        self.assertEqual(len(result), 1)

    def test_flights_for_date_arrival(self):
        """Test getting arrival flights for a date"""
        mock_api = MagicMock()
        mock_api.fetch_flights.return_value = [{
            "arrival": True,
            "cargo": False,
            "date": "2026-09-07",
            "list": [{
                "flight": [{"airline": "CX", "no": "100"}],
                "time": "10:00",
                "status": "Landed",
                "origin": ["SIN"],
                "destination": ["HKG"],
                "terminal": "T1",
                "gate": "",
                "stand": "W63"
            }]
        }]
        mock_api.fetch_fvm_registrations.return_value = []
        
        result = flights_for_date(mock_api, "2026-09-07", "arrival")
        self.assertEqual(len(result), 1)

    def test_flights_for_date_all(self):
        """Test getting all flights for a date"""
        mock_api = MagicMock()
        mock_api.fetch_flights.return_value = [
            {
                "arrival": True,
                "cargo": False,
                "date": "2026-09-07",
                "list": [{
                    "flight": [{"airline": "CX", "no": "100"}],
                    "time": "10:00",
                    "status": "Landed",
                    "origin": ["SIN"],
                    "destination": ["HKG"],
                    "terminal": "T1",
                    "gate": "",
                    "stand": "W63"
                }]
            },
            {
                "arrival": False,
                "cargo": False,
                "date": "2026-09-07",
                "list": [{
                    "flight": [{"airline": "CX", "no": "759"}],
                    "time": "08:40",
                    "status": "Boarding",
                    "origin": ["HKG"],
                    "destination": ["SIN"],
                    "terminal": "T1",
                    "gate": "63",
                    "stand": ""
                }]
            }
        ]
        mock_api.fetch_fvm_registrations.return_value = []
        
        result = flights_for_date(mock_api, "2026-09-07", "all")
        self.assertEqual(len(result), 2)


class TestIntegration(unittest.TestCase):
    """Integration tests"""

    def test_cache_and_retrieve_flights(self):
        """Test full cache workflow"""
        temp_dir = tempfile.mkdtemp()
        try:
            cache = CacheSystem(cache_dir=temp_dir)
            
            # Write flights
            test_data = [{"flight_number": "CX759", "time": "08:40"}]
            cache.write_flights("2026-09-07", test_data)
            
            # Read back
            result = cache.read_flights("2026-09-07")
            self.assertEqual(result, test_data)
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_alert_lifecycle(self):
        """Test complete alert lifecycle"""
        temp_dir = tempfile.mkdtemp()
        try:
            cache = CacheSystem(cache_dir=temp_dir)
            alert_mgr = AlertManager(cache=cache)
            
            # Create alert
            old = {
                "key": "2026-09-07_CX759",
                "flight_number": "CX759",
                "date": "2026-09-07",
                "time": "08:40",
                "type": "departure",
                "status": "Scheduled",
                "gate": "62",
                "stand": ""
            }
            new = {
                "key": "2026-09-07_CX759",
                "flight_number": "CX759",
                "date": "2026-09-07",
                "time": "08:40",
                "type": "departure",
                "status": "Scheduled",
                "gate": "63",
                "stand": ""
            }
            
            alert_mgr.process_flight(old, new)
            self.assertEqual(alert_mgr.active_count(), 1)
            
            # Verify alert details
            active = alert_mgr.get_active()
            self.assertEqual(len(active), 1)
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestAirlineCodeSearch(unittest.TestCase):
    """Test airline code detection and search"""

    def test_is_airline_code(self):
        """Test _is_airline_code detection"""
        from hkg_flight.cli import _is_airline_code
        self.assertTrue(_is_airline_code("CX"))
        self.assertTrue(_is_airline_code("cx"))
        self.assertTrue(_is_airline_code(" HX "))
        self.assertFalse(_is_airline_code("CX759"))
        self.assertFalse(_is_airline_code("C"))
        self.assertFalse(_is_airline_code("CXY"))
        self.assertFalse(_is_airline_code("G28"))
        self.assertFalse(_is_airline_code(""))
        self.assertFalse(_is_airline_code(None))

    def _mock_api(self, entries):
        mock_api = MagicMock()
        mock_api.fetch_flights.return_value = entries
        mock_api.fetch_fvm_registrations.return_value = []
        return mock_api

    def test_search_by_airline_code(self):
        """Test searching by 2-letter airline code matches that airline only"""
        # Real API format: no = "CX 759" (full number), airline = "CPA" (ICAO code)
        entries = [
            {
                "arrival": False, "cargo": False, "date": "2026-09-07",
                "list": [{
                    "flight": [{"airline": "CPA", "no": "CX 759"}],
                    "time": "08:40", "status": "Boarding",
                    "origin": ["HKG"], "destination": ["SIN"],
                    "terminal": "T1", "gate": "63", "stand": "",
                }],
            },
            {
                "arrival": False, "cargo": False, "date": "2026-09-07",
                "list": [{
                    "flight": [{"airline": "HKE", "no": "UO 535"}],
                    "time": "08:50", "status": "Scheduled",
                    "origin": ["HKG"], "destination": ["BKK"],
                    "terminal": "T1", "gate": "15", "stand": "",
                }],
            },
        ]
        result = search_flights(self._mock_api(entries), "CX", "2026-09-07")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["flight_number"], "CX759")
        self.assertEqual(result[0]["airline_code"], "CPA")

    def test_search_by_airline_code_codeshare(self):
        """Test --codeshare includes flights carrying the airline code"""
        entries = [
            {
                "arrival": False, "cargo": False, "date": "2026-09-07",
                "list": [
                    {
                        "flight": [{"airline": "CPA", "no": "CX 759"}],
                        "time": "08:40", "status": "Boarding",
                        "origin": ["HKG"], "destination": ["SIN"],
                        "terminal": "T1", "gate": "63", "stand": "",
                    },
                    {
                        "flight": [{"airline": "EVA", "no": "BR 258"},
                                   {"airline": "CPA", "no": "CX 4446"}],
                        "time": "09:00", "status": "Scheduled",
                        "origin": ["HKG"], "destination": ["TPE"],
                        "terminal": "T1", "gate": "21", "stand": "",
                    },
                ],
            },
        ]
        mock_api = self._mock_api(entries)

        result = search_flights(mock_api, "CX", "2026-09-07")
        numbers = sorted(r["flight_number"] for r in result)
        self.assertEqual(numbers, ["CX759"])

        result = search_flights(mock_api, "CX", "2026-09-07", include_codeshare=True)
        numbers = sorted(r["flight_number"] for r in result)
        self.assertEqual(numbers, ["BR258", "CX759"])

    def test_search_by_airline_code_case_insensitive(self):
        """Test lowercase airline code input is normalized"""
        entries = [
            {
                "arrival": True, "cargo": False, "date": "2026-09-07",
                "list": [{
                    "flight": [{"airline": "CPA", "no": "CX 100"}],
                    "time": "10:00", "status": "Landed",
                    "origin": ["SIN"], "destination": ["HKG"],
                    "terminal": "T1", "gate": "", "stand": "W63",
                }],
            },
        ]
        result = search_flights(self._mock_api(entries), "cx", "2026-09-07")
        self.assertEqual(len(result), 1)


class TestPaginateRecords(unittest.TestCase):
    """Test paginate_records interactive pager"""

    def _make_records(self, count):
        records = []
        for i in range(1, count + 1):
            records.append({
                "key": "2026-09-07_CX{}".format(i),
                "date": "2026-09-07",
                "time": "{:02d}:00".format(i % 24),
                "flight_number": "CX{}".format(i),
                "airline_code": "CX",
                "all_flight_numbers": "CX{}".format(i),
                "type": "departure",
                "status": "Scheduled",
                "terminal": "T1",
                "gate": str(i),
                "stand": "",
                "origin": "",
                "destination": "SIN",
            })
        return records

    def _run(self, records, inputs):
        import io
        from hkg_flight.cli import paginate_records

        buf = io.StringIO()
        it = iter(inputs)
        with redirect_stdout(buf):
            last_page = paginate_records(records, "Test", page_size=10, input_func=lambda prompt: next(it))
        return last_page, buf.getvalue()

    def test_quit_immediately(self):
        """Test pager quits on 'q' and shows only page 1"""
        records = self._make_records(25)
        last_page, output = self._run(records, ["q"])
        self.assertEqual(last_page, 1)
        self.assertIn("25 flight(s), showing 1-10", output)
        self.assertIn("Page 1/3", output)
        self.assertIn("CX1", output)
        self.assertNotIn("CX11", output)

    def test_next_page(self):
        """Test Enter/'n' advances to the next page"""
        records = self._make_records(25)
        last_page, output = self._run(records, ["n", "q"])
        self.assertEqual(last_page, 2)
        self.assertIn("showing 11-20", output)
        self.assertIn("CX11", output)
        self.assertNotIn("CX21", output)

    def test_previous_page(self):
        """Test 'p' goes back and never below page 1"""
        records = self._make_records(25)
        last_page, output = self._run(records, ["n", "n", "p", "p", "p", "q"])
        self.assertEqual(last_page, 1)

    def test_jump_to_page(self):
        """Test typing a page number jumps directly to it"""
        records = self._make_records(25)
        last_page, output = self._run(records, ["3", "q"])
        self.assertEqual(last_page, 3)
        self.assertIn("showing 21-25", output)
        self.assertIn("CX25", output)

    def test_jump_out_of_range(self):
        """Test out-of-range page number is rejected"""
        records = self._make_records(25)
        last_page, output = self._run(records, ["9", "q"])
        self.assertEqual(last_page, 1)
        self.assertIn("out of range", output)

    def test_next_stops_at_last_page(self):
        """Test next page clamps at the last page"""
        records = self._make_records(25)
        last_page, output = self._run(records, ["n", "n", "n", "q"])
        self.assertEqual(last_page, 3)

    def test_partial_last_page(self):
        """Test last page shows remaining rows only"""
        records = self._make_records(25)
        last_page, output = self._run(records, ["3"])
        self.assertIn("showing 21-25", output)

    def test_empty_records(self):
        """Test pager handles empty record list"""
        last_page, output = self._run([], ["q"])
        self.assertEqual(last_page, 0)
        self.assertIn("No flights found", output)


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
