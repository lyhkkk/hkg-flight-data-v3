"""V3-G0 red baseline for the known terminal counterexamples.

These tests intentionally describe the V3 contracts before production fixes.
Failures are evidence for the next repair gate, not a request to weaken the
contract or to hide the failure behind a reducer-only assertion.
"""

import shutil
import threading
import time
import unittest
import unicodedata
import asyncio
import importlib.util
from unittest.mock import MagicMock

from hkg_flight.alerts import AlertManager
from hkg_flight.cache import CacheSystem
from hkg_flight.poller import Poller
from hkg_flight.terminal.presenter import DEPARTURES, visible_rows
from hkg_flight.terminal.session import Session
from hkg_flight.terminal import views
from hkg_flight.terminal import plain
from tests.fixtures.terminal.data import make_combined_snapshot, make_flight


class TestV3G0DataAndLifecycleBaseline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = "/tmp/hkg-flight-v3-g0-baseline-{}".format(id(self))
        self.cache = CacheSystem(cache_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_r01_session_snapshot_is_deeply_isolated(self):
        session = Session(cache=self.cache, api=MagicMock(),
                          alert_manager=AlertManager(cache=self.cache), no_poll=True)
        session._airlines = [{"code": "CX", "description": ["Cathay"]}]
        snapshot = session.snapshot()
        snapshot["airlines"]["airlines"][0]["description"].append("MUTATED")
        self.assertEqual(session.airlines_snapshot()["airlines"][0]["description"], ["Cathay"])

    def test_r02_mutable_flight_fields_do_not_change_entity_id(self):
        old = make_flight(0)
        updated = dict(old, status="Boarding", status_category="boarding", gate="63")
        old_id = visible_rows({"records": [old]}, DEPARTURES, "")[0]["id"]
        new_id = visible_rows({"records": [updated]}, DEPARTURES, "")[0]["id"]
        self.assertEqual(new_id, old_id)

    def test_r03_pending_requests_are_coalesced(self):
        api = MagicMock()
        poller = Poller(cache=self.cache, api=api, enabled=False)
        try:
            self.assertEqual(poller.request_refresh(), "accepted")
            self.assertEqual(poller.request_refresh(), "already_running")
        finally:
            poller.stop()

    def test_r04_closed_refresh_cannot_publish_late_result(self):
        started = threading.Event()
        release = threading.Event()
        api = MagicMock()

        def fetch(_date):
            started.set()
            release.wait(5)
            return [{"arrival": False, "cargo": False, "date": "2026-09-09",
                     "list": [{"flight": [{"airline": "CX", "no": "100"}],
                               "time": "08:00", "status": "Scheduled"}]}]

        api.fetch_flights.side_effect = fetch
        poller = Poller(cache=self.cache, api=api, enabled=False)
        poller.start_background()
        self.assertTrue(started.wait(5))
        close_done = threading.Event()

        def close():
            poller.stop()
            close_done.set()

        closer = threading.Thread(target=close)
        closer.start()
        time.sleep(0.05)
        release.set()
        closer.join(5)
        self.assertTrue(close_done.is_set())
        self.assertEqual(poller.snapshot()["records"], [])

    def test_r05_airline_worker_cannot_publish_after_session_close(self):
        started = threading.Event()
        release = threading.Event()
        api = MagicMock()
        api.fetch_flights.return_value = []

        def fetch_airlines():
            started.set()
            release.wait(5)
            return {"airlines": [{"code": "CX"}], "source": "api",
                    "ok": True, "error": None}

        api.fetch_airlines_meta.side_effect = fetch_airlines
        session = Session(cache=self.cache, api=api,
                          alert_manager=AlertManager(cache=self.cache), no_poll=True)
        session.start()
        self.assertTrue(started.wait(5))
        session.close()
        release.set()
        deadline = time.time() + 5
        while time.time() < deadline and not session.airlines_snapshot()["loaded"]:
            time.sleep(0.01)
        self.assertFalse(session.airlines_snapshot()["loaded"])

    def test_r06_empty_api_success_is_zero_in_plain_mode(self):
        api = MagicMock()
        api.fetch_flights.return_value = []
        session = Session(cache=self.cache, api=api,
                          alert_manager=AlertManager(cache=self.cache), no_poll=True)
        try:
            session.poller.refresh_today()
            output = []
            code = plain.run_plain(session, input_func=lambda _prompt: "",
                                   out=output.append, tty=False)
            self.assertEqual(code, 0)
        finally:
            session.close()

    def test_r10_closed_poller_rejects_new_refresh(self):
        poller = Poller(cache=self.cache, api=MagicMock(), enabled=False)
        poller.stop()
        self.assertEqual(poller.request_refresh(), "closed")


class TestV3G0PresentationBaseline(unittest.TestCase):
    def test_r07_external_markup_is_literal(self):
        snapshot = make_combined_snapshot(2)
        record = snapshot["flights"]["records"][0]
        record["status"] = "[bold red]INJECT[/]"
        record["status_category"] = "boarding"
        from hkg_flight.terminal.state import AppState, reconcile
        state = AppState()
        state.current = DEPARTURES
        rows = visible_rows(snapshot["flights"], DEPARTURES, "")
        reconcile(state, rows)
        rendered = "\n".join(views.body_lines(state, snapshot, 80, 24, color=True))
        self.assertNotIn("[bold red]", rendered)

    def test_r08_display_cell_width_is_bounded(self):
        snapshot = make_combined_snapshot(2)
        record = snapshot["flights"]["records"][0]
        record["destination"] = "北京" * 12
        from hkg_flight.terminal.state import AppState, reconcile
        state = AppState()
        state.current = DEPARTURES
        rows = visible_rows(snapshot["flights"], DEPARTURES, "")
        reconcile(state, rows)
        for line in views.body_lines(state, snapshot, 40, 16, color=False):
            width = sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in line)
            self.assertLessEqual(width, 40, repr(line))

    def test_r10_previous_date_is_explicit(self):
        snapshot = make_combined_snapshot(1, date="2026-09-08")
        header = views.header_line(
            snapshot, snapshot["web"], today="2026-09-09")
        self.assertIn("previous", header)


@unittest.skipUnless(importlib.util.find_spec("textual"), "requires textual")
class TestV3G0AdapterBaseline(unittest.TestCase):
    def test_r09_airline_page_search_is_reachable(self):
        async def scenario():
            from hkg_flight.terminal.textual_app import FlightBoardApp
            temp_dir = "/tmp/hkg-flight-v3-g0-airline-{}".format(id(self))
            cache = CacheSystem(cache_dir=temp_dir)
            api = MagicMock()
            api.fetch_flights.return_value = []
            api.fetch_airlines_meta.return_value = {
                "airlines": [{"code": "CX", "description": ["Cathay"]}],
                "source": "api", "ok": True, "error": None}
            session = Session(cache=cache, api=api,
                              alert_manager=AlertManager(cache=cache), no_poll=True)
            session.poller.refresh_today()
            app = FlightBoardApp(session, color=False)
            try:
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    await pilot.press("6")
                    await pilot.pause()
                    await pilot.press("slash")
                    await pilot.pause()
                    self.assertEqual(session.state.current, "airlines")
                    self.assertEqual(session.state.focus, "search")
            finally:
                session.close()
                shutil.rmtree(temp_dir, ignore_errors=True)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
