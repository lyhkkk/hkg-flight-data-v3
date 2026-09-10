"""V3-G0 R10 evidence: rollover, publish ordering and post-close publication.

These tests drive the *real* publish seam (``Poller._do_refresh`` via the
public ``Poller.refresh_today`` / ``Poller.stop`` / ``Session.close`` entry
points). Only the network-facing ``api`` object and the two documented test
seams (``Poller._now`` and the module-level ``today_str`` import) are
substituted, because a wall-clock midnight cannot be awaited in CI.

Nothing in ``hkg_flight`` is modified; failures here are G0 evidence.
"""

import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

import hkg_flight.poller as poller_mod
from hkg_flight.alerts import AlertManager
from hkg_flight.cache import CacheSystem
from hkg_flight.poller import Poller
from hkg_flight.terminal import views
from hkg_flight.terminal.session import Session
from tests.fixtures.terminal.data import make_combined_snapshot


class _Clock(threading.local):
    """Thread-local ``today_str`` / ``_now`` so two in-flight refreshes can
    represent two different wall-clock moments at once."""

    date = "2026-09-09"
    now = "2026-09-09T23:59:00"
    branch = "new"


CLOCK = _Clock()


def _fake_today_str():
    return CLOCK.date


def _raw(date, number, time_str, gate="", status="Scheduled"):
    return [{
        "arrival": False,
        "cargo": False,
        "date": date,
        "list": [{
            "flight": [{"airline": "CX", "no": number}],
            "time": time_str,
            "status": status,
            "gate": gate,
        }],
    }]


class R10Base(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="hkg-v3-g0-r10-")
        self.cache = CacheSystem(cache_dir=self.temp_dir)
        self.alert_manager = AlertManager(cache=self.cache)
        self._orig_today = poller_mod.today_str
        poller_mod.today_str = _fake_today_str

    def tearDown(self):
        poller_mod.today_str = self._orig_today
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _poller(self, api):
        poller = Poller(cache=self.cache, api=api,
                        alert_manager=self.alert_manager, enabled=False)
        poller._now = lambda: CLOCK.now
        return poller


class TestR10MidnightRollover(R10Base):
    """23:59 request returns after midnight: the stale result must not clobber
    the newer date's records, revision, success time or alerts."""

    def test_r10_stale_midnight_result_cannot_overwrite_new_date(self):
        api = MagicMock()
        in_old = threading.Event()
        release_old = threading.Event()

        def fetch(_date):
            if CLOCK.branch == "old":
                in_old.set()
                self.assertTrue(release_old.wait(10))
                return _raw("2026-09-09", "100", "23:50")
            return _raw("2026-09-10", "200", "00:10")

        api.fetch_flights.side_effect = fetch
        poller = self._poller(api)

        def old_runner():
            CLOCK.date = "2026-09-09"
            CLOCK.now = "2026-09-09T23:59:00"
            CLOCK.branch = "old"
            poller.refresh_today()

        def new_runner():
            CLOCK.date = "2026-09-10"
            CLOCK.now = "2026-09-10T00:00:05"
            CLOCK.branch = "new"
            poller.refresh_today()

        old = threading.Thread(target=old_runner, name="old-2359")
        old.start()
        self.assertTrue(in_old.wait(10), "stale refresh never entered fetch")

        new = threading.Thread(target=new_runner, name="new-0000")
        new.start()
        new.join(10)
        self.assertFalse(new.is_alive())

        after_new = poller.snapshot()
        alerts_after_new = self.alert_manager.snapshot()

        release_old.set()
        old.join(10)
        self.assertFalse(old.is_alive())

        final = poller.snapshot()
        alerts_final = self.alert_manager.snapshot()

        # Assertion order matters: the alert baseline is checked first so a
        # stale-publish regression is recorded even when the record assertion
        # above it would already abort the test.
        self.assertEqual(alerts_final["revision"], alerts_after_new["revision"],
                         "stale result mutated the alert baseline")
        self.assertEqual(after_new["records_date"], "2026-09-10")
        self.assertEqual(final["records_date"], "2026-09-10",
                         "stale 2026-09-09 result overwrote the new date")
        self.assertEqual([r["flight_number"] for r in final["records"]], ["200"])
        self.assertEqual(final["last_api_success_at"], after_new["last_api_success_at"],
                         "stale result overwrote last_api_success_at")
        self.assertGreaterEqual(final["revision"], after_new["revision"])


