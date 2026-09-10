"""
HKG Flight Data v3 - Alert Manager Module
Manages flight alerts (gate/stand changes).
"""

import copy
import threading
from datetime import datetime


MAX_HISTORY = 500


class AlertManager(object):
    """
    Tracks gate/stand changes and manages alert lifecycle.
    """

    def __init__(self, cache=None):
        self.cache = cache
        self.lock = threading.RLock()
        self._revision = 0
        self._alerts = {"active": [], "history": [], "new_flag": False}
        if cache is not None:
            self._alerts = cache.read_alerts()
            if "new_flag" not in self._alerts:
                self._alerts["new_flag"] = False

    def save(self):
        """Persist alerts to cache, retaining only recent history."""
        with self.lock:
            history = self._alerts.setdefault("history", [])
            if len(history) > MAX_HISTORY:
                del history[:-MAX_HISTORY]
            if self.cache is not None:
                self.cache.write_alerts(self._alerts)

    def active_count(self):
        """Return number of active alerts."""
        with self.lock:
            return len(self._alerts.get("active", []))

    def get_active(self):
        """Return a copy of the active alerts."""
        with self.lock:
            return copy.deepcopy(self._alerts.get("active", []))

    def get_history(self):
        """Return a copy of the historical alerts."""
        with self.lock:
            return copy.deepcopy(self._alerts.get("history", []))

    def alerts_revision(self):
        """Return the monotonic revision counter for the active alert set."""
        with self.lock:
            return self._revision

    def snapshot(self):
        """Return an atomic read-only view of the active alerts.

        Returns a dict with the current ``revision`` and a defensive copy of
        the active alerts. Callers cannot mutate manager state through this.
        """
        with self.lock:
            return {
                "revision": self._revision,
                "alerts": copy.deepcopy(self._alerts.get("active", [])),
            }

    def consume_new_flag(self):
        """Consume and return the new alert flag."""
        with self.lock:
            flag = self._alerts.get("new_flag", False)
            self._alerts["new_flag"] = False
            return flag

    def process_flight(self, old, new):
        """
        Compare old and new flight state, generate alerts for changes.

        Args:
            old: Previous flight state dict
            new: Current flight state dict
        """
        if not old or not new:
            return

        key = new.get("key", "")
        flight_number = new.get("flight_number", "")
        date = new.get("date", "")
        time = new.get("time", "")
        flight_type = new.get("type", "")

        # Check gate change
        old_gate = old.get("gate", "")
        new_gate = new.get("gate", "")
        if old_gate != new_gate and new_gate:
            self._upsert_alert(
                key, flight_number, date, time, flight_type,
                "GATE", old_gate, new_gate, new.get("status", "")
            )

        # Check stand change
        old_stand = old.get("stand", "")
        new_stand = new.get("stand", "")
        if old_stand != new_stand and new_stand:
            self._upsert_alert(
                key, flight_number, date, time, flight_type,
                "STAND", old_stand, new_stand, new.get("status", "")
            )

        # Clear alerts if flight departed/landed/arrived
        status = new.get("status", "").lower()
        if any(s in status for s in ["departed", "landed", "arrived", "cancelled"]):
            self._clear_for_key(key)

    def _upsert_alert(self, key, flight_number, date, time, flight_type,
                      field, old_value, new_value, status):
        """Create or update an alert."""
        with self.lock:
            # Check if alert already exists
            for alert in self._alerts.get("active", []):
                if alert.get("key") == key and alert.get("field") == field:
                    alert["old_value"] = old_value
                    alert["new_value"] = new_value
                    alert["status"] = status
                    alert["raised_at"] = datetime.now().isoformat(timespec="seconds")
                    self._alerts["new_flag"] = True
                    self._revision += 1
                    self.save()
                    return

            # Create new alert
            alert = {
                "key": key,
                "flight_number": flight_number,
                "date": date,
                "time": time,
                "type": flight_type,
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "status": status,
                "raised_at": datetime.now().isoformat(timespec="seconds"),
            }
            self._alerts.setdefault("active", []).append(alert)
            self._alerts["new_flag"] = True
            self._revision += 1
            self.save()

    def _clear_for_key(self, key):
        """Clear all alerts for a specific flight key."""
        with self.lock:
            active = self._alerts.get("active", [])
            to_remove = [a for a in active if a.get("key") == key]
            if to_remove:
                self._alerts["active"] = [a for a in active if a.get("key") != key]
                self._alerts.setdefault("history", []).extend(to_remove)
                self._revision += 1
                self.save()
