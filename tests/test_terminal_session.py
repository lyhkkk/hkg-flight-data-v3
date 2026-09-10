"""Session: owns the poller, the web toggle and the airline loader."""

import tempfile
import time
import unittest

from hkg_flight.alerts import AlertManager
from hkg_flight.cache import CacheSystem
from hkg_flight.terminal.presenter import DEPARTURES, ARRIVALS
from hkg_flight.terminal.session import Session, WEB_ERROR, WEB_OFF, WEB_ON
from hkg_flight.utils import today_str

TODAY = today_str()


def raw_payload():
    return [
        {"arrival": False, "cargo": False, "date": TODAY, "list": [
            {"flight": [{"airline": "CPA", "no": "CX 759"}], "time": "08:40",
             "status": "Boarding", "gate": "63", "terminal": "T1", "destination": ["NRT"]},
            {"flight": [{"airline": "HKE", "no": "UO 612"}], "time": "09:15",
             "status": "Delayed", "gate": "205", "terminal": "T1", "destination": ["KIX"]},
        ]},
        {"arrival": True, "cargo": False, "date": TODAY, "list": [
            {"flight": [{"airline": "CPA", "no": "CX 100"}], "time": "07:00",
             "status": "Landed 06:52", "stand": "W63", "hall": "A", "baggage": "12",
             "terminal": "T1", "origin": ["SYD"]},
        ]},
    ]


class FakeAPI:
    def __init__(self, raw=None, fail=False, fail_airlines=False):
        self.raw = raw
        self.fail = fail
        self.fail_airlines = fail_airlines
        self.airlines_calls = 0

    def fetch_flights(self, date_str):
        if self.fail:
            raise RuntimeError("offline")
        return self.raw

    def fetch_airlines_meta(self):
        self.airlines_calls += 1
        if self.fail_airlines:
            raise RuntimeError("airlines offline")
        return {"airlines": [{"code": "CX", "description": ["Cathay"]}],
                "source": "api", "ok": True, "error": None}


def make_session(raw=None, fail=False, **kw):
    cache = CacheSystem(tempfile.mkdtemp())
    api = FakeAPI(raw, fail)
    session = Session(cache=cache, api=api, alert_manager=AlertManager(cache), **kw)
    return session, api


class TestProjection(unittest.TestCase):
    def setUp(self):
        self.session, _ = make_session(raw_payload())
        self.session.poller.refresh_today()

    def tearDown(self):
        self.session.close()

    def test_rows_for_each_page(self):
        self.assertEqual(len(self.session.rows_for(DEPARTURES)), 2)
        self.assertEqual(len(self.session.rows_for(ARRIVALS)), 1)
        self.assertEqual(self.session.rows_for("unknown-page"), [])

    def test_snapshot_shape(self):
        snap = self.session.snapshot()
        self.assertEqual(set(snap), {"flights", "alerts", "airlines", "web"})
        self.assertIn("records", snap["flights"])

    def test_latest_revision_is_a_cheap_tuple(self):
        rev = self.session.latest_revision()
        self.assertEqual(len(rev), 4)
        self.assertIsInstance(rev[0], int)


class TestHandleAndReconcile(unittest.TestCase):
    def setUp(self):
        self.session, _ = make_session(raw_payload())
        self.session.poller.refresh_today()
        self.session.reconcile()

    def tearDown(self):
        self.session.close()

    def test_handle_executes_side_effects(self):
        commands = self.session.handle({"type": "refresh"})
        self.assertEqual(commands, ["refresh"])

    def test_handle_page_switch_and_move(self):
        self.session.handle({"type": "page", "page": ARRIVALS})
        self.assertEqual(self.session.state.current, ARRIVALS)
        self.session.handle({"type": "move", "direction": "down", "height": 10})
        self.assertEqual(self.session.state.pages[ARRIVALS].selected_index, 0)

    def test_reconcile_after_search(self):
        self.session.state.pages[DEPARTURES].search_text = "UO"
        self.session.reconcile()
        page = self.session.state.pages[DEPARTURES]
        self.assertIn("UO", page.selected_id)


class TestLifecycle(unittest.TestCase):
    def test_start_refreshes_in_background_and_loads_airlines(self):
        session, api = make_session(raw_payload())
        try:
            session.start()
            deadline = time.time() + 5
            while session.poller.revision() == 0 and time.time() < deadline:
                time.sleep(0.02)
            self.assertGreater(session.poller.revision(), 0)
            deadline = time.time() + 5
            while not session.airlines_snapshot()["loaded"] and time.time() < deadline:
                time.sleep(0.02)
            self.assertTrue(session.airlines_snapshot()["loaded"])
            self.assertEqual(len(session.airlines_snapshot()["airlines"]), 1)
        finally:
            session.close()

    def test_close_is_idempotent(self):
        session, _ = make_session(raw_payload())
        session.close()
        self.assertIsNone(session.close())

    def test_refresh_after_close_is_rejected(self):
        session, _ = make_session(raw_payload())
        session.close()
        self.assertEqual(session.request_refresh(), "closed")

    def test_no_poll_disables_timed_refresh_but_still_refreshes_once(self):
        session, _ = make_session(raw_payload(), no_poll=True)
        try:
            session.start()
            deadline = time.time() + 5
            while session.poller.revision() == 0 and time.time() < deadline:
                time.sleep(0.02)
            self.assertGreater(session.poller.revision(), 0)
            self.assertFalse(session.poller.enabled)
        finally:
            session.close()


class TestWebToggle(unittest.TestCase):
    def test_off_on_off(self):
        session, _ = make_session(raw_payload(), port=18091)
        try:
            self.assertEqual(session.web_status()[0], WEB_OFF)
            self.assertEqual(session.toggle_web(), WEB_ON)
            self.assertEqual(session.toggle_web(), WEB_OFF)
        finally:
            session.close()

    def test_busy_port_reports_error_never_on(self):
        holder, _ = make_session(raw_payload(), port=18092)
        other, _ = make_session(raw_payload(), port=18092)
        try:
            self.assertEqual(holder.toggle_web(), WEB_ON)
            self.assertEqual(other.toggle_web(), WEB_ERROR)
            self.assertNotEqual(other.web_status()[0], WEB_ON)
        finally:
            holder.close()
            other.close()

    def test_toggle_after_close_is_inert(self):
        session, _ = make_session(raw_payload(), port=18093)
        session.close()
        self.assertEqual(session.toggle_web(), WEB_OFF)


class TestAirlinesFailure(unittest.TestCase):
    def test_airlines_error_is_surfaced(self):
        cache = CacheSystem(tempfile.mkdtemp())
        session = Session(cache=cache, api=FakeAPI(None, fail_airlines=True),
                          alert_manager=AlertManager(cache))
        try:
            session.start()
            deadline = time.time() + 5
            while not session.airlines_snapshot()["loaded"] and time.time() < deadline:
                time.sleep(0.02)
            snap = session.airlines_snapshot()
            self.assertTrue(snap["loaded"])
            self.assertEqual(snap["airlines"], [])
            self.assertIsNotNone(snap["error"])
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
