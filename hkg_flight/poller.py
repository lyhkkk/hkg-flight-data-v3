"""
HKG Flight Data v3 - Poller Module
Background polling for flight data updates.

The poller owns one worker thread, one atomic defensive snapshot, and the
alert-change baseline. Readers never receive the internal record list; every
public read returns a copy, and the snapshot is deep-copied once at publish
time so background refreshes can never mutate data a caller already received.
"""

import copy
import threading
from datetime import datetime

from .utils import log, normalize_flights, today_str


class Poller(object):
    """
    Background poller for flight data.

    Provides:
      - ``start()``: synchronous-first start (CLI/web compatibility).
      - ``start_background()``: non-blocking start; exactly one first refresh.
      - ``request_refresh()``: coalesced manual refresh (accepted /
        already_running / closed).
      - ``snapshot()``: atomic read-only flight data + health metadata.
      - ``stop()``: idempotent shutdown with a bounded join.
    """

    def __init__(self, cache=None, api=None, alert_manager=None,
                 poll_interval=30, enabled=True):
        self.cache = cache
        self.api = api
        self.alert_manager = alert_manager
        self.poll_interval = poll_interval
        self.enabled = enabled
        self._thread = None
        self._stop_event = threading.Event()
        self._cond = threading.Condition()
        self._lock = threading.RLock()
        self._closed = False
        self._refreshing = False
        self._refresh_pending = False
        # Refresh ordering: every refresh cycle takes the next ``generation``.
        # ``_published_generation`` is the generation that owns the live
        # snapshot, which is how late, out-of-order or cross-day results are
        # recognised and dropped instead of being published.
        self._generation = 0
        self._published_generation = 0
        self._records = []
        self._snapshot = self._new_snapshot()

    # -- internal ---------------------------------------------------------
    def _new_snapshot(self):
        """Build an empty snapshot dict (never shared with callers)."""
        return {
            "revision": 0,
            "records_date": "",
            "records": [],
            "source": "none",
            "last_attempt_at": None,
            "last_api_success_at": None,
            "cache_saved_at": None,
            "last_error": None,
            "refreshing": False,
            "polling_enabled": self.enabled,
            "next_refresh_at": None,
        }

    def _now(self):
        """Current wall-clock time (isoformat). Test seam for fixed clocks."""
        return datetime.now().isoformat(timespec="seconds")

    def _cache_saved_at(self, date_str):
        """Read the cached flights file mtime; None when unavailable."""
        if self.cache is None:
            return None
        return self.cache.flight_mtime(date_str)

    def _set_refreshing_locked(self, value):
        """Flip the ``refreshing`` flag on the live snapshot (lock held)."""
        if self._snapshot.get("refreshing") == value:
            return
        snapshot = dict(self._snapshot)
        snapshot["refreshing"] = value
        self._snapshot = snapshot

    def _reset_refresh_state(self):
        """Release the refresh slot on every path (lock, then flag)."""
        with self._lock:
            self._refreshing = False
            self._set_refreshing_locked(False)

    def _is_stale_locked(self, generation, date_str, has_records):
        """True when this result must never be published (lock held).

        A result is stale when the poller is closed, when a newer generation
        already owns the live snapshot, or when its request date is older than
        the date already published (midnight rollover).
        """
        if self._closed:
            return True
        if generation < self._published_generation:
            return True
        if has_records and date_str:
            current_date = self._snapshot.get("records_date") or ""
            if current_date and date_str < current_date:
                return True
        return False

    def _claim_publish_locked(self, generation, date_str, has_records):
        """Reserve the publish slot for ``generation`` (lock held).

        Claiming before alert detection is what keeps a late result from
        re-running alert detection: a stale result never reaches the baseline.
        """
        if self._is_stale_locked(generation, date_str, has_records):
            return False
        self._published_generation = generation
        return True

    def _do_refresh(self):
        """
        Perform one refresh cycle and publish a new snapshot revision.

        Network and normalization work happens outside the snapshot lock; the
        publish step (which bumps the revision) holds the lock. Returns the
        normalized records so callers such as ``start`` can stay compatible.

        Every cycle owns a monotonically increasing ``generation`` taken at
        start time, together with the ``date_str`` it requested. The result is
        published only when the poller is still open, no newer generation has
        published in the meantime, and the request date is not older than the
        published one. A discarded result touches nothing: no records, no
        ``records_date``, no revision, no success time and no alert baseline.
        """
        date_str = today_str()
        attempt_at = self._now()
        raw_data = None
        source = None
        last_error = None
        api_success = False
        published = False

        with self._lock:
            if self._closed:
                return list(self._records)
            self._generation += 1
            generation = self._generation
            self._refreshing = True
            self._refresh_pending = False
            snapshot = dict(self._snapshot)
            snapshot["refreshing"] = True
            snapshot["last_attempt_at"] = attempt_at
            self._snapshot = snapshot

        try:
            try:
                raw_data = self.api.fetch_flights(date_str)
                if raw_data is not None:
                    source = "api"
                    api_success = True
            except Exception as exc:
                last_error = "{}".format(exc)
                log("Refresh error: {}".format(exc))

            if raw_data is None and self.cache is not None:
                try:
                    cached = self.cache.read_flights(date_str)
                except Exception:
                    cached = None
                if cached is not None:
                    raw_data = cached
                    source = "cache"
                    log("Using cached data for {}".format(date_str))

            if raw_data is None:
                last_error = last_error or "api_failed"
                with self._lock:
                    have_memory = bool(self._snapshot.get("records_date"))
                source = "memory" if have_memory else "none"
                new_records = None
            else:
                new_records = normalize_flights(raw_data)

            # Publish gate: claim the slot before touching the alert baseline,
            # so a stale or closed refresh never re-runs alert detection.
            with self._lock:
                publishable = self._claim_publish_locked(
                    generation, date_str, new_records is not None)
                old_records = list(self._records) if publishable else []

            # Detect changes and generate alerts against the previous baseline.
            # The comparison runs against the locked copy, never the caller's.
            if publishable and new_records is not None and self.alert_manager is not None:
                if old_records:
                    old_map = {r.get("key"): r for r in old_records}
                    for new_rec in new_records:
                        old_rec = old_map.get(new_rec.get("key"))
                        if old_rec:
                            self.alert_manager.process_flight(old_rec, new_rec)

            with self._lock:
                # Re-check under the lock: the poller may have closed, or a
                # newer generation may have taken the slot, while alerts ran.
                if publishable and not self._closed and \
                        self._published_generation == generation:
                    previous = self._snapshot
                    snapshot = self._new_snapshot()
                    snapshot["revision"] = previous.get("revision", 0) + 1
                    if new_records is not None:
                        snapshot["records"] = copy.deepcopy(new_records)
                        snapshot["records_date"] = date_str
                        snapshot["source"] = source
                    else:
                        snapshot["records"] = list(self._records)
                        snapshot["records_date"] = previous.get("records_date", "")
                        snapshot["source"] = source
                    snapshot["last_attempt_at"] = attempt_at
                    if api_success:
                        snapshot["last_api_success_at"] = attempt_at
                    else:
                        snapshot["last_api_success_at"] = previous.get(
                            "last_api_success_at")
                    if source == "cache":
                        snapshot["cache_saved_at"] = self._cache_saved_at(date_str)
                    snapshot["last_error"] = last_error
                    snapshot["refreshing"] = False
                    snapshot["polling_enabled"] = self.enabled
                    self._records = list(snapshot["records"])
                    self._snapshot = snapshot
                    published = True
        finally:
            # Every path -- success, empty success, cache fallback, error and
            # the closed / stale discard -- releases the refresh slot once.
            self._reset_refresh_state()

        if published and new_records is not None:
            log("Refreshed {} flights for {} (source={})".format(
                len(new_records), date_str, source))
        with self._lock:
            return list(self._records)

    def _refresh_once(self):
        """Worker-side refresh that never lets an exception kill the loop."""
        try:
            self._do_refresh()
        except Exception as exc:
            log("Poll error: {}".format(exc))
            with self._lock:
                snapshot = dict(self._snapshot)
                snapshot["refreshing"] = False
                snapshot["last_error"] = "{}".format(exc)
                self._snapshot = snapshot

    # -- lifecycle --------------------------------------------------------
    def start(self):
        """
        Legacy synchronous-first start (CLI/web compatibility).

        Performs one blocking refresh then starts the background loop. The
        new TUI should use ``start_background`` instead so it never blocks.
        """
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return

        try:
            self.refresh_today()
        except Exception as exc:
            log("Initial refresh error: {}".format(exc))

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log("Poller started")

    def start_background(self):
        """
        Non-blocking start for the new TUI.

        The first refresh happens exactly once on the worker thread; the UI
        shows its shell immediately and consumes the published snapshot.
        """
        if self._thread and self._thread.is_alive():
            return
        if self._closed:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log("Poller started (background)")

    def request_refresh(self):
        """Request one refresh. Returns accepted / already_running / closed.

        The single refresh slot is owned by an in-flight refresh *or* by an
        already pending request, so a duplicate request is coalesced into
        ``already_running`` instead of queueing a second refresh.
        """
        with self._lock:
            if self._closed:
                return "closed"
            if self._refreshing or self._refresh_pending:
                return "already_running"
            self._refresh_pending = True
        with self._cond:
            self._cond.notify_all()
        return "accepted"

    def stop(self):
        """Stop the background poller and report if it did not terminate."""
        with self._lock:
            self._closed = True
            # Every generation issued so far is now stale, so a refresh that
            # is still in flight is dropped instead of published after close.
            self._published_generation = self._generation
            self._stop_event.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                log("Poller did not stop within 5 seconds")
                return False
        log("Poller stopped")
        return True

    def _run(self):
        """Main polling loop: one first refresh, then interval/manual triggers."""
        self._refresh_once()
        with self._cond:
            while not self._stop_event.is_set():
                if self.enabled:
                    self._cond.wait(self.poll_interval)
                else:
                    # --no-poll: only manual requests wake the loop.
                    self._cond.wait()
                if self._stop_event.is_set():
                    break
                self._refresh_pending = False
                self._refresh_once()

    # -- reads ------------------------------------------------------------
    def refresh_today(self):
        """Refresh today's flight data (synchronous, returns records)."""
        return self._do_refresh()

    @property
    def today_records(self):
        """Defensive copy of today's records (read-only by convention)."""
        with self._lock:
            return list(self._records)

    def get_today(self):
        """Get today's flights (defensive copy)."""
        return self.today_records

    def snapshot(self):
        """Return an atomic, read-only snapshot of flights and health metadata.

        The returned dict is freshly constructed; its ``records`` list is the
        publish-time deep copy that the background never mutates afterwards.
        """
        with self._lock:
            snap = dict(self._snapshot)
            snap["records"] = list(self._snapshot.get("records", []))
        return snap

    def consume_new_alert_flag(self):
        """Consume and return the new alert flag."""
        if self.alert_manager:
            return self.alert_manager.consume_new_flag()
        return False
