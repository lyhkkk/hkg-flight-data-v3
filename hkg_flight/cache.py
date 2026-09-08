"""
HKG Flight Data v3 - Cache System Module
Manages on-disk caching of flight data.
"""

import json
import os
import threading
import time
from datetime import datetime

from .utils import normalize_flight_number, log, validate_date


# Default cache directory
DEFAULT_CACHE_DIR = "~/.hkg_flight_cache"

# Default API rate limit interval (seconds)
DEFAULT_MIN_API_INTERVAL = 0.6

# Default web server port
DEFAULT_WEB_PORT = 8080


def _safe_cache_path(cache_dir, filename):
    """
    Safely construct a cache file path, ensuring it stays within cache_dir.
    Returns the absolute path, or None if path traversal is detected.
    """
    # Get absolute path of cache directory
    abs_cache_dir = os.path.abspath(cache_dir)
    
    # Construct the full path
    full_path = os.path.join(cache_dir, filename)
    abs_full_path = os.path.abspath(full_path)
    
    # Verify the path is within the cache directory
    if not abs_full_path.startswith(abs_cache_dir + os.sep) and abs_full_path != abs_cache_dir:
        log("Path traversal detected: {}".format(filename))
        return None
    
    return abs_full_path


class CacheSystem(object):
    """
    Manages the on-disk cache in ``~/.hkg_flight_cache``.

    Files:
      flights_YYYY-MM-DD.json  - raw HKIA API per date
      airlines.json            - airline metadata
      state.json               - current state of all tracked flights
      alerts.json              - pending alerts (active + history)
    """

    def __init__(self, cache_dir=DEFAULT_CACHE_DIR):
        self.cache_dir = os.path.expanduser(cache_dir)
        self.lock = threading.Lock()
        os.makedirs(self.cache_dir, exist_ok=True)

    # -- paths ------------------------------------------------------------
    def flight_path(self, date_str):
        """Get cache path for a specific date. Returns None if date is invalid."""
        if not validate_date(date_str):
            log("Invalid date format: {}".format(date_str))
            return None
        return _safe_cache_path(self.cache_dir, "flights_{}.json".format(date_str))

    @property
    def airlines_path(self):
        return os.path.join(self.cache_dir, "airlines.json")

    @property
    def state_path(self):
        return os.path.join(self.cache_dir, "state.json")

    @property
    def alerts_path(self):
        return os.path.join(self.cache_dir, "alerts.json")

    @property
    def fvm_reg_path(self):
        return os.path.join(self.cache_dir, "fvm_registrations.json")

    # -- generic io -------------------------------------------------------
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
            log("cache write failed {}: {}".format(path, exc))

    def cache_age_minutes(self, path):
        try:
            age = time.time() - os.path.getmtime(path)
            return int(age // 60)
        except Exception:
            return -1

    # -- flights ----------------------------------------------------------
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

    # -- airlines ---------------------------------------------------------
    def read_airlines(self):
        data = self._read_json(self.airlines_path, [])
        return data if isinstance(data, list) else []

    def write_airlines(self, data):
        with self.lock:
            self._write_json(self.airlines_path, data)

    # -- state ------------------------------------------------------------
    def read_state(self):
        data = self._read_json(self.state_path, {})
        if isinstance(data, dict) and isinstance(data.get("flights"), dict):
            return data["flights"]
        return data if isinstance(data, dict) else {}

    def write_state(self, state):
        with self.lock:
            self._write_json(self.state_path, state if isinstance(state, dict) else {})

    # -- alerts -----------------------------------------------------------
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
            payload = {
                "active": alert_data.get("active", []),
                "history": alert_data.get("history", []),
            }
            self._write_json(self.alerts_path, payload)

    # -- FVM registrations (accumulated over time) -------------------------
    def read_fvm_registrations(self):
        """Read accumulated FVM registration data (flight_id -> reg info)."""
        data = self._read_json(self.fvm_reg_path, {})
        return data if isinstance(data, dict) else {}

    def write_fvm_registrations(self, data):
        """Write accumulated FVM registration data."""
        with self.lock:
            self._write_json(self.fvm_reg_path, data if isinstance(data, dict) else {})

    def merge_fvm_snapshot(self, fvm_list):
        """
        Merge a FVM API snapshot into the accumulated cache.
        FVM returns current active flights; we accumulate over time so we
        keep registration data for flights that have already departed.
        """
        if not isinstance(fvm_list, list):
            return
        with self.lock:
            accumulated = self._read_json(self.fvm_reg_path, {})
            if not isinstance(accumulated, dict):
                accumulated = {}
            for item in fvm_list:
                fid = item.get("flight_id", "")
                if not fid:
                    continue
                key = normalize_flight_number(fid)
                existing = accumulated.get(key, {})
                # Update with latest data, keep old fields if new ones are empty
                merged = {
                    "REG": item.get("REG") or existing.get("REG", ""),
                    "SUBTYPE": item.get("SUBTYPE") or existing.get("SUBTYPE", ""),
                    "ORIG": item.get("ORIG") or existing.get("ORIG", ""),
                    "DEST": item.get("DEST") or existing.get("DEST", ""),
                    "STAND": item.get("STAND") or existing.get("STAND", ""),
                    "BR": item.get("BR") or existing.get("BR", ""),
                    "RWY": item.get("RWY") or existing.get("RWY", ""),
                    "ETA": item.get("ETA") or existing.get("ETA", ""),
                    "ATA": item.get("ATA") or existing.get("ATA", ""),
                    "NO": item.get("NO") or existing.get("NO", ""),
                    "last_seen": datetime.now().isoformat(timespec="seconds"),
                }
                accumulated[key] = merged
            self._write_json(self.fvm_reg_path, accumulated)
