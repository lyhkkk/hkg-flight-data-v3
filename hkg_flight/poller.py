"""
HKG Flight Data v3 - Poller Module
Background polling for flight data updates.
"""

import threading
import time
from datetime import datetime

from .utils import log, normalize_flights


class Poller(object):
    """
    Background poller for flight data.
    Automatically refreshes data at regular intervals.
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
        self._lock = threading.Lock()
        self.today_records = []
        self.last_update = None

    def start(self):
        """Start the background poller."""
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return

        # Do an initial refresh before starting background thread
        try:
            self.refresh_today()
        except Exception as exc:
            log("Initial refresh error: {}".format(exc))

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log("Poller started")

    def stop(self):
        """Stop the background poller."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log("Poller stopped")

    def _run(self):
        """Main polling loop."""
        while not self._stop_event.is_set():
            try:
                self.refresh_today()
            except Exception as exc:
                log("Poll error: {}".format(exc))

            # Wait for next poll or stop event
            self._stop_event.wait(self.poll_interval)

    def get_today(self):
        """Get today's flights (arrivals and departures)."""
        return self.today_records

    def consume_new_alert_flag(self):
        """Consume and return the new alert flag."""
        if self.alert_manager:
            return self.alert_manager.consume_new_flag()
        return False

    def refresh_today(self):
        """Refresh today's flight data."""
        from .utils import today_str

        date_str = today_str()
        raw_data = self.api.fetch_flights(date_str)

        if raw_data is None:
            # Use cache as fallback
            if self.cache:
                cached = self.cache.read_flights(date_str)
                if cached:
                    raw_data = cached
                    log("Using cached data for {}".format(date_str))

        if raw_data is None:
            log("No data available for {}".format(date_str))
            return []

        new_records = normalize_flights(raw_data)

        # Detect changes and generate alerts
        if self.alert_manager and self.today_records:
            old_map = {r.get("key"): r for r in self.today_records}
            new_map = {r.get("key"): r for r in new_records}

            for key, new_rec in new_map.items():
                old_rec = old_map.get(key)
                if old_rec:
                    self.alert_manager.process_flight(old_rec, new_rec)

        with self._lock:
            self.today_records = new_records
            self.last_update = datetime.now()

        log("Refreshed {} flights for {}".format(len(new_records), date_str))
        return new_records

    @staticmethod
    def _make_snapshot(rec, now):
        """Create a state snapshot for change detection."""
        return {
            "key": rec.get("key", ""),
            "flight_number": rec.get("flight_number", ""),
            "date": rec.get("date", ""),
            "time": rec.get("time", ""),
            "type": rec.get("type", ""),
            "status": rec.get("status", ""),
            "gate": rec.get("gate", ""),
            "stand": rec.get("stand", ""),
            "last_seen": now.isoformat(timespec="seconds"),
        }

    @staticmethod
    def _snapshot_changed(old, new):
        """Check if relevant fields changed."""
        fields = ["gate", "stand", "status", "time"]
        for field in fields:
            if old.get(field) != new.get(field):
                return True
        return False
