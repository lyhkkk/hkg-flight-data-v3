"""
HKG Flight Data v3 - Poller.

One worker thread refreshes today's flights on an interval and on demand, then
publishes an immutable snapshot. Readers always see a complete, consistent
snapshot; a refresh never mutates data a caller already received.

Concurrency model, stated plainly: there is exactly **one writer** (the worker
thread), and ``_refresh`` never runs concurrently with itself. A manual request
that arrives mid-refresh is reported as ``already_running`` rather than queued,
so the refresh slot can never be double-claimed. That is the whole story - no
generation counters, no late-result reordering, because there is no second
writer to reorder against.

Records are *published, never mutated*: ``normalize_flights`` builds a fresh
list of fresh dicts each cycle and nothing writes to it afterwards, so a
snapshot only needs a shallow list copy to stay safe.
"""

import threading
from datetime import datetime

from .utils import log, normalize_flights, today_str


# A snapshot older than this (seconds) is reported as STALE by the UI.
STALE_AFTER_FACTOR = 2
STALE_AFTER_FLOOR = 60


class Poller:
    """Background refresher that publishes an atomic flight snapshot."""

    def __init__(self, cache=None, api=None, alert_manager=None,
                 poll_interval=30, enabled=True):
        self.cache = cache
        self.api = api
        self.alert_manager = alert_manager
        self.poll_interval = poll_interval
        self.enabled = enabled

        self._cond = threading.Condition()
        self._thread = None
        self._closed = False
        self._refreshing = False
        self._pending = False

        self._records = []
        self._meta = {
            "revision": 0,
            "records_date": "",
            "source": "none",
            "last_attempt_at": None,
            "last_api_success_at": None,
            "cache_saved_at": None,
            "last_error": None,
            "polling_enabled": enabled,
        }

    # -- lifecycle -------------------------------------------------------
    def start(self, blocking=False):
        """Start the worker.

        ``blocking=True`` performs the first refresh on the calling thread
        before the worker starts (used by ``web``, which wants data ready);
        ``blocking=False`` returns immediately and refreshes on the worker.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        if self._closed:
            return
        if blocking:
            self._refresh()
        self._thread = threading.Thread(
            target=self._run, args=(not blocking,), name="poller", daemon=True)
        self._thread.start()
        log("Poller started")

    def stop(self, timeout=5.0):
        """Stop the worker; True when it terminated within ``timeout``.

        Idempotent: the second and later calls are no-ops.
        """
        with self._cond:
            first_call = not self._closed
            self._closed = True
            self._cond.notify_all()
        if not first_call:
            return True
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                log(f"Poller did not stop within {timeout} seconds")
                return False
        log("Poller stopped")
        return True

    def request_refresh(self):
        """Ask for a refresh: ``accepted`` / ``already_running`` / ``closed``."""
        with self._cond:
            if self._closed:
                return "closed"
            if self._refreshing or self._pending:
                return "already_running"
            self._pending = True
            self._cond.notify_all()
            return "accepted"

    def _run(self, first_refresh):
        if first_refresh:
            self._refresh()
        while True:
            with self._cond:
                if self._closed:
                    return
                # A pending manual request skips the wait entirely; otherwise
                # sleep for the interval (or block forever when polling is off).
                if not self._pending:
                    self._cond.wait(self.poll_interval if self.enabled else None)
                if self._closed:
                    return
                self._pending = False
            self._refresh()

    # -- refresh ---------------------------------------------------------
    def refresh_today(self):
        """Refresh synchronously on the calling thread; returns the records."""
        self._refresh()
        with self._cond:
            return list(self._records)

    def _refresh(self):
        """One full cycle: fetch, normalize, diff for alerts, publish."""
        with self._cond:
            if self._closed:
                return
            self._refreshing = True

        try:
            attempt_at = datetime.now().isoformat(timespec="seconds")
            date_str = today_str()
            records, source, error, api_ok = self._load(date_str)

            with self._cond:
                if self._closed:
                    return
                previous = self._records
                self._publish_locked(date_str, records, source, error, api_ok, attempt_at)

            # Alert detection runs outside the lock against the previous
            # baseline. It only sees records, never the live snapshot.
            if records is not None and self.alert_manager is not None:
                self.alert_manager.retain_date(date_str)
                if previous:
                    old_map = {r.get("key"): r for r in previous}
                    for new_rec in records:
                        old_rec = old_map.get(new_rec.get("key"))
                        if old_rec is not None:
                            self.alert_manager.process_flight(old_rec, new_rec)
        except Exception as exc:
            log(f"Refresh error: {exc}")
            with self._cond:
                self._meta = {**self._meta, "last_error": str(exc)}
        finally:
            with self._cond:
                self._refreshing = False

    def _load(self, date_str):
        """Fetch today's data, falling back to cache then to memory.

        Returns ``(records|None, source, error, api_ok)``. ``records is None``
        means no new data was obtained and the previous snapshot stands.
        """
        raw = None
        error = None
        api_ok = False
        try:
            raw = self.api.fetch_flights(date_str)
            if raw is not None:
                api_ok = True
        except Exception as exc:
            error = str(exc)
            log(f"Refresh error: {exc}")

        if raw is None and self.cache is not None:
            try:
                raw = self.cache.read_flights(date_str)
            except Exception:
                raw = None
            if raw is not None:
                log(f"Using cached data for {date_str}")
                return normalize_flights(raw), "cache", error, api_ok

        if raw is None:
            with self._cond:
                have_records = bool(self._meta.get("records_date"))
            return None, ("memory" if have_records else "none"), error or "api_failed", api_ok

        return normalize_flights(raw), "api", error, api_ok

    def _publish_locked(self, date_str, records, source, error, api_ok, attempt_at):
        """Install a new snapshot. Caller holds the lock."""
        meta = dict(self._meta)
        meta["revision"] = meta.get("revision", 0) + 1
        meta["last_attempt_at"] = attempt_at
        meta["last_error"] = error
        meta["source"] = source
        meta["polling_enabled"] = self.enabled
        # Only a cache-sourced snapshot has a cache timestamp to report.
        meta["cache_saved_at"] = self._cache_mtime(date_str) if source == "cache" else None

        if api_ok:
            meta["last_api_success_at"] = attempt_at

        if records is not None:
            self._records = records
            meta["records_date"] = date_str

        self._meta = meta

    def _cache_mtime(self, date_str):
        if self.cache is None:
            return None
        try:
            return self.cache.flight_mtime(date_str)
        except Exception:
            return None

    # -- reads -----------------------------------------------------------
    def snapshot(self):
        """Atomic read-only view: health metadata + the record list."""
        with self._cond:
            snap = dict(self._meta)
            snap["records"] = list(self._records)
            snap["refreshing"] = self._refreshing
        return snap

    @property
    def today_records(self):
        """Shallow copy of today's records (records themselves are immutable)."""
        with self._cond:
            return list(self._records)

    def get_today(self):
        return self.today_records

    def revision(self):
        """Cheap change detector for UIs that poll frequently."""
        with self._cond:
            return self._meta.get("revision", 0)
