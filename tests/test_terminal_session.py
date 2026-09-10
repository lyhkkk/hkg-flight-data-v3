"""
Session lifecycle tests: web toggle statuses, port conflict, idempotent close,
airline failure metadata, worker ownership and the close gate that discards
late worker results.
"""

import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock

from hkg_flight.cache import CacheSystem
from hkg_flight.alerts import AlertManager
from hkg_flight.terminal.session import (
    Session,
    WEB_OFF,
    WEB_ON,
    WEB_ERROR,
    WEB_STARTING,
)


def wait_for_worker(session, timeout=5.0):
    """Poll the airline worker until it reports completion."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if session.airlines_worker_status()["done"]:
            return True
        time.sleep(0.01)
    return False


class TestSessionWebAndClose(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache = CacheSystem(cache_dir=self.temp_dir)
        self.api = MagicMock()
        self.api.fetch_flights.return_value = []
        self.api.fetch_airlines_meta.return_value = {
            "airlines": [], "source": "api", "ok": True, "error": None}
        self.alert_manager = AlertManager(cache=self.cache)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _session(self, port=0):
        return Session(cache=self.cache, api=self.api,
                       alert_manager=self.alert_manager, port=port, no_poll=True)

    def test_web_toggle_on_then_off(self):
        session = self._session()
        try:
            self.assertEqual(session.toggle_web(), WEB_ON)
            self.assertEqual(session.toggle_web(), WEB_OFF)
        finally:
            session.close()

    def test_web_port_conflict_reports_error_not_on(self):
        first = self._session(port=0)
        first.toggle_web()
        port = first.web_server._server.server_address[1]
        second = self._session(port=port)
        try:
            status = second.toggle_web()
            self.assertEqual(status, WEB_ERROR)
            self.assertEqual(second.web_status()[0], WEB_ERROR)
        finally:
            second.close()
            first.close()

    def test_close_is_idempotent(self):
        session = self._session()
        first = session.close()
        second = session.close()
        self.assertTrue(first["closed"])
        self.assertTrue(second["closed"])

    def test_repeat_close_keeps_results_and_writes_nothing(self):
        session = self._session()
        first = session.close()
        second = session.close()
        # A repeat close must not overwrite the first outcome, publish airline
        # data or resurrect the web server.
        self.assertEqual(first["closed"], second["closed"])
        self.assertEqual(first.get("poller_stopped"), second.get("poller_stopped"))
        self.assertEqual(first.get("web_stopped"), second.get("web_stopped"))
        self.assertFalse(session.airlines_snapshot()["loaded"])
        self.assertEqual(session.web_status()[0], WEB_OFF)

    def test_airline_worker_is_owned_and_observable(self):
        session = self._session()
        try:
            session.start()
            status = session.airlines_worker_status()
            self.assertIsNotNone(status["thread"], "worker handle is not owned")
            self.assertTrue(wait_for_worker(session))
            status = session.airlines_worker_status()
            self.assertTrue(status["done"])
            self.assertFalse(status["running"])
            self.assertIsNone(status["error"])
            snap = session.airlines_snapshot()
            self.assertTrue(snap["loaded"])
            self.assertEqual(snap["source"], "api")
        finally:
            session.close()

    def test_airline_worker_exception_is_observable(self):
        # A non-mapping result makes the publish step itself fail: the worker
        # must stay observable and must not publish anything.
        self.api.fetch_airlines_meta.return_value = "not-a-dict"
        session = self._session()
        try:
            session.start()
            self.assertTrue(wait_for_worker(session))
            status = session.airlines_worker_status()
            self.assertTrue(status["done"])
            self.assertIsNotNone(status["error"])
            self.assertFalse(session.airlines_snapshot()["loaded"])
        finally:
            session.close()

    def test_blocked_airline_worker_is_released_and_cannot_publish(self):
        started = threading.Event()
        release = threading.Event()

        def fetch_airlines():
            started.set()
            self.assertTrue(release.wait(10))
            return {"airlines": [{"code": "CX"}], "source": "api",
                    "ok": True, "error": None}

        self.api.fetch_airlines_meta.side_effect = fetch_airlines
        session = self._session()
        session.start()
        self.assertTrue(started.wait(10), "airline worker never started")
        self.assertTrue(session.airlines_worker_status()["running"])

        began = time.time()
        results = session.close()
        elapsed = time.time() - began
        self.assertTrue(results["closed"])
        # A worker blocked inside the API call cannot be cancelled, so close
        # must stay bounded by close_timeout instead of hanging.
        self.assertLessEqual(elapsed, session.close_timeout + 2.0)
        self.assertFalse(results["airlines_joined"],
                         "blocked worker must not be reported as joined")

        release.set()
        self.assertTrue(wait_for_worker(session))
        snap = session.airlines_snapshot()
        self.assertFalse(snap["loaded"], "late airline result was published")
        self.assertEqual(snap["airlines"], [])
        self.assertEqual(snap["revision"], 0)
        status = session.airlines_worker_status()
        self.assertFalse(status["running"])
        self.assertTrue(status["done"])

    def test_web_close_during_start_never_reports_on(self):
        in_start = threading.Event()
        release = threading.Event()

        class _SlowServer(object):
            def __init__(self):
                self.stopped = False

            def start(self):
                in_start.set()
                release.wait(10)
                return True

            def stop(self):
                self.stopped = True

        session = self._session()
        fake = _SlowServer()
        session.web_server = fake
        starter = threading.Thread(target=session.toggle_web)
        try:
            starter.start()
            self.assertTrue(in_start.wait(10))
            self.assertEqual(session.web_status()[0], WEB_STARTING)
            session.close()
            release.set()
            starter.join(10)
            self.assertFalse(starter.is_alive())
        finally:
            release.set()
            session.close()
        self.assertTrue(fake.stopped, "server started during close was released")
        self.assertEqual(session.web_status()[0], WEB_OFF)
        self.assertNotEqual(session.web_status()[0], WEB_ON)

    def test_toggle_web_after_close_does_not_start(self):
        session = self._session()
        session.close()
        self.assertEqual(session.toggle_web(), WEB_OFF)
        self.assertEqual(session.web_status()[0], WEB_OFF)
        self.assertIsNone(session.web_server)

    def test_web_restart_after_off_reports_on(self):
        session = self._session()
        try:
            self.assertEqual(session.toggle_web(), WEB_ON)
            self.assertEqual(session.toggle_web(), WEB_OFF)
            self.assertEqual(session.toggle_web(), WEB_ON)
            self.assertEqual(session.web_status()[0], WEB_ON)
        finally:
            session.close()
        self.assertEqual(session.web_status()[0], WEB_OFF)

    def test_airline_failure_metadata_visible(self):
        self.api.fetch_airlines_meta.return_value = {
            "airlines": [], "source": "none", "ok": False, "error": "api_failed"}
        session = self._session()
        try:
            session.start()
            session._load_airlines()
            snap = session.airlines_snapshot()
            self.assertFalse(snap["airlines"])
            self.assertEqual(snap["source"], "none")
            self.assertEqual(snap["error"], "api_failed")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
