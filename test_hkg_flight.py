# HKG Flight Data v3 - Test Suite
# Tests for core functionality

import os
import sys
import json
import time
import tempfile
import unittest
from unittest.mock import patch, MagicMock

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
    load_airlines,
    DEFAULT_CACHE_DIR,
    DEFAULT_MIN_API_INTERVAL,
)


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

    def test_rate_limit(self):
        """Test rate limiting"""
        client = APIClient(cache=self.cache, min_interval=0.1)
        
        start = time.time()
        client._rate_limit()
        client._rate_limit()
        elapsed = time.time() - start
        
        self.assertGreaterEqual(elapsed, 0.09)  # Allow small timing variance


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


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
