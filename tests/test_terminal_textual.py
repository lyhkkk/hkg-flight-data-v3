"""Enhanced UI: mounts and drives the shared session.

Skipped when Textual is not installed, so the base suite stays dependency-free.
"""

import asyncio
import importlib.util
import tempfile
import unittest

from hkg_flight.alerts import AlertManager
from hkg_flight.cache import CacheSystem
from hkg_flight.terminal.presenter import DEPARTURES, ARRIVALS, ALERTS
from hkg_flight.terminal.session import Session
from hkg_flight.utils import today_str

HAS_TEXTUAL = importlib.util.find_spec("textual") is not None

if HAS_TEXTUAL:
    from hkg_flight.terminal.textual_app import FlightBoardApp

TODAY = today_str()


def raw_payload(count=30):
    entries = []
    for i in range(count):
        entries.append({
            "arrival": i % 2 == 1, "cargo": False, "date": TODAY,
            "list": [{"flight": [{"airline": "CPA", "no": f"CX {100 + i}"}],
                      "time": f"{i % 24:02d}:{(i * 7) % 60:02d}",
                      "status": "Scheduled",
                      "gate": str(10 + i) if i % 2 == 0 else None,
                      "stand": f"W{10 + i}" if i % 2 == 1 else None,
                      "terminal": "T1", "destination": ["NRT"], "origin": ["SYD"]}],
        })
    return entries


class FakeAPI:
    def fetch_flights(self, date_str):
        return raw_payload()

    def fetch_airlines_meta(self):
        return {"airlines": [{"code": "CX", "description": ["Cathay"]}],
                "source": "api", "ok": True, "error": None}


@unittest.skipUnless(HAS_TEXTUAL, "Textual is not installed")
class TestTextualApp(unittest.TestCase):
    def setUp(self):
        cache = CacheSystem(tempfile.mkdtemp())
        self.session = Session(cache=cache, api=FakeAPI(),
                               alert_manager=AlertManager(cache), no_poll=True)
        self.session.poller.refresh_today()
        self.session.reconcile()

    def tearDown(self):
        self.session.close()

    def test_mounts_and_renders(self):
        async def scenario():
            app = FlightBoardApp(self.session)
            async with app.run_test() as pilot:
                await pilot.pause()
                self.assertTrue(app.query("#header"))
                self.assertTrue(app.query("#body"))

        asyncio.run(scenario())

    def test_page_keys_switch_pages(self):
        async def scenario():
            app = FlightBoardApp(self.session)
            async with app.run_test() as pilot:
                await pilot.press("2")
                self.assertEqual(self.session.state.current, ARRIVALS)
                await pilot.press("5")
                self.assertEqual(self.session.state.current, ALERTS)
                await pilot.press("1")
                self.assertEqual(self.session.state.current, DEPARTURES)

        asyncio.run(scenario())

    def test_navigation_keys_move_the_selection(self):
        async def scenario():
            app = FlightBoardApp(self.session)
            async with app.run_test() as pilot:
                await pilot.press("down")
                await pilot.press("down")
                self.assertEqual(self.session.state.pages[DEPARTURES].selected_index, 2)

        asyncio.run(scenario())

    def test_help_overlay_toggles(self):
        async def scenario():
            app = FlightBoardApp(self.session)
            async with app.run_test() as pilot:
                await pilot.press("question_mark")
                self.assertTrue(self.session.state.help_open)
                await pilot.press("escape")
                self.assertFalse(self.session.state.help_open)

        asyncio.run(scenario())

    def test_search_input_drives_the_shared_state(self):
        async def scenario():
            app = FlightBoardApp(self.session)
            async with app.run_test() as pilot:
                await pilot.press("slash")
                await pilot.press("C", "X", "1")
                await pilot.pause()
                self.assertEqual(self.session.state.pages[DEPARTURES].search_text, "CX1")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
