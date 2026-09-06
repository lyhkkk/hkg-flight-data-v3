#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HKG Flight Data v3 — single-file flight information retrieval system for
Hong Kong International Airport (HKIA).

Backend:
  - APIClient     : polite HKIA REST API client with cache fallback
  - CacheSystem   : ~/.hkg_flight_cache/ JSON cache and state store
  - AlertManager  : gate/stand change alerts with active/history tracking
  - Poller        : background daemon that polls today's flights every 30s

Frontend:
  - curses TUI with pagination, filtering, colors and web-server toggle
  - Simple print fallback when curses is unavailable
  - CLI one-shot queries: query, departures, arrivals, alerts

Only the Python 3.7+ standard library is required.
"""

import json
import os
import re
import sys
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

# curses is optional; on Windows without windows-curses it's unavailable.
try:
    import curses
except ImportError:
    curses = None

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except ImportError:  # pragma: no cover - very old Python fallback
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class ThreadingHTTPServer(HTTPServer):
        daemon_threads = True

# =========================================================================
# Constants
# =========================================================================

API_BASE = "https://www.hongkongairport.com/flightinfo-rest/rest"
DEFAULT_CACHE_DIR = os.path.expanduser("~/.hkg_flight_cache")
DEFAULT_POLL_INTERVAL = 30          # seconds
DEFAULT_MIN_API_INTERVAL = 0.6      # seconds between API calls
DEFAULT_TIMEOUT = 15                # seconds
DEFAULT_WEB_PORT = 8080
PAGE_SIZE = 20
HISTORY_LIMIT = 100

# Status categories that clear an active gate/stand alert.
CLEAR_ALERT_STATUSES = frozenset({
    "boarding", "departed", "arrived", "landed", "cancelled"
})

# =========================================================================
# Small helpers
# =========================================================================


def today_str():
    """Return today's date as YYYY-MM-DD."""
    return date.today().isoformat()


def normalize_flight_number(no):
    """Normalize a flight number (e.g. 'CX 759' -> 'CX759')."""
    if no is None:
        return ""
    return str(no).strip().replace(" ", "").upper()


def make_flight_key(date_str, flight_number):
    """Stable per-flight key: ``2026-08-16_CX759``."""
    return "{}_{}".format(date_str, normalize_flight_number(flight_number))


def route_text(rec):
    """Human readable route for a normalized flight record."""
    if rec.get("type") == "arrival":
        origin = rec.get("origin", "").replace("|", "/")
        return "{} → HKG".format(origin) if origin else "-- → HKG"
    dest = rec.get("destination", "").replace("|", "/")
    return "HKG → {}".format(dest) if dest else "HKG → --"


def gate_stand_text(rec):
    """Gate/stand column text."""
    gate = rec.get("gate", "")
    stand = rec.get("stand", "")
    if gate:
        return "Gate {}".format(gate)
    if stand:
        return "Stand {}".format(stand)
    return "--"


def format_time(value):
    """Format a datetime/time value as HH:MM:SS or return the original."""
    if value is None:
        return "--:--:--"
    if isinstance(value, datetime):
        return value.strftime("%H:%M:%S")
    return str(value)


def format_raw_time(value):
    """Format a plain HH:MM value."""
    if not value:
        return "--:--"
    return str(value)


def log(msg):
    """Simple stderr logger used by background components."""
    try:
        sys.stderr.write("[hkg_flight] {}\n".format(msg))
        sys.stderr.flush()
    except Exception:
        pass


# =========================================================================
# Status display mapping
# =========================================================================

# Curses color pair ids (also reused by the simple print TUI as names).
PAIR_SCHEDULED = 1
PAIR_GATE_CLOSED = 2
PAIR_BOARDING_SOON = 3
PAIR_FINAL_CALL = 4
PAIR_BOARDING = 5
PAIR_DEPARTED = 6
PAIR_EST = 7
PAIR_DELAYED = 8
PAIR_ARRIVED = 9
PAIR_LANDED = 10
PAIR_CANCELLED = 11
PAIR_HEADER = 12
PAIR_ACCENT = 13

# ANSI-like colors for the non-curses fallback.
SIMPLE_COLORS = {
    PAIR_SCHEDULED: "\033[0m",
    PAIR_GATE_CLOSED: "\033[33m",
    PAIR_BOARDING_SOON: "\033[36m",
    PAIR_FINAL_CALL: "\033[35m",
    PAIR_BOARDING: "\033[32m",
    PAIR_DEPARTED: "\033[32;2m",
    PAIR_EST: "\033[33m",
    PAIR_DELAYED: "\033[31m",
    PAIR_ARRIVED: "\033[32m",
    PAIR_LANDED: "\033[32;2m",
    PAIR_CANCELLED: "\033[31m",
    PAIR_HEADER: "\033[36m",
    PAIR_ACCENT: "\033[33m",
}
RESET = "\033[0m"


def get_status_info(raw_status, flight_type=None):
    """
    Convert a raw HKIA status string into a triple:

        (category, display_with_icon, display_plain)

    ``category`` is the normalized classification used by alerts and colors.
    """
    s = (raw_status or "").strip()
    low = s.lower()

    if not s:
        return "scheduled", "○ Scheduled", "Scheduled"

    if "cancel" in low:
        return "cancelled", "✗ Cancelled", "Cancelled"
    if "delay" in low:
        return "delayed", "⚠ Delayed", "Delayed"
    if "gate closed" in low:
        return "gate closed", "◉ Gate Closed", "Gate Closed"
    if "boarding soon" in low:
        return "boarding soon", "◉ Boarding Soon", "Boarding Soon"
    if "final call" in low:
        return "final call", "⚡ Final Call", "Final Call"
    if "boarding" in low:
        return "boarding", "✓ Boarding", "Boarding"

    if low.startswith("dep") or "departed" in low:
        return "departed", "→ Departed", "Departed"
    if "arrived" in low:
        return "arrived", "✓ Arrived", "Arrived"
    if "landed" in low or "landing" in low:
        return "landed", "↓ Landed", "Landed"

    if "est at" in low or "estimated" in low:
        m = re.search(r"est(?:imated)?\s+at\s+(\d{2}:\d{2})", low)
        tail = m.group(1) if m else s
        return "est", "⏱ Est at {}".format(tail), "Est at {}".format(tail)

    if "at gate" in low:
        if flight_type == "arrival":
            return "arrived", "✓ At Gate", "Arrived"
        return "boarding", "✓ At Gate", "Boarding"

    if "scheduled" in low:
        return "scheduled", "○ Scheduled", "Scheduled"
    if "check" in low:
        return "scheduled", "○ Check-in", "Check-in"

    # Unknown text: keep it visible but treat as scheduled category.
    return "scheduled", "○ {}".format(s), s


def status_pair(category):
    """Color pair id for a status category."""
    mapping = {
        "scheduled": PAIR_SCHEDULED,
        "gate closed": PAIR_GATE_CLOSED,
        "boarding soon": PAIR_BOARDING_SOON,
        "final call": PAIR_FINAL_CALL,
        "boarding": PAIR_BOARDING,
        "departed": PAIR_DEPARTED,
        "est": PAIR_EST,
        "delayed": PAIR_DELAYED,
        "arrived": PAIR_ARRIVED,
        "landed": PAIR_LANDED,
        "cancelled": PAIR_CANCELLED,
    }
    return mapping.get(category, PAIR_SCHEDULED)


# =========================================================================
# Normalized flight records
# =========================================================================


def normalize_flights(raw_data):
    """
    Convert the raw HKIA API array into a flat list of normalized records.

    Cargo entries are skipped. Codeshares are preserved in
    ``all_flight_numbers`` for searching.
    """
    records = []
    if not isinstance(raw_data, list):
        return records

    for entry in raw_data:
        if not isinstance(entry, dict):
            continue
        if entry.get("cargo"):
            continue

        is_arrival = bool(entry.get("arrival"))
        entry_date = str(entry.get("date") or "")

        for flight_obj in entry.get("list") or []:
            if not isinstance(flight_obj, dict):
                continue

            flight_list = flight_obj.get("flight") or []
            primary = flight_list[0] if isinstance(flight_list, list) and flight_list else {}
            raw_no = primary.get("no", "") if isinstance(primary, dict) else ""
            flight_number = normalize_flight_number(raw_no)
            if not flight_number:
                continue

            all_nos = []
            for item in flight_list:
                if isinstance(item, dict) and item.get("no"):
                    all_nos.append(normalize_flight_number(item.get("no")))

            origin = flight_obj.get("origin") or []
            destination = flight_obj.get("destination") or []
            if isinstance(origin, str):
                origin = [origin]
            if isinstance(destination, str):
                destination = [destination]

            status_raw = str(flight_obj.get("status") or "")
            status_cat, status_disp, status_label = get_status_info(
                status_raw, "arrival" if is_arrival else "departure"
            )

            rec = {
                "key": make_flight_key(entry_date, flight_number),
                "date": entry_date,
                "time": str(flight_obj.get("time") or ""),
                "flight_number": flight_number,
                "airline_code": str(primary.get("airline", "")) if isinstance(primary, dict) else "",
                "all_flight_numbers": "|".join(all_nos),
                "type": "arrival" if is_arrival else "departure",
                "status": status_raw,
                "statusCode": flight_obj.get("statusCode"),
                "status_category": status_cat,
                "status_display": status_disp,
                "status_label": status_label,
                "terminal": str(flight_obj.get("terminal") or ""),
                "gate": str(flight_obj.get("gate") or ""),
                "aisle": str(flight_obj.get("aisle") or ""),
                "hall": str(flight_obj.get("hall") or ""),
                "belt": str(flight_obj.get("baggage") or flight_obj.get("belt") or ""),
                "stand": str(flight_obj.get("stand") or ""),
                "origin": "|".join(x for x in origin if x),
                "destination": "|".join(x for x in destination if x),
            }
            records.append(rec)

    return records


