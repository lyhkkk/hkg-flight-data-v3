"""
HKG Flight Data v3 - Terminal Session.

The session is the single owner of the poller, the web server toggle and the
airline loader. The UI layer (Textual or plain) only reads snapshots and posts
commands; it never starts threads, stops servers or touches the API.
"""

import threading

from .state import AppState, dispatch, reconcile
from .presenter import (
    FLIGHT_PAGES,
    ALERTS,
    AIRLINES,
    visible_rows,
    alert_rows,
    airline_rows,
)
from ..poller import Poller
from ..utils import log


WEB_OFF = "off"
WEB_ON = "on"
WEB_ERROR = "error"


class Session:
    """Owns one poller, one web server, one airline loader, one UI state."""

    def __init__(self, cache=None, api=None, alert_manager=None,
                 port=8080, no_poll=False, poll_interval=30, close_timeout=2.0):
        self.cache = cache
        self.api = api
        self.alert_manager = alert_manager
        self.port = port
        self.poller = Poller(
            cache=cache, api=api, alert_manager=alert_manager,
            poll_interval=poll_interval, enabled=not no_poll,
        )

        self.web_server = None
        self._web_status = WEB_OFF
        self._web_error = None
        self._web_lock = threading.RLock()

        self._airlines = []
        self._airlines_source = "none"
        self._airlines_error = None
        self._airlines_loaded = False
        self._airlines_revision = 0
        self._airlines_lock = threading.Lock()

        self.state = AppState()
        self._closed = False
        self.close_timeout = close_timeout

    # -- lifecycle -------------------------------------------------------
    def start(self):
        """Start the poller (non-blocking) and load airlines once."""
        if self._closed:
            return
        self.poller.start()
        if self.api is not None:
            threading.Thread(
                target=self._load_airlines, name="airlines", daemon=True).start()

    def _load_airlines(self):
        """Fetch airline metadata once and publish it (never raises)."""
        try:
            meta = self.api.fetch_airlines_meta()
        except Exception as exc:
            meta = {"airlines": [], "source": "none", "error": str(exc)}
        with self._airlines_lock:
            if self._closed:
                return
            self._airlines = list(meta.get("airlines", []))
            self._airlines_source = meta.get("source", "none")
            self._airlines_error = meta.get("error")
            self._airlines_loaded = True
            self._airlines_revision += 1

    def request_refresh(self):
        """Forward a manual refresh request to the poller."""
        return self.poller.request_refresh()

    def toggle_web(self):
        """Start or stop the owned web server; returns the new status.

        Honest about failure: a busy port reports ``error``, never a false
        ``on``. Binding is synchronous, so there is no in-between state to
        publish.
        """
        with self._web_lock:
            if self._closed:
                return self._web_status
            if self.web_server is None:
                from ..web import WebServer
                self.web_server = WebServer(
                    self.poller, self.api, self.alert_manager, port=self.port)

            if self._web_status == WEB_ON:
                try:
                    self.web_server.stop()
                except Exception as exc:
                    log(f"Web stop failed: {exc}")
                self._web_status, self._web_error = WEB_OFF, None
                return self._web_status

            try:
                started, error = bool(self.web_server.start()), None
            except Exception as exc:
                started, error = False, str(exc)

            if started:
                self._web_status, self._web_error = WEB_ON, None
            else:
                self._web_status = WEB_ERROR
                self._web_error = error or f"port {self.port} unavailable"
            return self._web_status

    # -- reads -----------------------------------------------------------
    def flights_snapshot(self):
        return self.poller.snapshot()

    def alerts_snapshot(self):
        if self.alert_manager is None:
            return {"revision": 0, "alerts": []}
        return self.alert_manager.snapshot()

    def airlines_snapshot(self):
        with self._airlines_lock:
            return {
                "revision": self._airlines_revision,
                "airlines": list(self._airlines),
                "source": self._airlines_source,
                "error": self._airlines_error,
                "loaded": self._airlines_loaded,
            }

    def web_status(self):
        return self._web_status, self._web_error, self.port

    def snapshot(self):
        """Combined read-only view: flights + alerts + airlines + web."""
        return {
            "flights": self.flights_snapshot(),
            "alerts": self.alerts_snapshot(),
            "airlines": self.airlines_snapshot(),
            "web": {"status": self._web_status, "error": self._web_error, "port": self.port},
        }

    def latest_revision(self):
        """Cheap change token the UI polls; builds no snapshot, copies nothing."""
        alerts_rev = self.alert_manager.alerts_revision() if self.alert_manager else 0
        with self._airlines_lock:
            airlines_rev = self._airlines_revision
        return (self.poller.revision(), alerts_rev, airlines_rev, self._web_status)

    # -- UI projection ---------------------------------------------------
    def rows_for(self, page_name):
        """Visible rows for a page under the current UI state."""
        page = self.state.pages.get(page_name)
        if page is None:
            return []
        if page_name in FLIGHT_PAGES:
            return visible_rows(
                self.flights_snapshot(), page_name,
                search_text=page.search_text,
                airline=page.airline_filter,
                status=page.status_filter,
            )
        if page_name == ALERTS:
            return alert_rows(self.alerts_snapshot()["alerts"], page.search_text)
        if page_name == AIRLINES:
            return airline_rows(self.airlines_snapshot()["airlines"], page.search_text)
        return []

    def handle(self, action):
        """Reduce one UI action and execute any side-effect commands it yields."""
        rows = self.rows_for(self.state.current)
        self.state, commands = dispatch(self.state, rows, action)
        for command in commands:
            if command == "refresh":
                self.request_refresh()
            elif command == "web_toggle":
                self.toggle_web()
            elif command == "quit":
                self.close()
        return commands

    def reconcile(self):
        """Re-clamp selection against the current rows (refresh, filter, page)."""
        reconcile(self.state, self.rows_for(self.state.current))

    # -- cleanup ---------------------------------------------------------
    def close(self):
        """Idempotent shutdown of everything this session owns."""
        with self._web_lock:
            if self._closed:
                return
            self._closed = True

        if self.poller is not None:
            try:
                self.poller.stop(self.close_timeout)
            except Exception as exc:
                log(f"Poller stop failed: {exc}")

        if self.web_server is not None:
            try:
                self.web_server.stop()
            except Exception as exc:
                log(f"Web stop failed: {exc}")
            self._web_status, self._web_error = WEB_OFF, None