class TestR10PublishOrdering(R10Base):
    """Out-of-order completion: a refresh that started earlier but finished
    later must be discarded in favour of the newer published result."""

    def test_r10_out_of_order_completion_is_discarded(self):
        api = MagicMock()
        in_old = threading.Event()
        release_old = threading.Event()

        def fetch(_date):
            if CLOCK.branch == "old":
                in_old.set()
                self.assertTrue(release_old.wait(10))
                return _raw("2026-09-09", "100", "08:00", gate="1")
            if CLOCK.branch == "base":
                return _raw("2026-09-09", "100", "07:55", gate="1")
            return _raw("2026-09-09", "100", "08:05", gate="2")

        api.fetch_flights.side_effect = fetch
        poller = self._poller(api)

        # Baseline publish so the newer refresh can raise a GATE alert.
        CLOCK.date = "2026-09-09"
        CLOCK.now = "2026-09-09T07:58:00"
        CLOCK.branch = "base"
        poller.refresh_today()
        self.assertEqual(poller.snapshot()["records"][0]["gate"], "1")

        def old_runner():
            CLOCK.date = "2026-09-09"
            CLOCK.now = "2026-09-09T23:59:00"
            CLOCK.branch = "old"
            poller.refresh_today()

        def new_runner():
            CLOCK.date = "2026-09-09"
            CLOCK.now = "2026-09-10T00:00:05"
            CLOCK.branch = "new"
            poller.refresh_today()

        old = threading.Thread(target=old_runner, name="old-late")
        old.start()
        self.assertTrue(in_old.wait(10))

        new = threading.Thread(target=new_runner, name="new-early")
        new.start()
        new.join(10)
        self.assertFalse(new.is_alive())

        after_new = poller.snapshot()
        alerts_after_new = self.alert_manager.snapshot()
        self.assertEqual(after_new["records"][0]["gate"], "2")
        self.assertEqual(after_new["last_api_success_at"], "2026-09-10T00:00:05")

        release_old.set()
        old.join(10)
        self.assertFalse(old.is_alive())

        final = poller.snapshot()
        self.assertEqual(self.alert_manager.snapshot()["revision"],
                         alerts_after_new["revision"],
                         "late result re-ran alert detection")
        self.assertEqual(final["last_api_success_at"], "2026-09-10T00:00:05")
        self.assertEqual(final["records"][0]["gate"], "2",
                         "late out-of-order result was published")


class TestR10ClosedRejectsNewWork(R10Base):
    def test_r10_session_request_refresh_after_close_is_closed(self):
        api = MagicMock()
        api.fetch_flights.return_value = []
        api.fetch_airlines_meta.return_value = {
            "airlines": [{"code": "CX"}], "source": "api", "ok": True, "error": None}
        session = Session(cache=self.cache, api=api,
                          alert_manager=self.alert_manager, no_poll=True)
        session.start()
        session.close()
        self.assertEqual(session.request_refresh(), "closed")

    def test_r10_poller_closed_rejects_new_refresh(self):
        poller = self._poller(MagicMock())
        poller.stop()
        self.assertEqual(poller.request_refresh(), "closed")


class TestR10PreviousDateSemantics(unittest.TestCase):
    def test_r10_previous_date_shows_explicit_date_and_marker(self):
        snapshot = make_combined_snapshot(1, date="2026-09-08")
        header = views.header_line(snapshot, snapshot["web"], today="2026-09-09")
        self.assertIn("2026-09-08", header)
        self.assertIn("previous", header)

    def test_r10_same_date_has_no_previous_marker(self):
        snapshot = make_combined_snapshot(1, date="2026-09-09")
        header = views.header_line(snapshot, snapshot["web"], today="2026-09-09")
        self.assertNotIn("previous", header)


if __name__ == "__main__":
    unittest.main(verbosity=2)
