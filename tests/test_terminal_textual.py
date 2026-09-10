"""
Textual interaction tests (enhanced environment only).

These run headless via ``App.run_test``. They are skipped when Textual is not
installed so the module stays importable in the base (3.7) environment, where
``test*`` discovery still loads it.
"""

import asyncio
import importlib.util
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from hkg_flight.cache import CacheSystem
from hkg_flight.alerts import AlertManager
from hkg_flight.terminal.session import Session
from tests.fixtures.terminal.data import make_flights, make_airlines

_TEXTUAL_AVAILABLE = importlib.util.find_spec("textual") is not None


def make_raw(records):
    entries = []
    for rec in records:
        is_arrival = rec.get("type") == "arrival"
        origin = rec.get("origin", "").split("|") if rec.get("origin") else []
        destination = rec.get("destination", "").split("|") if rec.get("destination") else []
        entries.append({
            "arrival": is_arrival,
            "cargo": False,
            "date": rec.get("date", ""),
            "list": [{
                "flight": [{"airline": rec.get("airline_code", ""), "no": rec.get("flight_number", "")}],
                "time": rec.get("time", ""),
                "status": rec.get("status", ""),
                "origin": origin,
                "destination": destination,
                "terminal": rec.get("terminal", ""),
                "gate": rec.get("gate", ""),
                "stand": rec.get("stand", ""),
                "aisle": rec.get("aisle", ""),
                "hall": rec.get("hall", ""),
                "baggage": rec.get("belt", ""),
            }],
        })
    return entries


def build_session(flights=None):
    temp_dir = tempfile.mkdtemp()
    cache = CacheSystem(cache_dir=temp_dir)
    api = MagicMock()
    api.fetch_flights.return_value = make_raw(flights or [])
    api.fetch_airlines_meta.return_value = {
        "airlines": make_airlines(8), "source": "api", "ok": True, "error": None}
    alert_manager = AlertManager(cache=cache)
    session = Session(cache=cache, api=api, alert_manager=alert_manager, no_poll=True)
    session.poller.refresh_today()
    return session, temp_dir


def _run(scenario):
    def runner():
        asyncio.run(scenario())
    return runner


@unittest.skipUnless(_TEXTUAL_AVAILABLE, "requires textual")
class TestTextualInteraction(unittest.TestCase):
    def test_pages_switch_via_digit_keys(self):
        def scenario():
            from hkg_flight.terminal.textual_app import FlightBoardApp
            session, tmp = build_session(make_flights(30))
            app = FlightBoardApp(session, color=False)
            async def body():
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    self.assertEqual(session.state.current, "departures")
                    await pilot.press("2")
                    await pilot.pause()
                    self.assertEqual(session.state.current, "arrivals")
                    await pilot.press("5")
                    await pilot.pause()
                    self.assertEqual(session.state.current, "alerts")
            try:
                asyncio.run(body())
            finally:
                session.close()
                shutil.rmtree(tmp, ignore_errors=True)
        scenario()

    def test_search_typing_does_not_swallow_digits_wq(self):
        def scenario():
            from hkg_flight.terminal.textual_app import FlightBoardApp
            session, tmp = build_session(make_flights(30))
            app = FlightBoardApp(session, color=False)
            async def body():
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    await pilot.press("slash")
                    await pilot.pause()
                    self.assertEqual(session.state.focus, "search")
                    for key in "cx261wq":
                        await pilot.press(key)
                    await pilot.pause()
                    self.assertEqual(session.state.pages["departures"].search_text.lower(), "cx261wq")
                    self.assertEqual(session.state.current, "departures")
                    self.assertEqual(session.web_status()[0], "off")
            try:
                asyncio.run(body())
            finally:
                session.close()
                shutil.rmtree(tmp, ignore_errors=True)
        scenario()

    def test_escape_cancels_search_edit(self):
        def scenario():
            from hkg_flight.terminal.textual_app import FlightBoardApp
            session, tmp = build_session(make_flights(30))
            app = FlightBoardApp(session, color=False)
            async def body():
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    await pilot.press("slash")
                    await pilot.pause()
                    await pilot.press("c")
                    await pilot.press("x")
                    await pilot.pause()
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertEqual(session.state.focus, "list")
                    self.assertEqual(session.state.pages["departures"].search_text, "")
            try:
                asyncio.run(body())
            finally:
                session.close()
                shutil.rmtree(tmp, ignore_errors=True)
        scenario()

    def test_enter_opens_detail_and_escape_closes(self):
        def scenario():
            from hkg_flight.terminal.textual_app import FlightBoardApp
            session, tmp = build_session(make_flights(30))
            app = FlightBoardApp(session, color=False)
            async def body():
                async with app.run_test(size=(120, 30)) as pilot:
                    await pilot.pause()
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertTrue(session.state.detail_id)
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertIsNone(session.state.detail_id)
            try:
                asyncio.run(body())
            finally:
                session.close()
                shutil.rmtree(tmp, ignore_errors=True)
        scenario()

    def test_q_quits(self):
        def scenario():
            from hkg_flight.terminal.textual_app import FlightBoardApp
            session, tmp = build_session(make_flights(30))
            app = FlightBoardApp(session, color=False)
            async def body():
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    await pilot.press("q")
                    await pilot.pause()
            try:
                asyncio.run(body())
            finally:
                session.close()
                shutil.rmtree(tmp, ignore_errors=True)
        scenario()


if __name__ == "__main__":
    unittest.main(verbosity=2)