def sort_flights(records):
    """Sort flights by date then scheduled time, then flight number."""
    return sorted(records, key=lambda r: (r.get("date", ""), r.get("time", ""), r.get("flight_number", "")))


def filter_records(records, text):
    """
    Filter normalized records by flight number, route, status, or terminal.
    Used by both the TUI and the web UI.
    """
    if not text:
        return records
    text = text.strip().lower()
    out = []
    for rec in records:
        haystack = "|".join([
            rec.get("flight_number", ""),
            rec.get("all_flight_numbers", ""),
            rec.get("origin", ""),
            rec.get("destination", ""),
            rec.get("status", ""),
            rec.get("status_label", ""),
            rec.get("terminal", ""),
            rec.get("gate", ""),
            rec.get("stand", ""),
            rec.get("hall", ""),
            rec.get("belt", ""),
        ]).lower()
        if text in haystack:
            out.append(rec)
    return out


# =========================================================================
# BACKEND: CacheSystem
# =========================================================================


class CacheSystem(object):
    """
    Manages the on-disk cache in ``~/.hkg_flight_cache``.

    Files:
      flights_YYYY-MM-DD.json  — raw HKIA API per date
      airlines.json            — airline metadata
      state.json               — current state of all tracked flights
      alerts.json              — pending alerts (active + history)
    """

    def __init__(self, cache_dir=DEFAULT_CACHE_DIR):
        self.cache_dir = os.path.expanduser(cache_dir)
        self.lock = threading.Lock()
        os.makedirs(self.cache_dir, exist_ok=True)

    # -- paths ------------------------------------------------------------
    def flight_path(self, date_str):
        return os.path.join(self.cache_dir, "flights_{}.json".format(date_str))

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
        data = self._read_json(self.flight_path(date_str), None)
        return data if isinstance(data, list) else None

    def write_flights(self, date_str, data):
        with self.lock:
            self._write_json(self.flight_path(date_str), data)

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


# =========================================================================
# BACKEND: APIClient
# =========================================================================


