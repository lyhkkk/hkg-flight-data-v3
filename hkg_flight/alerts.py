"""
HKG Flight Data v3 - Alert Manager.

Tracks gate/stand changes and manages the alert lifecycle:

  gate/stand change detected
    -> alert raised (active set grows, revision advances)
    -> alert persists while the flight is still pending
    -> alert cleared once the flight is boarding/departed/arrived/landed/cancelled

Readers poll ``alerts_revision()``; they never share a mutable flag with the
manager. ``snapshot()`` returns per-alert copies, so the poller thread may keep
updating the live set without disturbing a caller that already read it.
"""

import threading
from datetime import datetime


MAX_HISTORY = 500

# Statuses that end an alert's life.
_CLEARING_STATUSES = ("departed", "landed", "arrived", "cancelled")


class AlertManager:
    """Gate/stand change detection with an active set and a retained history."""

    def __init__(self, cache=None):
        self.cache = cache
        self.lock = threading.RLock()
        self._revision = 0
        self._alerts = {"active": [], "history": []}
        if cache is not None:
            stored = cache.read_alerts()
            self._alerts = {
                "active": stored.get("active", []),
                "history": stored.get("history", []),
            }

    # -- persistence -----------------------------------------------------
    def save(self):
        """Persist alerts, retaining only the most recent history entries."""
        with self.lock:
            history = self._alerts.setdefault("history", [])
            if len(history) > MAX_HISTORY:
                del history[:-MAX_HISTORY]
            if self.cache is not None:
                self.cache.write_alerts(self._alerts)

    # -- reads -----------------------------------------------------------
    def active_count(self):
        with self.lock:
            return len(self._alerts.get("active", []))

    def get_active(self):
        """Copy of the active alerts (each alert is a fresh dict)."""
        with self.lock:
            return [dict(alert) for alert in self._alerts.get("active", [])]

    def get_history(self):
        """Copy of the retained alert history."""
        with self.lock:
            return [dict(alert) for alert in self._alerts.get("history", [])]

    def alerts_revision(self):
        """Monotonic counter that advances whenever the active set changes."""
        with self.lock:
            return self._revision

    def snapshot(self):
        """Atomic read-only view: ``{"revision", "alerts"}``."""
        with self.lock:
            return {
                "revision": self._revision,
                "alerts": [dict(alert) for alert in self._alerts.get("active", [])],
            }

    # -- change detection ------------------------------------------------
    def process_flight(self, old, new):
        """Compare two states of one flight and raise/clear alerts."""
        if not old or not new:
            return

        key = new.get("key", "")
        new_status = str(new.get("status", "")).lower()

        for field in ("gate", "stand"):
            old_value = old.get(field, "")
            new_value = new.get(field, "")
            if old_value != new_value and new_value:
                self._upsert(
                    key=key,
                    flight_number=new.get("flight_number", ""),
                    date=new.get("date", ""),
                    time=new.get("time", ""),
                    flight_type=new.get("type", ""),
                    field=field.upper(),
                    old_value=old_value,
                    new_value=new_value,
                    status=new.get("status", ""),
                )

        if any(s in new_status for s in _CLEARING_STATUSES):
            self._clear_for_key(key)

    def _upsert(self, key, flight_number, date, time, flight_type,
                field, old_value, new_value, status):
        """Create the alert, or refresh it when one already exists."""
        now = datetime.now().isoformat(timespec="seconds")
        with self.lock:
            for alert in self._alerts.get("active", []):
                if alert.get("key") == key and alert.get("field") == field:
                    alert["old_value"] = old_value
                    alert["new_value"] = new_value
                    alert["status"] = status
                    alert["raised_at"] = now
                    self._revision += 1
                    self.save()
                    return

            self._alerts.setdefault("active", []).append({
                "key": key,
                "flight_number": flight_number,
                "date": date,
                "time": time,
                "type": flight_type,
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "status": status,
                "raised_at": now,
            })
            self._revision += 1
            self.save()

    def _clear_for_key(self, key):
        """Move every active alert for ``key`` into the history."""
        with self.lock:
            active = self._alerts.get("active", [])
            cleared = [a for a in active if a.get("key") == key]
            if not cleared:
                return
            self._alerts["active"] = [a for a in active if a.get("key") != key]
            self._alerts.setdefault("history", []).extend(cleared)
            self._revision += 1
            self.save()
