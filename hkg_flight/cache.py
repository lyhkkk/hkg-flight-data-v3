"""
HKG Flight Data v3 - Cache System.

On-disk cache under ``~/.hkg_flight_cache``:

  flights_YYYY-MM-DD.json  raw HKIA API response per date
  airlines.json            airline metadata
  alerts.json              active alerts + retained history

Writes are atomic (temp file + ``os.replace``). Reads never raise: a missing or
corrupt file is simply a cache miss.
"""

import json
import os
import threading
import time

from .utils import log, validate_date


DEFAULT_CACHE_DIR = "~/.hkg_flight_cache"

# Minimum seconds between HKIA API calls (the reference client uses 0.5).
DEFAULT_MIN_API_INTERVAL = 0.6

DEFAULT_WEB_PORT = 8080


class CacheSystem:
    """On-disk cache for flight data, airline metadata and alerts."""

    def __init__(self, cache_dir=DEFAULT_CACHE_DIR):
        self.cache_dir = os.path.expanduser(cache_dir)
        self.lock = threading.Lock()
        os.makedirs(self.cache_dir, exist_ok=True)

    # -- paths -----------------------------------------------------------
    def flight_path(self, date_str):
        """Cache path for one date, or None when the date is malformed.

        ``date_str`` is always validated to ``\\d{4}-\\d{2}-\\d{2}`` before it
        reaches the filesystem, so the filename cannot escape the cache dir.
        """
        if not validate_date(date_str):
            return None
        return os.path.join(self.cache_dir, f"flights_{date_str}.json")

    @property
    def airlines_path(self):
        return os.path.join(self.cache_dir, "airlines.json")

    @property
    def alerts_path(self):
        return os.path.join(self.cache_dir, "alerts.json")

    # -- generic io ------------------------------------------------------
    def _read_json(self, path, default=None):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return default

    def _write_json(self, path, obj):
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(obj, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as exc:
            log(f"cache write failed {path}: {exc}")

    def cache_age_minutes(self, path):
        """Age of a cache file in whole minutes, or -1 when unavailable."""
        try:
            return int(max(0.0, time.time() - os.path.getmtime(path)) // 60)
        except Exception:
            return -1

    # -- flights ---------------------------------------------------------
    def read_flights(self, date_str):
        path = self.flight_path(date_str)
        if path is None:
            return None
        data = self._read_json(path, None)
        return data if isinstance(data, list) else None

    def write_flights(self, date_str, data):
        path = self.flight_path(date_str)
        if path is None:
            return
        with self.lock:
            self._write_json(path, data)

    def clear_flights(self, date_str):
        """Delete the cached file for one date (a no-op when absent)."""
        path = self.flight_path(date_str)
        if path is None:
            return
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception as exc:
            log(f"cache delete failed {path}: {exc}")

    def flight_mtime(self, date_str):
        """Cached flights file mtime as epoch seconds, or None.

        This is when the *local* file was written, not when HKIA generated the
        data; callers must surface UNKNOWN rather than a fake time when absent.
        """
        path = self.flight_path(date_str)
        if path is None:
            return None
        try:
            return os.path.getmtime(path)
        except Exception:
            return None

    # -- airlines --------------------------------------------------------
    def read_airlines(self):
        data = self._read_json(self.airlines_path, [])
        return data if isinstance(data, list) else []

    def write_airlines(self, data):
        with self.lock:
            self._write_json(self.airlines_path, data)

    # -- alerts ----------------------------------------------------------
    def read_alerts(self):
        data = self._read_json(self.alerts_path, {})
        if not isinstance(data, dict):
            data = {}
        active = data.get("active", [])
        history = data.get("history", [])
        return {
            "active": active if isinstance(active, list) else [],
            "history": history if isinstance(history, list) else [],
        }

    def write_alerts(self, alert_data):
        with self.lock:
            self._write_json(self.alerts_path, {
                "active": alert_data.get("active", []),
                "history": alert_data.get("history", []),
            })