class APIClient(object):
    """
    Polite HKIA REST API client.

    - minimum 0.6s between requests
    - proper browser-ish headers
    - 15s timeout, one retry
    - falls back to on-disk cache when live API fails
    """

    def __init__(self, cache=None, min_interval=DEFAULT_MIN_API_INTERVAL,
                 timeout=DEFAULT_TIMEOUT):
        self.cache = cache or CacheSystem()
        self.min_interval = min_interval
        self.timeout = timeout
        self._rate_lock = threading.Lock()
        self._last_request = 0.0
        self._airlines_mem = None

    # -- low level --------------------------------------------------------
    def _rate_limit(self):
        """Sleep until the minimum interval since the last request has passed."""
        with self._rate_lock:
            now = time.time()
            wait = self._last_request + self.min_interval - now
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.time()

    def _request_json(self, url):
        """GET json with one retry. Returns parsed list/dict or None."""
        last_exc = None
        for attempt in range(2):
            try:
                self._rate_limit()
                req = urllib.request.Request(url, headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"
                    ),
                    "Accept": "application/json",
                    "Referer": "https://www.hongkongairport.com/en/flights/arrivals/passenger.page",
                })
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if data is not None:
                    return data
            except Exception as exc:
                last_exc = exc
                if attempt == 0:
                    time.sleep(0.5)
        if last_exc is not None:
            log("API request failed for {}: {}".format(url, last_exc))
        return None

    # -- flights ----------------------------------------------------------
    def fetch_flights(self, date_str):
        """
        Fetch flights for a date. Past dates use the /past endpoint.
        Returns raw list on success, or cached data if the API failed.
        Returns None only when both live API and cache fail.
        """
        try:
            target = date.fromisoformat(date_str)
        except Exception:
            target = date.today()

        if target < date.today():
            endpoint = "flights/past"
        else:
            endpoint = "flights"

        url = "{}/{}{}?date={}&span=1".format(
            API_BASE, endpoint, "" if endpoint == "flights" else "", date_str
        )
        # The URL above works for both endpoints; kept explicit for clarity.
        url = "{}/{}?date={}&span=1".format(API_BASE, endpoint, date_str)

        data = self._request_json(url)
        if isinstance(data, list):
            self.cache.write_flights(date_str, data)
            return data

        cached = self.cache.read_flights(date_str)
        if cached is not None:
            age = self.cache.cache_age_minutes(self.cache.flight_path(date_str))
            log("⚠ API failed for {}, using cache (age: {}m)".format(date_str, age))
            return cached
        return None

    # -- airlines ---------------------------------------------------------
    def fetch_airlines(self):
        """Fetch airline metadata, preferring a live API call."""
        if self._airlines_mem is not None:
            return list(self._airlines_mem)

        url = "{}/airlines".format(API_BASE)
        data = self._request_json(url)
        if isinstance(data, list):
            self._airlines_mem = data
            self.cache.write_airlines(data)
            return data

        cached = self.cache.read_airlines()
        if cached:
            log("⚠ airlines API failed, using cache")
            self._airlines_mem = cached
            return cached
        return []

    # -- FVM registration/tail numbers ------------------------------------
    def fetch_fvm_registrations(self):
        """
        Fetch aircraft registration/tail numbers from fvm.menziescnac.com.

        Returns accumulated registration data (current + cached historical).
        FVM only returns ~40-50 active flights; we accumulate over time so
        departed flights retain their registration info.

        Returns a dict mapping flight_id (e.g. "CX469") to registration info:
        { "CX469": {"REG": "BHPQ", "SUBTYPE": "32Q", "ORIG": "TPE", ...}, ... }
        """
        url = "https://fvm.menziescnac.com/flights"
        try:
            self._rate_limit()
            req = urllib.request.Request(url, headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                # Merge into accumulated cache
                self.cache.merge_fvm_snapshot(data)
                # Return the full accumulated data
                return self.cache.read_fvm_registrations()
        except Exception as exc:
            log("⚠ FVM registration API failed: {}".format(exc))
        # On failure, return cached data
        return self.cache.read_fvm_registrations()


# =========================================================================
# BACKEND: AlertManager
# =========================================================================


class AlertManager(object):
    """
    Tracks gate/stand changes and maintains active + history alerts.

    Active alerts are only kept while the status is not a terminal status
    (boarding / departed / arrived / landed / cancelled).
    """

    def __init__(self, cache=None):
        self.cache = cache or CacheSystem()
        data = self.cache.read_alerts()
        self.active = data["active"]
        self.history = data["history"]
        self.lock = threading.Lock()
        self._new_flag = False

    # -- persistence ------------------------------------------------------
    def save(self):
        self.cache.write_alerts({"active": self.active, "history": self.history})

    # -- queries ----------------------------------------------------------
    def active_count(self):
        with self.lock:
            return len(self.active)

    def get_active(self):
        with self.lock:
            return [dict(a) for a in self.active]

    def get_history(self):
        with self.lock:
            return [dict(a) for a in self.history]

    def consume_new_flag(self):
        """Return and clear the 'new alert raised' flag used for TUI flash."""
        with self.lock:
            flag = self._new_flag
            self._new_flag = False
            return flag

    # -- diff processing --------------------------------------------------
    def process_flight(self, old, new):
        """
        Given the old and new snapshot of one flight, raise/update gate/stand
        alerts and clear alerts when the status becomes terminal.
        """
        if not isinstance(old, dict) or not isinstance(new, dict):
            return

        key = new.get("key") or old.get("key")
        flight_number = new.get("flight_number") or old.get("flight_number")
        status_raw = new.get("status") or ""
        flight_type = new.get("type") or old.get("type")
        status_cat, _, status_label = get_status_info(status_raw, flight_type)

        with self.lock:
            # 1. Raise/update gate and stand alerts for non-terminal statuses.
            if status_cat not in CLEAR_ALERT_STATUSES:
                for field, label in (("gate", "GATE"), ("stand", "STAND")):
                    old_value = str(old.get(field) or "")
                    new_value = str(new.get(field) or "")
                    if old_value != new_value and (old_value or new_value):
                        self._upsert_alert(
                            key=key,
                            flight_number=flight_number,
                            date=new.get("date") or old.get("date") or "",
                            time=new.get("time") or old.get("time") or "",
                            flight_type=new.get("type") or old.get("type") or "",
                            field=label,
                            old_value=old_value,
                            new_value=new_value,
                            status_text=status_label,
                            raised_at=datetime.now().isoformat(timespec="seconds"),
                        )

            # 2. Terminal status clears all active alerts for this flight.
            if status_cat in CLEAR_ALERT_STATUSES:
                self._clear_for_key(key)

        # Persist outside the lock to avoid holding it during disk I/O.
        self.save()

    def _upsert_alert(self, key, flight_number, date, time, flight_type,
                      field, old_value, new_value, status_text, raised_at):
        """
        Insert a new active alert, or update an existing active alert for the
        same key+field (keeping the original raised_at and old_value).
        """
        for alert in self.active:
            if alert.get("key") == key and alert.get("field") == field:
                alert["flight_number"] = flight_number
                alert["date"] = date
                alert["time"] = time
                alert["type"] = flight_type
                alert["new_value"] = new_value
                alert["status"] = status_text
                # Keep the first seen old_value so the alert tells the full story.
                self._new_flag = True
                return

        alert = {
            "key": key,
            "flight_number": flight_number,
            "date": date,
            "time": time,
            "type": flight_type,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "status": status_text,
            "raised_at": raised_at,
        }
        self.active.append(alert)
        self._new_flag = True

    def _clear_for_key(self, key):
        """Move all active alerts for a flight into history (max 100)."""
        remaining = []
        cleared = []
        for alert in self.active:
            if alert.get("key") == key:
                alert["cleared_at"] = datetime.now().isoformat(timespec="seconds")
                cleared.append(alert)
            else:
                remaining.append(alert)
        self.active = remaining
        if cleared:
            self.history.extend(cleared)
            self.history = self.history[-HISTORY_LIMIT:]


# =========================================================================
# BACKEND: Poller
# =========================================================================


class Poller(object):
    """
    Daemon thread that polls today's flights every 30 seconds.

    The poller also maintains ``state.json`` and runs the AlertManager diff
    so gate/stand changes are detected live.
    """

    def __init__(self, cache=None, api=None, alert_manager=None,
                 poll_interval=DEFAULT_POLL_INTERVAL, enabled=True):
        self.cache = cache or CacheSystem()
        self.api = api or APIClient(self.cache)
        self.alert_manager = alert_manager or AlertManager(self.cache)
        self.poll_interval = poll_interval
        self.enabled = enabled

        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None

        self.today_date = today_str()
        self.today_records = []
        self.today_by_key = {}
        self.state = self.cache.read_state()
        self.last_update = None
        self.next_update = None
        self.last_error = None

    # -- lifecycle --------------------------------------------------------
    def start(self):
        if not self.enabled or self.thread is not None:
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="hkg-poller", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _run(self):
        self.refresh_today()
        while not self.stop_event.wait(self.poll_interval):
            self.refresh_today()

    # -- data access ------------------------------------------------------
    def get_today(self):
        with self.lock:
            arrivals = [dict(r) for r in self.today_records if r.get("type") == "arrival"]
            departures = [dict(r) for r in self.today_records if r.get("type") == "departure"]
            return {
                "date": self.today_date,
                "arrivals": arrivals,
                "departures": departures,
                "records": [dict(r) for r in self.today_records],
                "last_update": self.last_update,
                "next_update": self.next_update,
                "last_error": self.last_error,
            }

    def consume_new_alert_flag(self):
        return self.alert_manager.consume_new_flag()

    # -- polling ----------------------------------------------------------
    def refresh_today(self):
        """Fetch today's data, update state, and diff gate/stand changes."""
        self.today_date = today_str()
        raw = self.api.fetch_flights(self.today_date)
        now = datetime.now()

        # Fetch FVM registration/tail number data (separate API)
        fvm_data = self.api.fetch_fvm_registrations()

        if raw is None:
            with self.lock:
                self.last_error = "API unavailable; showing cached/current data"
                self.next_update = now + timedelta(seconds=self.poll_interval)
            return False

        records = normalize_flights(raw)

        # Merge FVM registration data into records
        for rec in records:
            fn = rec.get("flight_number", "")
            fvm = fvm_data.get(fn, {})
            if fvm:
                rec["reg"] = fvm.get("REG", "")
                rec["aircraft_type"] = fvm.get("SUBTYPE", "")
                # FVM may have more accurate stand/gate info
                if fvm.get("STAND") and not rec.get("stand"):
                    rec["stand"] = fvm["STAND"]
                if fvm.get("BR") and not rec.get("gate"):
                    rec["gate"] = fvm["BR"]

        by_key = {}
        for rec in records:
            by_key[rec["key"]] = rec

        with self.lock:
            for key, rec in by_key.items():
                old = self.state.get(key)
                new_snap = self._make_snapshot(rec, now)
                if old is not None and self._snapshot_changed(old, new_snap):
                    self.alert_manager.process_flight(old, new_snap)
                self.state[key] = new_snap

            self.today_records = sort_flights(records)
            self.today_by_key = by_key
            self.last_update = now
            self.next_update = now + timedelta(seconds=self.poll_interval)
            self.last_error = None

            # Persist state + alerts after each successful poll.
            self.cache.write_state(self.state)
            self.alert_manager.save()
        return True

    @staticmethod
    def _make_snapshot(rec, now):
        return {
            "key": rec.get("key", ""),
            "flight_number": rec.get("flight_number", ""),
            "date": rec.get("date", ""),
            "time": rec.get("time", ""),
            "type": rec.get("type", ""),
            "status": rec.get("status", ""),
            "terminal": rec.get("terminal", ""),
            "gate": rec.get("gate", ""),
            "stand": rec.get("stand", ""),
            "aisle": rec.get("aisle", ""),
            "hall": rec.get("hall", ""),
            "belt": rec.get("belt", ""),
            "reg": rec.get("reg", ""),
            "aircraft_type": rec.get("aircraft_type", ""),
            "last_updated": now.isoformat(timespec="seconds"),
        }

    @staticmethod
    def _snapshot_changed(old, new):
        """Compare snapshots ignoring last_updated."""
        for field in ("key", "flight_number", "date", "time", "type", "status",
                      "terminal", "gate", "stand", "aisle", "hall", "belt"):
            if old.get(field) != new.get(field):
                return True
        return False


# =========================================================================
# Search / data helpers
# =========================================================================


def search_flights(api, flight_number, date_str=None):
    """
    Search a flight number (or codeshare) across yesterday/today/tomorrow,
    or across one explicit date. Returns normalized records.
    """
    fn = normalize_flight_number(flight_number)
    if not fn:
        return []

    if date_str:
        dates = [date_str]
    else:
        today = date.today()
        dates = [
            (today - timedelta(days=1)).isoformat(),
            today.isoformat(),
            (today + timedelta(days=1)).isoformat(),
        ]

    results = {}
    for dt in dates:
        raw = api.fetch_flights(dt)
        if not isinstance(raw, list):
            continue
        for rec in normalize_flights(raw):
            if rec.get("date") != dt:
                continue
            numbers = "|{}|".format(rec.get("all_flight_numbers", ""))
            if rec.get("flight_number") == fn or "|{}|".format(fn) in numbers:
                results[rec["key"]] = rec

    results_list = sort_flights(list(results.values()))
    # Merge FVM registration data
    _merge_fvm_data(api, results_list)
    return results_list


def flights_for_date(api, date_str, flight_type="all"):
    """Return normalized, sorted flights for a single exact date."""
    raw = api.fetch_flights(date_str)
    if not isinstance(raw, list):
        return []
    records = [r for r in normalize_flights(raw) if r.get("date") == date_str]
    if flight_type in ("arrival", "departure"):
        records = [r for r in records if r.get("type") == flight_type]
    records = sort_flights(records)
    # Merge FVM registration data
    _merge_fvm_data(api, records)
    return records


def _merge_fvm_data(api, records):
    """
    Merge FVM registration/tail number data into flight records.

    FVM only returns currently active flights at the airport (typically ~40-50).
    Flights not in FVM are either not yet active or already departed long ago.
    """
    if not records:
        return
    fvm_data = api.fetch_fvm_registrations()
    if not fvm_data:
        return
    matched = 0
    for rec in records:
        fn = rec.get("flight_number", "")
        # Try exact match first, then without spaces
        fvm = fvm_data.get(fn) or fvm_data.get(fn.replace(" ", ""))
        if fvm:
            matched += 1
            rec["reg"] = fvm.get("REG", "")
            rec["aircraft_type"] = fvm.get("SUBTYPE", "")
            # FVM may have more accurate stand/gate for active flights
            if fvm.get("STAND"):
                rec["stand"] = fvm["STAND"]
            if fvm.get("BR") and fvm["BR"].strip():
                rec["gate"] = fvm["BR"]
    log("FVM merge: {}/{} flights matched".format(matched, len(records)))


def load_airlines(api):
    """Return airline metadata via API/cache."""
    return api.fetch_airlines()


# =========================================================================
# Web Server
# =========================================================================


class WebServer(object):
    """Non-blocking HTTP server exposing a dark-themed web UI + JSON API."""

    def __init__(self, poller, api, alert_manager, port=DEFAULT_WEB_PORT):
        self.poller = poller
        self.api = api
        self.alert_manager = alert_manager
        self.port = port
        self.httpd = None
        self.thread = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.stats_cache = {"time": 0.0, "data": None}

    # -- lifecycle --------------------------------------------------------
    def running(self):
        with self.lock:
            return self.httpd is not None

    def start(self):
        with self.lock:
            if self.httpd is not None:
                return False
            self.stop_event.clear()
            handler = self._make_handler()
            try:
                self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
            except Exception as exc:
                log("web server failed to start on port {}: {}".format(self.port, exc))
                self.httpd = None
                return False
            self.thread = threading.Thread(
                target=self.httpd.serve_forever, name="hkg-web", daemon=True
            )
            self.thread.start()
            return True

    def stop(self):
        with self.lock:
            if self.httpd is None:
                return
            self.stop_event.set()
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None
            self.thread = None

    # -- stats ------------------------------------------------------------
    def get_stats(self):
        """Calculated stats with a tiny cache to avoid hammering the API."""
        now = time.time()
        if self.stats_cache["data"] and now - self.stats_cache["time"] < 2:
            return self.stats_cache["data"]

        today = self.poller.get_today()
        airlines = self.api.fetch_airlines()
        stats = {
            "date": today["date"],
            "arrivals": len(today["arrivals"]),
            "departures": len(today["departures"]),
            "airlines": len(airlines),
            "alerts": self.alert_manager.active_count(),
            "last_update": (
                today["last_update"].strftime("%Y-%m-%d %H:%M:%S")
                if today["last_update"] else "--:--:--"
            ),
            "next_update": (
                today["next_update"].strftime("%H:%M:%S")
                if today["next_update"] else "--:--:--"
            ),
            "web_port": self.port,
        }
        self.stats_cache = {"time": now, "data": stats}
        return stats

    # -- handler ----------------------------------------------------------
    def _make_handler(self):
        web = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):  # quieter logs
                pass

            def _send_json(self, obj, status=200):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, html):
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                path = parsed.path

                if path == "/":
                    self._send_html(web.web_ui())
                elif path == "/api/flights":
                    self._send_json(web.api_flights(params))
                elif path == "/api/search":
                    self._send_json(web.api_search(params))
                elif path == "/api/alerts":
                    self._send_json(web.api_alerts())
                elif path == "/api/stats":
                    self._send_json(web.get_stats())
                elif path == "/api/airlines":
                    self._send_json(web.api_airlines())
                elif path == "/api/stream":
                    self._handle_stream()
                else:
                    self._send_json({"error": "Not found"}, status=404)

            def _handle_stream(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                try:
                    while not web.stop_event.is_set():
                        payload = json.dumps({
                            "type": "update",
                            "alerts": web.alert_manager.get_active(),
                            "stats": web.get_stats(),
                        }, ensure_ascii=False)
                        self.wfile.write(("data: {}\n\n".format(payload)).encode("utf-8"))
                        self.wfile.flush()
                        time.sleep(5)
                except Exception:
                    pass

        return Handler

    # -- api methods ------------------------------------------------------
    def api_flights(self, params):
        date_str = params.get("date", [today_str()])[0]
        flight_type = params.get("type", ["all"])[0]
        terminal = params.get("terminal", [""])[0]
        status = params.get("status", [""])[0]

        records = flights_for_date(self.api, date_str, flight_type)
        if terminal:
            records = [r for r in records if r.get("terminal", "").lower() == terminal.lower()]
        if status:
            records = [r for r in records if status.lower() == r.get("status_category", "")]

        return {
            "date": date_str,
            "count": len(records),
            "flights": records,
        }

    def api_search(self, params):
        fn = params.get("flight", [""])[0]
        date_str = params.get("date", [None])[0]
        results = search_flights(self.api, fn, date_str)
        return {"query": fn, "count": len(results), "results": results}

    def api_alerts(self):
        return {
            "active": self.alert_manager.get_active(),
            "history": self.alert_manager.get_history(),
        }

    def api_airlines(self):
        return {"count": len(self.api.fetch_airlines()), "airlines": self.api.fetch_airlines()}

    # -- web ui -----------------------------------------------------------
    def web_ui(self):
        return WEB_UI


WEB_UI = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>✈ HKG Flight Data</title>
<style>
:root{--bg:#0f1923;--panel:#16222e;--border:rgba(255,255,255,.1);--text:#e6edf3;--muted:#8fa4c4;--accent:#faa718;--ok:#4ade80;--warn:#f59e0b;--bad:#ef4444}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;padding:18px}
h1{color:var(--accent);text-align:center;font-size:24px;margin-bottom:6px}
.sub{color:var(--muted);text-align:center;font-size:13px;margin-bottom:18px}
.stats{display:flex;gap:12px;justify-content:center;flex-wrap:wrap;margin-bottom:18px}
.stat{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:12px 18px;text-align:center;min-width:110px}
.stat b{display:block;font-size:24px;color:var(--accent)}
.stat span{font-size:11px;color:var(--muted)}
.alert-banner{background:rgba(250,167,24,.12);border:1px solid rgba(250,167,24,.35);color:var(--accent);border-radius:10px;padding:10px 14px;margin-bottom:18px;font-weight:600;display:none}
.alert-banner.show{display:block}
.controls{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:16px;margin-bottom:18px;display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
.controls input,.controls select{background:rgba(0,0,0,.3);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:10px;font-size:14px;width:100%}
.controls button{background:var(--accent);color:#000;border:none;border-radius:8px;padding:10px;font-weight:700;cursor:pointer;font-size:14px}
.table-wrap{background:var(--panel);border:1px solid var(--border);border-radius:14px;overflow:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
th{color:var(--muted);text-align:left;padding:10px 12px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--panel)}
td{padding:9px 12px;border-bottom:1px solid rgba(255,255,255,.04)}
tr:hover td{background:rgba(255,255,255,.03)}
.fn{color:var(--accent);font-weight:700}
.arr{background:rgba(74,222,128,.12);color:#4ade80;border-radius:10px;padding:2px 8px;font-size:11px}
.dep{background:rgba(250,167,24,.15);color:#faa718;border-radius:10px;padding:2px 8px;font-size:11px}
.status-scheduled{color:#fff}.status-gate-closed,.status-delayed{color:#facc15}
.status-boarding-soon{color:#67e8f9}.status-final-call{color:#f0abfc}
.status-boarding,.status-departed,.status-arrived,.status-landed{color:#4ade80}
.status-est{color:#facc15}.status-cancelled{color:#ef4444}
.footer{color:var(--muted);text-align:center;font-size:12px;margin-top:16px}
</style>
</head>
<body>
<h1>✈ HKG Flight Data</h1>
<div class="sub">Hong Kong International Airport · live flight information · dark mode</div>
<div class="stats" id="stats"></div>
<div class="alert-banner" id="alertBanner"></div>
<div class="controls">
  <input id="q" placeholder="Flight number (e.g. CX759)" value="">
  <input id="date" type="date" value="">
  <select id="type"><option value="all">All flights</option><option value="departure">Departures</option><option value="arrival">Arrivals</option></select>
  <select id="terminal"><option value="">All terminals</option><option value="T1">Terminal 1</option><option value="T2">Terminal 2</option></select>
  <select id="status"><option value="">All statuses</option><option value="scheduled">Scheduled</option><option value="gate closed">Gate Closed</option><option value="boarding soon">Boarding Soon</option><option value="final call">Final Call</option><option value="boarding">Boarding</option><option value="departed">Departed</option><option value="est">Est at</option><option value="delayed">Delayed</option><option value="arrived">Arrived</option><option value="landed">Landed</option><option value="cancelled">Cancelled</option></select>
  <button id="btn">Search / Filter</button>
</div>
<div class="table-wrap">
<table><thead><tr><th>TIME</th><th>FLIGHT</th><th>REG</th><th>ROUTE</th><th>STATUS</th><th>GATE/STAND</th><th>TERMINAL</th></tr></thead><tbody id="rows"></tbody></table>
</div>
<div class="footer">Auto-refresh via SSE · API: /api/flights /api/search /api/alerts /api/stats /api/airlines</div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function statusClass(c){return 'status-'+(c||'scheduled').replace(/ /g,'-')}
async function loadStats(){
  const s=await (await fetch('/api/stats')).json();
  $('stats').innerHTML=`
    <div class="stat"><b>${s.arrivals}</b><span>Arrivals</span></div>
    <div class="stat"><b>${s.departures}</b><span>Departures</span></div>
    <div class="stat"><b>${s.airlines}</b><span>Airlines</span></div>
    <div class="stat"><b>${s.alerts}</b><span>Active Alerts</span></div>
    <div class="stat"><b>${esc(s.last_update)}</b><span>Last update</span></div>`;
}
async function loadFlights(){
  const q=encodeURIComponent($('q').value.trim());
  const d=$('date').value||new Date().toISOString().slice(0,10);
  const t=$('type').value;const term=$('terminal').value;const st=$('status').value;
  let url=`/api/flights?date=${d}&type=${t}`;
  if(term)url+=`&terminal=${term}`;
  if(st)url+=`&status=${st}`;
  if(q)url=`/api/search?flight=${q}&date=${d}`;
  const data=await (await fetch(url)).json();
  const rows=q?data.results||[]:data.flights||[];
  if(!rows.length){$('rows').innerHTML='<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:20px">No flights found</td></tr>';return}
  $('rows').innerHTML=rows.map(f=>{
    const route=f.type==='arrival'?esc(f.origin||'--').replace(/\|/g,'/')+' → HKG':'HKG → '+esc(f.destination||'--').replace(/\|/g,'/');
    const gs=f.gate?'Gate '+esc(f.gate):(f.stand?'Stand '+esc(f.stand):'--');
    return `<tr>
      <td>${esc(f.time)}</td>
      <td class="fn">${esc(f.flight_number)} <span class="${f.type==='arrival'?'arr':'dep'}">${f.type==='arrival'?'ARR':'DEP'}</span></td>
      <td class="fn">${esc(f.reg||'--')}</td>
      <td>${route}</td>
      <td class="${statusClass(f.status_category)}">${esc(f.status_display)}</td>
      <td>${gs}</td>
      <td>${esc(f.terminal||'--')}</td>
    </tr>`;
  }).join('');
}
function renderAlerts(alerts){
  const b=$('alertBanner');
  if(alerts&&alerts.length){b.textContent='⚠ '+alerts.length+' active alert'+(alerts.length>1?'s':'')+': '+alerts.map(a=>a.flight_number+' '+a.field+' '+(a.old_value||'-')+'→'+(a.new_value||'-')).join(' | ');b.classList.add('show')}
  else{b.textContent='';b.classList.remove('show')}
}
$('btn').onclick=()=>{loadFlights();loadStats()};
$('q').addEventListener('keydown',e=>{if(e.key==='Enter')loadFlights()});
loadFlights();loadStats();
if(window.EventSource){const es=new EventSource('/api/stream');es.onmessage=e=>{const d=JSON.parse(e.data);renderAlerts(d.alerts);loadStats();loadFlights()}}
</script>
</body>
</html>
"""


# =========================================================================
# TUI: curses helper functions
# =========================================================================


def _setup_curses_colors(stdscr):
    """Initialize curses color pairs if supported."""
    try:
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            pairs = [
                (PAIR_SCHEDULED, curses.COLOR_WHITE),
                (PAIR_GATE_CLOSED, curses.COLOR_YELLOW),
                (PAIR_BOARDING_SOON, curses.COLOR_CYAN),
                (PAIR_FINAL_CALL, curses.COLOR_MAGENTA),
                (PAIR_BOARDING, curses.COLOR_GREEN),
                (PAIR_DEPARTED, curses.COLOR_GREEN),
                (PAIR_EST, curses.COLOR_YELLOW),
                (PAIR_DELAYED, curses.COLOR_RED),
                (PAIR_ARRIVED, curses.COLOR_GREEN),
                (PAIR_LANDED, curses.COLOR_GREEN),
                (PAIR_CANCELLED, curses.COLOR_RED),
                (PAIR_HEADER, curses.COLOR_CYAN),
                (PAIR_ACCENT, curses.COLOR_YELLOW),
            ]
            for pair_id, fg in pairs:
                curses.init_pair(pair_id, fg, -1)
    except Exception:
        pass


def _attr(pair_id, dim=False):
    """Build a curses attribute for a color pair."""
    attr = curses.color_pair(pair_id)
    if dim:
        attr |= curses.A_DIM
    return attr


# =========================================================================
# TUI: curses application
# =========================================================================


class CursesTUI(object):
    """Interactive terminal UI built with curses."""

    def __init__(self, stdscr, poller, api, alert_manager, web_server):
        self.stdscr = stdscr
        self.poller = poller
        self.api = api
        self.alert_manager = alert_manager
        self.web_server = web_server

        self.running = True
        self.mode = "departures"          # departures/arrivals/date/search/alerts/airlines
        self.view_date = poller.today_date
        self.current_flights = []
        self.airlines = []
        self.filter_text = ""
        self.page = 0
        self.scroll = 0
        self.message = ""
        self.message_until = 0.0
        self.flash_until = 0.0
        self.prompt_active = False

        self.last_render = 0.0

    # -- setup ------------------------------------------------------------
    def start(self):
        _setup_curses_colors(self.stdscr)
        try:
            curses.curs_set(0)
        except Exception:
            pass
        self.stdscr.timeout(5000)
        self.stdscr.keypad(True)

    # -- view helpers -----------------------------------------------------
    def load_view(self):
        """Refresh the current view's flight list from the shared state."""
        if self.mode == "departures" or self.mode == "arrivals":
            today = self.poller.get_today()
            self.view_date = today["date"]
            if self.mode == "departures":
                self.current_flights = today["departures"]
            else:
                self.current_flights = today["arrivals"]
        elif self.mode == "airlines":
            self.airlines = load_airlines(self.api)
            self.current_flights = []
        # date/search/alerts modes keep the loaded list.

    def visible_flights(self):
        if self.mode in ("alerts", "airlines"):
            return []
        return filter_records(self.current_flights, self.filter_text)

    def page_count(self):
        flights = self.visible_flights()
        if not flights:
            return 1
        return (len(flights) + PAGE_SIZE - 1) // PAGE_SIZE

    def clamp_page(self):
        max_page = max(1, self.page_count())
        self.page = max(0, min(self.page, max_page - 1))
        self.scroll = max(0, min(self.scroll, PAGE_SIZE - 1))

    # -- rendering --------------------------------------------------------
    def render(self):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        if h < 6 or w < 30:
            self.stdscr.addstr(0, 0, "Terminal too small")
            self.stdscr.refresh()
            return

        # Header
        alerts = self.alert_manager.active_count()
        if time.time() < self.flash_until:
            header_attr = _attr(PAIR_HEADER) | curses.A_REVERSE
        else:
            header_attr = _attr(PAIR_HEADER)
        web_state = "WEB:ON" if self.web_server.running() else "WEB:OFF"
        title = " ✈ HKG Flight Data — {}  [ALERTS: {}] {}  ".format(
            self.view_date, alerts, web_state
        )
        self._add(0, 0, title, header_attr)

        # Stats line
        today = self.poller.get_today()
        stats = " Arrivals: {} | Departures: {} | Airlines: {} | Last: {} | Next: {}".format(
            len(today["arrivals"]), len(today["departures"]),
            len(load_airlines(self.api)), format_time(today["last_update"]),
            format_time(today["next_update"])
        )
        self._add(1, 0, stats[: w - 1], curses.A_DIM)

        # Menu bar
        menu = " [1]Search [2]Date [3]Departures [4]Arrivals [5]Alerts [6]Airlines [W]Web [Q]Quit "
        self._add(2, 0, menu, _attr(PAIR_ACCENT))

        # Filter / message line
        if self.filter_text:
            info = " Filter: {} (Esc clear) ".format(self.filter_text)
        elif self.message and time.time() < self.message_until:
            info = " {}".format(self.message)
        else:
            info = " Type to filter when a list is shown "
        self._add(3, 0, info, _attr(PAIR_HEADER))

        # Separator
        self._add(4, 0, "-" * max(1, w - 1), curses.A_DIM)

        y = 5
        if self.mode == "alerts":
            self._render_alerts(y, h, w)
        elif self.mode == "airlines":
            self._render_airlines(y, h, w)
        else:
            self._render_flights(y, h, w)

        self.stdscr.refresh()
        self.last_render = time.time()

    def _add(self, y, x, text, attr=None):
        """Safe addstr that never exceeds the screen."""
        h, w = self.stdscr.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        text = str(text)[: max(0, w - x - 1)]
        try:
            self.stdscr.addstr(y, x, text, attr if attr is not None else curses.A_NORMAL)
        except Exception:
            pass

    def _render_flights(self, y, h, w):
        flights = self.visible_flights()
        self.clamp_page()
        page_start = self.page * PAGE_SIZE
        page_end = min(page_start + PAGE_SIZE, len(flights))
        if len(flights) == 0:
            self._add(y, 0, " (no flights match)", _attr(PAIR_SCHEDULED))
            y += 1
        else:
            header = " {:>5}  {:<9} {:<7} {:<22} {:<18} {:<12}".format(
                "TIME", "FLIGHT", "REG", "ROUTE", "STATUS", "GATE/STAND"
            )
            self._add(y, 0, header, _attr(PAIR_HEADER))
            y += 1
            self._add(y, 0, " " + "-" * max(10, w - 3), curses.A_DIM)
            y += 1

            available = max(0, h - y - 2)  # leave footer space
            scroll = self.scroll
            end = min(page_end, page_start + scroll + available)
            start = min(page_start + scroll, end)
            if available <= 0:
                available = 1

            for idx in range(start, end):
                rec = flights[idx]
                status_cat = rec.get("status_category", "scheduled")
                status_disp = rec.get("status_display", "○ Scheduled")
                route = route_text(rec)
                gs = gate_stand_text(rec)
                reg = rec.get("reg", "") or "-"
                line = " {:>5}  {:<9} {:<7} {:<22} {:<18} {:<12}".format(
                    format_raw_time(rec.get("time")), rec.get("flight_number", ""),
                    reg, route, status_disp, gs
                )
                attr = _attr(status_pair(status_cat), dim=status_cat in ("departed", "landed"))
                if idx == page_start + scroll:
                    attr |= curses.A_REVERSE
                self._add(y, 0, line, attr)
                y += 1

            if len(flights) > PAGE_SIZE:
                page_info = " ◄ {}/{} ►  Page {}/{}  (←/→ page ↑/↓ scroll) ".format(
                    self.page + 1, self.page_count(), self.page + 1, self.page_count()
                )
            else:
                page_info = " Page 1/1 "
            self._add(h - 1, 0, page_info, _attr(PAIR_ACCENT))

    def _render_alerts(self, y, h, w):
        active = self.alert_manager.get_active()
        if not active:
            self._add(y, 0, " No active alerts", _attr(PAIR_SCHEDULED))
            return
        available = h - y - 1
        for i, alert in enumerate(active[:max(0, available)]):
            line = " ⚠ {}  {} CHANGE: {} → {}".format(
                alert["flight_number"], alert["field"],
                alert.get("old_value") or "-", alert.get("new_value") or "-"
            )
            self._add(y, 0, line, _attr(PAIR_FINAL_CALL))
            y += 1
            line = "    Status: {} | {} | {}".format(
                alert.get("status", ""), alert.get("time", ""),
                alert.get("raised_at", "")
            )
            self._add(y, 0, line, curses.A_DIM)
            y += 1
        if len(active) > available:
            self._add(h - 1, 0, " Press any key to return, or Esc ", _attr(PAIR_ACCENT))

    def _render_airlines(self, y, h, w):
        airlines = self.airlines
        if not airlines:
            self._add(y, 0, " No airline data available", _attr(PAIR_SCHEDULED))
            return
        available = h - y - 1
        for row in airlines[:max(0, available)]:
            if not isinstance(row, dict):
                continue
            code = row.get("code", "")
            desc = row.get("description") or []
            name = desc[0] if isinstance(desc, list) and desc else ""
            self._add(y, 0, " {:<6} {}".format(code, name), _attr(PAIR_SCHEDULED))
            y += 1
        if len(airlines) > available:
            self._add(h - 1, 0, " More airlines below (page not needed) ", _attr(PAIR_ACCENT))

    # -- command handlers -------------------------------------------------
    def prompt(self, label):
        """Blocking one-line input prompt. Returns string or None on Esc."""
        self.prompt_active = True
        h, w = self.stdscr.getmaxyx()
        old_timeout = 5000
        try:
            self.stdscr.timeout(-1)
            curses.echo()
            curses.curs_set(1)
            result = None
            buf = ""
            while True:
                prompt_text = " {}: {}".format(label, buf)
                self._add(h - 1, 0, prompt_text + " " * max(1, w - len(prompt_text) - 1), _attr(PAIR_ACCENT))
                # Clear previous line content beyond cursor.
                self.stdscr.clrtoeol()
                self.stdscr.move(h - 1, min(w - 1, len(prompt_text)))
                self.stdscr.refresh()
                ch = self.stdscr.getch()
                if ch in (10, 13):
                    result = buf
                    break
                elif ch == 27:
                    result = None
                    break
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    buf = buf[:-1]
                elif 32 <= ch < 127:
                    buf += chr(ch)
            curses.noecho()
            curses.curs_set(0)
            self.stdscr.timeout(5000)
            return result
        except Exception:
            try:
                curses.noecho()
                curses.curs_set(0)
                self.stdscr.timeout(5000)
            except Exception:
                pass
            return None
        finally:
            self.prompt_active = False

    def cmd_search(self):
        fn = self.prompt("Search flight number")
        if not fn:
            return
        self.message = "Searching {}...".format(fn)
        self.message_until = time.time() + 2
        results = search_flights(self.api, fn, None)
        self.current_flights = results
        self.mode = "search"
        self.view_date = self.poller.today_date
        self.filter_text = ""
        self.page = 0
        self.scroll = 0
        if results:
            self.message = "{} result(s) for {}".format(len(results), fn.upper())
        else:
            self.message = "No results for {}".format(fn.upper())
        self.message_until = time.time() + 3

    def cmd_date(self):
        date_str = self.prompt("Date (YYYY-MM-DD)")
        if not date_str:
            return
        date_str = date_str.strip()
        try:
            date.fromisoformat(date_str)
        except Exception:
            self.message = "Invalid date. Use YYYY-MM-DD."
            self.message_until = time.time() + 3
            return
        self.message = "Loading {}...".format(date_str)
        self.message_until = time.time() + 2
        records = flights_for_date(self.api, date_str, "all")
        self.current_flights = records
        self.mode = "date"
        self.view_date = date_str
        self.filter_text = ""
        self.page = 0
        self.scroll = 0
        self.message = "{} flight(s) on {}".format(len(records), date_str)
        self.message_until = time.time() + 3

    def cmd_alerts(self):
        self.mode = "alerts"
        self.filter_text = ""
        self.page = 0
        self.scroll = 0

    def cmd_airlines(self):
        self.mode = "airlines"
        self.filter_text = ""
        self.airlines = load_airlines(self.api)
        self.page = 0
        self.scroll = 0

    def cmd_web(self):
        if self.web_server.running():
            self.web_server.stop()
            self.message = "Web server stopped"
        else:
            if self.web_server.start():
                self.message = "Web server running at http://localhost:{}".format(self.web_server.port)
            else:
                self.message = "Failed to start web server on port {}".format(self.web_server.port)
        self.message_until = time.time() + 4

    def set_mode(self, mode):
        self.mode = mode
        self.filter_text = ""
        self.page = 0
        self.scroll = 0
        self.load_view()

    # -- key handling -----------------------------------------------------
    def handle_key(self, ch):
        if ch == curses.KEY_RESIZE:
            self.render()
            return

        # In list views an active filter consumes printable characters so
        # typing a flight number like "CX759" does not trigger menu keys.
        list_mode = self.mode in ("departures", "arrivals", "date", "search")
        if list_mode and self.filter_text and 32 <= ch < 127:
            self.filter_text += chr(ch)
            self.page = 0
            self.scroll = 0
            return

        # Global numeric / letter menu keys (only when no filter is active).
        if ch == ord("1"):
            self.cmd_search()
            return
        if ch == ord("2"):
            self.cmd_date()
            return
        if ch in (ord("3"),):
            self.set_mode("departures")
            return
        if ch in (ord("4"),):
            self.set_mode("arrivals")
            return
        if ch in (ord("5"),):
            self.cmd_alerts()
            return
        if ch in (ord("6"),):
            self.cmd_airlines()
            return
        if ch in (ord("W"), ord("w")):
            self.cmd_web()
            return
        if ch in (ord("Q"), ord("q")):
            self.running = False
            return

        # Back navigation from alerts/airlines.
        if self.mode in ("alerts", "airlines"):
            if ch == 27 or ch in (ord("0"),):
                self.set_mode("departures")
            return

        # List views: pagination / scrolling / filtering.
        if list_mode:
            flights = self.visible_flights()
            if ch == curses.KEY_LEFT:
                if self.page > 0:
                    self.page -= 1
                    self.scroll = 0
                return
            if ch == curses.KEY_RIGHT:
                if self.page < self.page_count() - 1:
                    self.page += 1
                    self.scroll = 0
                return
            if ch == curses.KEY_UP:
                if self.scroll > 0:
                    self.scroll -= 1
                return
            if ch == curses.KEY_DOWN:
                if flights and self.scroll < min(PAGE_SIZE, len(flights)) - 1:
                    self.scroll += 1
                return
            if ch == curses.KEY_HOME:
                self.page = 0
                self.scroll = 0
                return
            if ch == curses.KEY_END:
                self.page = max(0, self.page_count() - 1)
                self.scroll = 0
                return
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                if self.filter_text:
                    self.filter_text = self.filter_text[:-1]
                    self.page = 0
                    self.scroll = 0
                return
            if ch == 27:
                if self.filter_text:
                    self.filter_text = ""
                    self.page = 0
                    self.scroll = 0
                return
            if 32 <= ch < 127:
                self.filter_text += chr(ch)
                self.page = 0
                self.scroll = 0
                return

    # -- main loop --------------------------------------------------------
    def run(self):
        self.start()
        self.load_view()
        while self.running:
            self.render()

            # Flash header for a short time after new alerts are raised.
            if self.poller.consume_new_alert_flag():
                self.flash_until = time.time() + 3

            ch = self.stdscr.getch()
            if ch == -1:
                continue
            self.handle_key(ch)

        try:
            self.stdscr.clear()
            self.stdscr.refresh()
        except Exception:
            pass


# =========================================================================
# TUI: simple fallback (when curses is unavailable / Windows without it)
# =========================================================================


def _enable_ansi_windows():
    """Enable ANSI/VT100 escape sequences on Windows 10+."""
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # STD_OUTPUT_HANDLE = -11
        handle = kernel32.GetStdHandle(-11)
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _colored(text, ansi_code):
    """Wrap text in ANSI color if available, else return plain."""
    if not ansi_code:
        return text
    try:
        return "{}{}{}".format(ansi_code, text, RESET)
    except Exception:
        return text


# Cross-platform single key press reader
try:
    import msvcrt
    def _getch():
        """Read a single keypress on Windows (returns str)."""
        ch = msvcrt.getwch()
        if ch in ('\x00', '\xe0'):  # Special key prefix
            ch2 = msvcrt.getwch()
            mapping = {
                'H': 'UP', 'P': 'DOWN', 'K': 'LEFT', 'M': 'RIGHT',
                'S': 'END', 'G': 'HOME',
            }
            return mapping.get(ch2, '')
        if ch == '\r':
            return 'ENTER'
        if ch == '\x1b':
            return 'ESC'
        if ch == '\x08':
            return 'BACKSPACE'
        return ch
except ImportError:
    import tty, termios
    def _getch():
        """Read a single keypress on Unix (returns str)."""
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    mapping = {'A': 'UP', 'B': 'DOWN', 'C': 'RIGHT', 'D': 'LEFT',
                               'F': 'END', 'H': 'HOME'}
                    return mapping.get(ch3, '')
                return 'ESC'
            if ch in ('\r', '\n'):
                return 'ENTER'
            if ch == '\x7f':
                return 'BACKSPACE'
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def run_simple_tui(poller, api, alert_manager, web_server):
    """Plain-print menu fallback for terminals without curses."""
    _enable_ansi_windows()
    mode = "departures"
    filter_text = ""
    page = 0
    cursor = 0  # cursor position within visible page
    running = True
    detail_flight = None  # if set, show this flight's details

    def clear():
        if os.name == "nt":
            os.system("cls")
        else:
            os.system("clear")

    while running:
        clear()
        today = poller.get_today()
        alerts = alert_manager.active_count()
        web = web_server.running()

        # Header with accent color
        hdr = "  ✈ HKG Flight Data — {}  [ALERTS: {}]  [WEB: {}]".format(
            today["date"], alerts, "ON" if web else "OFF")
        print(_colored("=" * 62, SIMPLE_COLORS[PAIR_HEADER]))
        print(_colored(hdr, SIMPLE_COLORS[PAIR_ACCENT]))
        print(_colored("=" * 62, SIMPLE_COLORS[PAIR_HEADER]))

        # Stats
        stats_line = "  Arrivals: {} | Departures: {} | Airlines: {}".format(
            len(today["arrivals"]), len(today["departures"]), len(load_airlines(api)))
        print(stats_line)
        print("  Last update: {}".format(format_time(today["last_update"])))

        # Menu
        print(_colored("-" * 62, SIMPLE_COLORS[PAIR_HEADER]))
        print(_colored("  [1] Search Flight   [2] By Date   [3] Departures", SIMPLE_COLORS[PAIR_ACCENT]))
        print(_colored("  [4] Arrivals        [5] Alerts    [6] Airlines", SIMPLE_COLORS[PAIR_ACCENT]))
        print(_colored("  [W] Web Server      [Q] Quit", SIMPLE_COLORS[PAIR_ACCENT]))
        print(_colored("-" * 62, SIMPLE_COLORS[PAIR_HEADER]))

        if mode == "alerts":
            active = alert_manager.get_active()
            if not active:
                print("  No active alerts")
            for a in active:
                print(_colored("  ⚠ {} {}: {} → {}".format(
                    a["flight_number"], a["field"], a.get("old_value") or "-",
                    a.get("new_value") or "-"), SIMPLE_COLORS[PAIR_DELAYED]))
                print("    Status: {} | {}".format(a.get("status"), a.get("raised_at", "")))
        elif mode == "airlines":
            airlines = load_airlines(api)
            for row in airlines[:50]:
                desc = row.get("description") or []
                name = desc[0] if isinstance(desc, list) and desc else ""
                print("  {:<6} {}".format(row.get("code", ""), name))
            if len(airlines) > 50:
                print("  ... and {} more".format(len(airlines) - 50))
        else:
            records = {"departures": today["departures"], "arrivals": today["arrivals"]}.get(mode, [])
            records = filter_records(records, filter_text)
            start = page * PAGE_SIZE
            chunk = records[start:start + PAGE_SIZE]

            # Clamp cursor
            if cursor >= len(chunk):
                cursor = max(0, len(chunk) - 1)

            # Column header
            print(_colored("  {:<2} {:<5} {:<10} {:<8} {:<22} {:<18} {:<12}".format(
                "", "TIME", "FLIGHT", "REG", "ROUTE", "STATUS", "GATE/STAND"),
                SIMPLE_COLORS[PAIR_HEADER]))
            print(_colored("  " + "-" * 79, SIMPLE_COLORS[PAIR_HEADER]))

            for i, rec in enumerate(chunk):
                status_cat = rec.get("status_category", "scheduled")
                status_disp = rec.get("status_display", "")
                marker = " ►" if i == cursor else "  "
                line = "{}{:<5} {:<10} {:<8} {:<22} {:<18} {:<12}".format(
                    marker,
                    format_raw_time(rec.get("time")), rec.get("flight_number", ""),
                    rec.get("reg", "") or "-",
                    route_text(rec), status_disp, gate_stand_text(rec))
                if i == cursor:
                    print(_colored(line, SIMPLE_COLORS[PAIR_ACCENT]))
                else:
                    print(_colored(line, SIMPLE_COLORS.get(status_cat, "")))

            total_pages = max(1, (len(records) + PAGE_SIZE - 1) // PAGE_SIZE)
            print(_colored("-" * 62, SIMPLE_COLORS[PAIR_HEADER]))
            print(_colored("  Page {}/{} | Filter: {} | Cursor: {}/{}".format(
                page + 1, total_pages, filter_text or "(none)",
                cursor + 1, len(chunk)), SIMPLE_COLORS[PAIR_ACCENT]))

        print("-" * 62)
        print("  [←/→] Page  [↑/↓] Scroll  [N/P] Next/Prev page  [Esc] Clear filter")
        print("  Type to filter  |  Commands: 1-6, W, Q")

        # Read single keypress
        key = _getch()

        # Arrow keys / navigation
        if key == "LEFT":
            if page > 0:
                page -= 1
                cursor = 0
        elif key == "RIGHT":
            total_pages = max(1, (len(filter_records(
                {"departures": today["departures"], "arrivals": today["arrivals"]}.get(mode, []),
                filter_text)) + PAGE_SIZE - 1) // PAGE_SIZE)
            if page < total_pages - 1:
                page += 1
                cursor = 0
        elif key == "UP":
            if cursor > 0:
                cursor -= 1
            elif page > 0:
                page -= 1
                cursor = PAGE_SIZE - 1
        elif key == "DOWN":
            records = {"departures": today["departures"], "arrivals": today["arrivals"]}.get(mode, [])
            records = filter_records(records, filter_text)
            chunk = records[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
            if cursor < len(chunk) - 1:
                cursor += 1
            else:
                total_pages = max(1, (len(records) + PAGE_SIZE - 1) // PAGE_SIZE)
                if page < total_pages - 1:
                    page += 1
                    cursor = 0
        elif key == "ENTER":
            # Show detail view for selected flight
            records = {"departures": today["departures"], "arrivals": today["arrivals"]}.get(mode, [])
            records = filter_records(records, filter_text)
            chunk = records[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
            if chunk and cursor < len(chunk):
                detail_flight = chunk[cursor]
                clear()
                print_flight_details(detail_flight)
                print()
                print("  Press any key to return...")
                _getch()
                detail_flight = None
        elif key == "HOME":
            page = 0
            cursor = 0
        elif key == "END":
            total_pages = max(1, (len(filter_records(
                {"departures": today["departures"], "arrivals": today["arrivals"]}.get(mode, []),
                filter_text)) + PAGE_SIZE - 1) // PAGE_SIZE)
            page = total_pages - 1
            cursor = 0
        elif key == "ESC":
            filter_text = ""
            page = 0
            cursor = 0
        elif key == "BACKSPACE":
            if filter_text:
                filter_text = filter_text[:-1]
                page = 0
                cursor = 0
        elif key == "N" and mode in ("departures", "arrivals"):
            page += 1
            cursor = 0
        elif key == "P" and mode in ("departures", "arrivals") and page > 0:
            page -= 1
            cursor = 0
        # Menu commands
        elif key == "1":
            fn = input("  Flight number: ").strip()
            if fn:
                results = search_flights(api, fn, None)
                filter_text = ""
                mode = "departures"
                page = 0
                cursor = 0
                print("  {} result(s)".format(len(results)))
                for rec in results[:10]:
                    print("  {} {} {}  {}".format(rec["date"], rec["time"],
                                                  rec["flight_number"], rec["status_display"]))
                input("  Press Enter...")
        elif key == "2":
            d = input("  Date (YYYY-MM-DD): ").strip()
            if d:
                records = flights_for_date(api, d, "all")
                mode = "departures"
                filter_text = ""
                page = 0
                cursor = 0
                print("  {} flight(s)".format(len(records)))
                for rec in sorted(records, key=lambda r: r["time"])[:10]:
                    print("  {} {} {}  {}".format(rec["date"], rec["time"],
                                                  rec["flight_number"], rec["status_display"]))
                input("  Press Enter...")
        elif key == "3":
            mode = "departures"; filter_text = ""; page = 0; cursor = 0
        elif key == "4":
            mode = "arrivals"; filter_text = ""; page = 0; cursor = 0
        elif key == "5":
            mode = "alerts"
        elif key == "6":
            mode = "airlines"
        elif key.upper() == "W":
            if web_server.running():
                web_server.stop()
                print("  Web server stopped")
            else:
                if web_server.start():
                    print("  Web server running at http://localhost:{}".format(web_server.port))
                else:
                    print("  Web server failed to start")
            input("  Press Enter...")
        elif key.upper() == "Q":
            break
        elif len(key) == 1 and key.isprintable() and mode in ("departures", "arrivals"):
            filter_text += key.lower()
            page = 0
            cursor = 0


# =========================================================================
# TUI entry point
# =========================================================================


def start_tui(poller, api, alert_manager, web_server):
    """Start the curses TUI, or fall back to the simple text UI."""
    if curses is None:
        log("curses not available (pip install windows-curses for full TUI), using simple mode")
        run_simple_tui(poller, api, alert_manager, web_server)
        return

    def _main(stdscr):
        app = CursesTUI(stdscr, poller, api, alert_manager, web_server)
        app.run()

    try:
        curses.wrapper(_main)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        log("curses TUI failed: {}, falling back to simple mode".format(exc))
        try:
            run_simple_tui(poller, api, alert_manager, web_server)
        except Exception:
            pass


# =========================================================================
# CLI helpers
# =========================================================================


def print_flight_details(rec, index=None):
    direction = "ARR" if rec.get("type") == "arrival" else "DEP"
    status_cat = rec.get("status_category", "scheduled")
    print(_colored("=" * 60, SIMPLE_COLORS[PAIR_HEADER]))
    if index is not None:
        print(_colored("  [{}/{}] {} ({})  {}/{}".format(
            index[0], index[1], rec.get("flight_number", ""), direction,
            rec.get("date", ""), rec.get("time", "")), SIMPLE_COLORS[PAIR_ACCENT]))
    else:
        print(_colored("  {} ({})  {}/{}".format(
            rec.get("flight_number", ""), direction,
            rec.get("date", ""), rec.get("time", "")), SIMPLE_COLORS[PAIR_ACCENT]))
    print("  Route:   {}".format(route_text(rec)))
    print(_colored("  Status:  {}  [{}]".format(
        rec.get("status", ""), rec.get("status_display", "")),
        SIMPLE_COLORS.get(status_cat, "")))
    # Registration / tail number
    reg = rec.get("reg", "")
    ac_type = rec.get("aircraft_type", "")
    if reg or ac_type:
        print(_colored("  Reg:     {}  ({})".format(reg or "-", ac_type or "-"),
                       SIMPLE_COLORS[PAIR_ACCENT]))
    print("  Terminal: {}".format(rec.get("terminal") or "-"))
    if rec.get("type") == "arrival":
        print("  Stand:   {}".format(rec.get("stand") or "-"))
        print("  Hall:    {}".format(rec.get("hall") or "-"))
        print("  Belt:    {}".format(rec.get("belt") or "-"))
    else:
        print("  Gate:    {}".format(rec.get("gate") or "-"))
        print("  Aisle:   {}".format(rec.get("aisle") or "-"))
    codeshares = [x for x in rec.get("all_flight_numbers", "").split("|") if x]
    if len(codeshares) > 1:
        print("  Codeshares: {}".format(", ".join(codeshares)))


def print_flight_table(records, title):
    _enable_ansi_windows()
    print(_colored("{} — {} flight(s)".format(title, len(records)), SIMPLE_COLORS[PAIR_ACCENT]))
    print(_colored("{:<5} {:<10} {:<8} {:<24} {:<20} {:<12} {:<6}".format(
        "TIME", "FLIGHT", "REG", "ROUTE", "STATUS", "GATE/STAND", "TERM"),
        SIMPLE_COLORS[PAIR_HEADER]))
    print(_colored("-" * 87, SIMPLE_COLORS[PAIR_HEADER]))
    for rec in records:
        status_cat = rec.get("status_category", "scheduled")
        print(_colored("{:<5} {:<10} {:<8} {:<24} {:<20} {:<12} {:<6}".format(
            format_raw_time(rec.get("time")), rec.get("flight_number", ""),
            rec.get("reg", "") or "-",
            route_text(rec), rec.get("status_display", ""),
            gate_stand_text(rec), rec.get("terminal") or "-"),
            SIMPLE_COLORS.get(status_cat, "")))


def cmd_query(api, args):
    if not args:
        print("Usage: python hkg_flight.py query CX759 [YYYY-MM-DD]")
        return 1
    fn = args[0]
    date_str = args[1] if len(args) > 1 else None
    results = search_flights(api, fn, date_str)
    if not results:
        print("No results for {}".format(fn))
        return 1
    for i, rec in enumerate(results):
        print_flight_details(rec, index=(i + 1, len(results)))
    print("=" * 60)
    print("Total: {} result(s)".format(len(results)))
    return 0


def cmd_departures(api, args):
    date_str = args[0] if args else today_str()
    records = flights_for_date(api, date_str, "departure")
    print_flight_table(records, "Departures {}".format(date_str))
    return 0


def cmd_arrivals(api, args):
    date_str = args[0] if args else today_str()
    records = flights_for_date(api, date_str, "arrival")
    print_flight_table(records, "Arrivals {}".format(date_str))
    return 0


def cmd_alerts(alert_manager):
    active = alert_manager.get_active()
    if not active:
        print("No active alerts.")
        return 0
    print("Active alerts: {}".format(len(active)))
    for a in active:
        print("⚠ {} {} change: {} → {} | status: {} | raised: {}".format(
            a["flight_number"], a["field"], a.get("old_value") or "-",
            a.get("new_value") or "-", a.get("status"), a.get("raised_at")))
    return 0


def print_usage():
    print("HKG Flight Data v3")
    print()
    print("Usage:")
    print("  python hkg_flight.py                     # Start TUI (default)")
    print("  python hkg_flight.py --web [--port N]    # Start web server")
    print("  python hkg_flight.py --no-poll           # TUI without live polling")
    print("  python hkg_flight.py query CX759         # Search flight")
    print("  python hkg_flight.py query CX759 2026-08-16")
    print("  python hkg_flight.py departures [DATE]")
    print("  python hkg_flight.py arrivals [DATE]")
    print("  python hkg_flight.py alerts")


# =========================================================================
# Main entry point
# =========================================================================


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    # Fix Windows console encoding for Unicode characters (✈, ⚠, etc.)
    if os.name == "nt":
        try:
            import io
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Shared backend objects.
    cache = CacheSystem()
    api = APIClient(cache)
    alert_manager = AlertManager(cache)
    poller = Poller(cache, api, alert_manager, poll_interval=DEFAULT_POLL_INTERVAL)

    # TUI options
    no_poll = "--no-poll" in argv
    web_only = "--web" in argv
    port = DEFAULT_WEB_PORT
    if "--port" in argv:
        try:
            idx = argv.index("--port")
            port = int(argv[idx + 1])
        except Exception:
            port = DEFAULT_WEB_PORT

    if not argv:
        poller.enabled = not no_poll
        # Always do a synchronous fetch first so the TUI has data to show
        print("Loading flight data...")
        poller.refresh_today()
        poller.start()
        web_server = WebServer(poller, api, alert_manager, port=port)
        start_tui(poller, api, alert_manager, web_server)
        poller.stop()
        web_server.stop()
        return 0

    # CLI one-shot commands
    cmd = argv[0]
    if cmd == "query":
        poller.stop()
        return cmd_query(api, argv[1:])
    if cmd == "departures":
        poller.stop()
        return cmd_departures(api, argv[1:])
    if cmd == "arrivals":
        poller.stop()
        return cmd_arrivals(api, argv[1:])
    if cmd == "alerts":
        poller.stop()
        return cmd_alerts(alert_manager)

    # Web-only mode
    if web_only:
        poller.enabled = not no_poll
        if no_poll:
            poller.refresh_today()
        poller.start()
        web_server = WebServer(poller, api, alert_manager, port=port)
        if not web_server.start():
            print("Could not start web server on port {}".format(port))
            poller.stop()
            return 1
        print("✈ HKG Flight Data web server")
        print("  http://localhost:{}".format(port))
        print("  Press Ctrl+C to stop")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            web_server.stop()
            poller.stop()
        return 0

    print_usage()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)