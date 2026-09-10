"""
HKG Flight Data v3 - Terminal Session
Session lifecycle, command serialization and snapshot bridging.

The session is the single owner of the poller, the web server toggle and the
airline loader. The UI layer (Textual or plain) only ever reads snapshots and
posts commands; it never starts threads, stops servers or touches the API.
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
WEB_STARTING = "starting"


class Session(object):
    """Owns one poller chain, one web server, one airline loader, one UI state."""

    def __init__(self, cache=None, api=None, alert_manager=None,
                 port=8080, no_poll=False, poll_interval=30,
                 close_timeout=2.0):
        self.cache = cache
        self.api = api
        self.alert_manager = alert_manager
        self.port = port
        self.no_poll = no_poll
        self.poller = Poller(
            cache=cache,
            api=api,
            alert_manager=alert_manager,
            poll_interval=poll_interval,
            enabled=not no_poll,
        )
        self.web_server = None
        self._web_status = WEB_OFF
        self._web_error = None
        self._web_lock = threading.RLock()

        self._airlines = []
        self._airlines_source = "none"
        self._airlines_error = None
        self._airlines_revision = 0
        self._airlines_loaded = False
        self._airlines_lock = threading.Lock()
        # Airline worker ownership: the session holds the handle, the
        # completion event, the worker exception and the generation that gates
        # every publish (success, failure, empty result or retry).
        self._airlines_thread = None
        self._airlines_generation = 0
        self._airlines_done = threading.Event()
        self._airlines_done.set()
        self._airlines_worker_error = None

        self.state = AppState()
        self._closed = False
        self._closed_lock = threading.Lock()
        self.close_timeout = close_timeout
        self._close_results = None

    # -- lifecycle --------------------------------------------------------
    def start(self):
        """Start the poller (background first refresh) and load airlines once."""
        with self._closed_lock:
            if self._closed:
                return None
        self.poller.start_background()
        if self.api is not None:
            self._start_airlines_worker()
        return None

    def _start_airlines_worker(self):
        """Start the owned airline worker under a fresh generation."""
        with self._airlines_lock:
            if self._closed:
                return None
            self._airlines_generation += 1
            generation = self._airlines_generation
            self._airlines_done.clear()
            self._airlines_worker_error = None
            thread = threading.Thread(
                target=self._load_airlines, args=(generation,),
                name="session-airlines", daemon=True)
            self._airlines_thread = thread
        # Started outside the lock; the daemon flag is only a last-resort
        # safety net, close() owns the real bounded join.
        thread.start()
        return thread

    def _publish_airlines(self, generation, meta):
        """Publish airline metadata only through the close/generation gate."""
        with self._airlines_lock:
            if generation is None:
                generation = self._airlines_generation
            if self._closed or generation != self._airlines_generation:
                return False
            self._airlines = list(meta.get("airlines", []))
            self._airlines_source = meta.get("source", "none")
            self._airlines_error = meta.get("error")
            self._airlines_revision += 1
            self._airlines_loaded = True
            return True

    def _load_airlines(self, generation=None):
        """Worker body: fetch once, publish through the gate, never raise."""
        try:
            meta = {"airlines": [], "source": "none", "ok": False, "error": "no_api"}
            try:
                meta = self.api.fetch_airlines_meta()
            except Exception as exc:
                meta = {"airlines": [], "source": "none", "ok": False,
                        "error": "{}".format(exc)}
            return self._publish_airlines(generation, meta)
        except Exception as exc:
            with self._airlines_lock:
                self._airlines_worker_error = "{}".format(exc)
            return False
        finally:
            self._airlines_done.set()

    def airlines_worker_status(self):
        """Observable ownership record for the owned airline worker."""
        with self._airlines_lock:
            thread = self._airlines_thread
            return {
                "generation": self._airlines_generation,
                "running": bool(thread is not None and thread.is_alive()),
                "done": self._airlines_done.is_set(),
                "error": self._airlines_worker_error,
                "thread": thread,
            }

    def request_refresh(self):
        """Forward a manual refresh request to the poller."""
        return self.poller.request_refresh()

    def toggle_web(self):
        """Start or stop the owned web server; return the new status.

        The status is honest: a failed or busy-port start reports ``error``, a
        start in progress reports ``starting``, and a close that lands while a
        start is in flight releases the server instead of reporting ``on``.
        """
        with self._web_lock:
            if self._closed:
                return self._web_status
            if self.web_server is None:
                from ..web import WebServer
                self.web_server = WebServer(self.poller, self.api, self.alert_manager, port=self.port)
            if self._web_status == WEB_ON:
                try:
                    self.web_server.stop()
                except Exception as exc:
                    log("Web stop failed: {}".format(exc))
                self._web_status = WEB_OFF
                self._web_error = None
                return self._web_status
            self._web_status = WEB_STARTING
            self._web_error = None
            server = self.web_server

        # Bind/serve outside the lock; the outcome is finalized under it.
        error = None
        try:
            started = bool(server.start())
        except Exception as exc:
            started = False
            error = "{}".format(exc)

        with self._web_lock:
            if self._closed:
                # Close landed while this start was in flight: release the
                # server now and never report ON.
                try:
                    server.stop()
                except Exception as exc:
                    log("Web stop failed: {}".format(exc))
                self._web_status = WEB_OFF
                self._web_error = None
                return self._web_status
            if started:
                self._web_status = WEB_ON
                self._web_error = None
            else:
                self._web_status = WEB_ERROR
                self._web_error = error or "port {} unavailable".format(self.port)
            return self._web_status

    # -- reads ------------------------------------------------------------
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
        """A cheap tuple the UI can poll to detect any data change."""
        snap = self.snapshot()
        return (
            snap["flights"].get("revision", 0),
            snap["alerts"].get("revision", 0),
            snap["airlines"].get("revision", 0),
        )

    # -- UI projection ----------------------------------------------------
    def rows_for(self, page_name):
        """Visible rows for a page under the current UI state."""
        page = self.state.pages[page_name]
        snap = self.snapshot()
        if page_name in FLIGHT_PAGES:
            return visible_rows(
                snap["flights"], page_name,
                search_text=page.search_text,
                airline=page.airline_filter,
                status=page.status_filter,
            )
        if page_name == ALERTS:
            return alert_rows(snap["alerts"]["alerts"], page.search_text)
        if page_name == AIRLINES:
            return airline_rows(snap["airlines"]["airlines"], page.search_text)
        return []

    def handle(self, action):
        """Reduce one UI action; execute any side-effect commands it yields."""
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

    # -- cleanup ----------------------------------------------------------
    def _join_airlines(self, thread=None):
        """Bounded join of the owned airline worker; True when it released."""
        if thread is None:
            with self._airlines_lock:
                thread = self._airlines_thread
        if thread is None or thread is threading.current_thread():
            return True
        thread.join(self.close_timeout)
        return not thread.is_alive()

    def _stop_web(self):
        """Release the owned web server; True when the status is off."""
        with self._web_lock:
            if self.web_server is not None:
                try:
                    self.web_server.stop()
                except Exception as exc:
                    log("Web stop failed: {}".format(exc))
            if self._web_status != WEB_STARTING:
                # A start still in flight finalizes itself as OFF via the
                # close gate; never overwrite that in-flight state with ON.
                self._web_status = WEB_OFF
                self._web_error = None
            return self._web_status == WEB_OFF

    def close(self):
        """Idempotent shutdown of everything this session owns.

        Order: block new publications first (close gate + airline generation
        bump), then release every owned resource under a bounded wait (poller,
        airline worker, web server), then report the outcome.
        """
        with self._closed_lock:
            if self._closed:
                if self._close_results:
                    return dict(self._close_results)
                return {"closed": True}
            self._closed = True
            self._close_results = {"closed": True}
        results = self._close_results

        # 1. Close gate: from here on no owned worker may publish.
        with self._airlines_lock:
            self._airlines_generation += 1
            thread = self._airlines_thread

        # 2. Release owned resources (each step is bounded and isolated).
        poller_stopped = True
        if self.poller is not None:
            try:
                poller_stopped = self.poller.stop()
            except Exception as exc:
                log("Poller stop failed: {}".format(exc))
                poller_stopped = False
        results["poller_stopped"] = poller_stopped
        results["airlines_joined"] = self._join_airlines(thread)
        results["web_stopped"] = self._stop_web()
        results["closed"] = True
        return dict(results)
