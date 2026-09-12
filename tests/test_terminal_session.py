"""Session: owns the poller, the web toggle and the airline loader."""

import tempfile
import time
import unittest
from datetime import datetime, timedelta

from hkg_flight.alerts import AlertManager
from hkg_flight.cache import CacheSystem
from hkg_flight.terminal.presenter import DEPARTURES, ARRIVALS, ALERTS
from hkg_flight.terminal.session import Session, WEB_ERROR, WEB_OFF, WEB_ON
from hkg_flight.utils import HKT, today_str

TODAY = today_str()


def shift_day(date_str, days):
    """``date_str`` moved by ``days``, in the same YYYY-MM-DD form."""
    year, month, day = (int(part) for part in date_str.split("-"))
    return (datetime(year, month, day, tzinfo=HKT) + timedelta(days=days)).date().isoformat()


def raw_payload(date_str=TODAY):
    return [
        {"arrival": False, "cargo": False, "date": date_str, "list": [
            {"flight": [{"airline": "CPA", "no": "CX 759"}], "time": "08:40",
             "status": "Boarding", "gate": "63", "terminal": "T1", "destination": ["NRT"]},
            {"flight": [{"airline": "HKE", "no": "UO 612"}], "time": "09:15",
             "status": "Delayed", "gate": "205", "terminal": "T1", "destination": ["KIX"]},
        ]},
        {"arrival": True, "cargo": False, "date": date_str, "list": [
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
        self.dates = []

    def fetch_flights(self, date_str):
        self.dates.append(date_str)
        if self.fail:
            raise RuntimeError("offline")
        # ``raw`` is one payload for every date, or a {date: payload} mapping.
        return self.raw.get(date_str) if isinstance(self.raw, dict) else self.raw

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
        self.session.poller.refresh_now()

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
        self.session.poller.refresh_now()
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


class TestSessionClock(unittest.TestCase):
    """The session is what knows the board's clock; the reducer never reads it."""

    @staticmethod
    def at(minutes, day=TODAY):
        hour, minute = divmod(minutes, 60)
        year, month, day_of_month = (int(part) for part in day.split("-"))
        return datetime(year, month, day_of_month, hour, minute, tzinfo=HKT)

    def build(self, minutes=12 * 60, day=TODAY, raw=None):
        session, _ = make_session(
            raw if raw is not None else raw_payload(),
            clock=lambda: self.at(minutes, day))
        session.poller.refresh_now()
        return session

    def top_row(self, session, page_name=DEPARTURES):
        """The record sitting at the top of the viewport."""
        page = session.state.pages[page_name]
        return session.rows_for(page_name)[page.offset]["record"]

    def test_a_fresh_flight_page_parks_on_the_clock(self):
        session = self.build(minutes=8 * 60)
        try:
            session.reanchor()
            page = session.state.pages[DEPARTURES]
            self.assertEqual(self.top_row(session)["time"], "08:40")
            self.assertEqual(page.anchor_minutes, 8 * 60)
            self.assertEqual(page.anchor_date, TODAY)
            self.assertTrue(page.anchor_auto)
        finally:
            session.close()

    def test_a_board_that_is_all_in_the_past_shows_its_tail(self):
        session = self.build(minutes=23 * 60)
        try:
            session.reanchor()
            page = session.state.pages[DEPARTURES]
            self.assertEqual(page.offset, len(session.rows_for(DEPARTURES)) - 1)
        finally:
            session.close()

    def test_the_anchor_parks_on_today_not_on_yesterday(self):
        # 01:30 in the morning: the board carries yesterday as well, and its
        # rows come first. Parking on the clock means today's 08:40, not a
        # flight that left a day ago.
        yesterday = shift_day(TODAY, -1)
        session = self.build(
            minutes=1 * 60 + 30,
            raw={yesterday: raw_payload(yesterday), TODAY: raw_payload(TODAY)})
        try:
            session.reanchor()
            top = self.top_row(session)
            self.assertEqual(top["date"], TODAY)
            self.assertEqual(top["time"], "08:40")
            self.assertEqual(session.state.pages[DEPARTURES].anchor_date, TODAY)
        finally:
            session.close()

    def test_a_page_opened_in_the_small_hours_also_parks_on_today(self):
        # The same rule has to hold for arrivals, which is a different row set.
        yesterday = shift_day(TODAY, -1)
        session = self.build(
            minutes=1 * 60 + 30,
            raw={yesterday: raw_payload(yesterday), TODAY: raw_payload(TODAY)})
        try:
            session.handle({"type": "page", "page": ARRIVALS})
            top = self.top_row(session, ARRIVALS)
            self.assertEqual(top["date"], TODAY)
            self.assertEqual(top["time"], "07:00")
        finally:
            session.close()

    def test_reanchor_leaves_a_pinned_page_alone(self):
        session = self.build(minutes=8 * 60)
        try:
            session.handle({"type": "page", "page": DEPARTURES})
            session.handle({"type": "move", "direction": "down"})
            page = session.state.pages[DEPARTURES]
            before = page.selected_id
            self.assertFalse(page.anchor_auto)
            session.reanchor()
            self.assertEqual(page.selected_id, before)
        finally:
            session.close()

    def test_reanchor_ignores_pages_that_have_no_clock(self):
        session = self.build(minutes=8 * 60)
        try:
            session.handle({"type": "page", "page": ALERTS})
            session.reanchor()
            self.assertIsNone(session.state.pages[ALERTS].anchor_minutes)
        finally:
            session.close()

    def test_anchor_now_reads_the_clock_through_the_session(self):
        session = self.build(minutes=13 * 60)
        try:
            session.handle({"type": "page", "page": DEPARTURES})
            session.handle({"type": "move", "direction": "end"})
            self.assertFalse(session.state.pages[DEPARTURES].anchor_auto)
            session.handle({"type": "anchor_now"})
            page = session.state.pages[DEPARTURES]
            self.assertTrue(page.anchor_auto)
            self.assertEqual(page.anchor_minutes, 13 * 60)
            self.assertEqual(page.anchor_date, TODAY)
        finally:
            session.close()

    def test_switching_pages_anchors_the_page_being_switched_to(self):
        # The anchor must be taken for the page being opened, not the one being
        # left - the two have different clocks only in principle, but the rows
        # are certainly different.
        session = self.build(minutes=8 * 60)
        try:
            session.handle({"type": "page", "page": ARRIVALS})
            page = session.state.pages[ARRIVALS]
            self.assertEqual(self.top_row(session, ARRIVALS)["time"], "07:00")
            self.assertEqual(page.anchor_minutes, 8 * 60)
        finally:
            session.close()

    def test_reconcile_keeps_following_the_clock(self):
        session = self.build(minutes=8 * 60)
        try:
            session.reanchor()
            session.reconcile()
            self.assertEqual(self.top_row(session)["time"], "08:40")
        finally:
            session.close()

    def test_the_poller_and_the_anchor_read_the_same_clock(self):
        # A board whose window and whose anchor disagree would park the
        # viewport on a date the board is not even showing.
        late = self.build(minutes=23 * 60 + 30)
        try:
            snap = late.snapshot()["flights"]
            self.assertEqual(snap["records_dates"], [TODAY, shift_day(TODAY, 1)])
            self.assertEqual(snap["records_date"], TODAY)
        finally:
            late.close()


if __name__ == "__main__":
    unittest.main()
