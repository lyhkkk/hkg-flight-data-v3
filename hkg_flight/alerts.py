"""
HKG Flight Data v3 - Alert Manager.

An alert marks a flight whose gate or stand has moved **away from the value it
was originally assigned**. The first allocation is the baseline, not news:
every normal flight gets a gate, so alerting on it would bury the signal under
hundreds of rows a day. Only a later divergence is an alert:

    N24 -> -         released   (the position was withdrawn)
    N24 -> S47       changed    (moved to a different position)
    N24 -> - -> S47  released then re-assigned -> shown as ``N24 -> S47``

A flight that returns to its baseline (``N24 -> S47 -> N24``) is no longer
divergent, so its alert clears. So does a flight that departs, lands or is
cancelled: its position is no longer actionable.

The manager is written by exactly one thread (the poller) and read by many
(the web handler threads and the UI), so a single lock guards the alert list.
Alerts are stored newest-first and capped at :data:`MAX_ALERTS`.
"""

import threading
from datetime import datetime

from .utils import status_category, today_str


MAX_ALERTS = 500

# Status categories that end a flight's life: its gate/stand stops mattering.
_CLOSED_CATEGORIES = ("departed", "landed", "cancelled")


def _category(rec):
    """Stable status category for a record, tolerating raw status strings."""
    return status_category(rec.get("status_category") or rec.get("status"))


class AlertManager:
    """Gate/stand divergence tracking, newest first."""

    def __init__(self, cache=None):
        self.cache = cache
        self.lock = threading.Lock()
        self._revision = 0
        self._alerts = []
        # (key, field) -> the value the flight was first assigned. In memory
        # only: a restart re-establishes baselines from the first snapshot,
        # which is exactly what the process-local diff model can support.
        self._baseline = {}

        if cache is not None:
            today = today_str()
            self._alerts = [
                a for a in cache.read_alerts() if str(a.get("date", "")) >= today
            ]
            for alert in self._alerts:
                self._baseline[(alert.get("key"), alert.get("field"))] = alert.get("old_value", "")

    # -- reads -----------------------------------------------------------
    def active_count(self):
        with self.lock:
            return len(self._alerts)

    def get_active(self):
        """Copy of the alerts, newest first (each alert is a fresh dict)."""
        with self.lock:
            return [dict(alert) for alert in self._alerts]

    def alerts_revision(self):
        """Monotonic counter that advances whenever the alert set changes."""
        with self.lock:
            return self._revision

    def snapshot(self):
        """Atomic read-only view: ``{"revision", "alerts"}``."""
        with self.lock:
            return {
                "revision": self._revision,
                "alerts": [dict(alert) for alert in self._alerts],
            }

    # -- change detection ------------------------------------------------
    def process_flight(self, old, new):
        """Compare two states of one flight and raise/clear its alerts."""
        if not old or not new:
            return

        key = new.get("key", "")
        if _category(new) in _CLOSED_CATEGORIES:
            self._drop_key(key)
            return

        for field in ("gate", "stand"):
            self._process_field(key, field, old, new)

    def retain_date(self, date_str):
        """Drop alerts that do not belong to ``date_str`` (called per refresh)."""
        if not date_str:
            return
        with self.lock:
            kept = [a for a in self._alerts if a.get("date", "") == date_str]
            if len(kept) == len(self._alerts):
                return
            self._alerts = kept
            self._baseline = {p: v for p, v in self._baseline.items() if p[0].startswith(date_str)}
            self._revision += 1
            payload = [dict(a) for a in self._alerts]
        self._persist(payload)

    def _process_field(self, key, field, old, new):
        """Track one field (gate or stand) of one flight."""
        old_value = str(old.get(field) or "")
        new_value = str(new.get(field) or "")
        if old_value == new_value:
            return

        pair = (key, field.upper())
        baseline = self._baseline.get(pair)

        if baseline is None:
            # No recorded assignment yet: the previous value is the best
            # baseline available, and an empty previous value means this is the
            # first allocation - silent by design.
            if not old_value:
                if new_value:
                    self._baseline[pair] = new_value
                return
            baseline = old_value
            self._baseline[pair] = baseline

        if new_value == baseline:
            self._resolve(pair)
        else:
            self._raise(pair, key, field, baseline, new_value, new)

    # -- mutations -------------------------------------------------------
    def _raise(self, pair, key, field, baseline, new_value, rec):
        """Create or refresh the alert for ``pair`` and move it to the front."""
        now = datetime.now().isoformat(timespec="seconds")
        with self.lock:
            for index, alert in enumerate(self._alerts):
                if (alert.get("key"), alert.get("field")) == pair:
                    alert["new_value"] = new_value
                    alert["status"] = rec.get("status", "")
                    alert["status_category"] = _category(rec)
                    alert["raised_at"] = now
                    if index:
                        self._alerts.insert(0, self._alerts.pop(index))
                    break
            else:
                self._alerts.insert(0, {
                    "key": key,
                    "flight_number": rec.get("flight_number", ""),
                    "date": rec.get("date", ""),
                    "time": rec.get("time", ""),
                    "type": rec.get("type", ""),
                    "field": field.upper(),
                    "old_value": baseline,
                    "new_value": new_value,
                    "status": rec.get("status", ""),
                    "status_category": _category(rec),
                    "raised_at": now,
                })
                del self._alerts[MAX_ALERTS:]
            self._revision += 1
            payload = [dict(a) for a in self._alerts]
        self._persist(payload)

    def _resolve(self, pair):
        """The flight returned to its baseline: its alert no longer applies."""
        with self.lock:
            kept = [a for a in self._alerts if (a.get("key"), a.get("field")) != pair]
            if len(kept) == len(self._alerts):
                return
            self._alerts = kept
            self._revision += 1
            payload = [dict(a) for a in self._alerts]
        self._persist(payload)

    def _drop_key(self, key):
        """Remove every alert and baseline for a flight (it has departed)."""
        with self.lock:
            kept = [a for a in self._alerts if a.get("key") != key]
            for pair in [p for p in self._baseline if p[0] == key]:
                del self._baseline[pair]
            if len(kept) == len(self._alerts):
                return
            self._alerts = kept
            self._revision += 1
            payload = [dict(a) for a in self._alerts]
        self._persist(payload)

    def _persist(self, payload):
        """Write the alert list through to the cache (never raises)."""
        if self.cache is not None:
            self.cache.write_alerts(payload)
