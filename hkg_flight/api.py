"""
HKG Flight Data v3 - API Client.

Talks to the HKIA REST API with polite rate limiting. The timing decision is
serialized, so concurrent callers (the poller, the airline loader, web queries)
cannot all observe the same free slot and collectively exceed the interval.
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .utils import log, validate_date


API_BASE = "https://www.hongkongairport.com/flightinfo-rest/rest"

REQUEST_TIMEOUT = 15


class APIClient:
    """HKIA REST client with rate limiting and cache-backed fallback."""

    def __init__(self, cache=None, min_interval=0.6,
                 airlines_cache_hours=24, bypass_cache=False):
        self.cache = cache
        self.min_interval = min_interval
        self.airlines_cache_hours = airlines_cache_hours
        self.bypass_cache = bypass_cache
        self._last_call = 0.0
        self._rate_lock = threading.Lock()

    # -- transport -------------------------------------------------------
    def _rate_limit(self):
        """Sleep just long enough to keep the minimum interval between calls."""
        with self._rate_lock:
            wait = self.min_interval - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()

    def _get_json(self, url):
        """GET ``url`` and parse JSON; None on any failure."""
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "HKGFlightData/3.0")
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            log(f"HTTP {exc.code} for {url}")
            return None
        except Exception as exc:
            log(f"request failed {url}: {exc}")
            return None

    # -- flights ---------------------------------------------------------
    def fetch_flights(self, date_str):
        """Raw flight data for one date, or None on failure.

        A successful response is written through to the cache, so a later
        failure can still be served from disk.
        """
        if not validate_date(date_str):
            log(f"Invalid date format: {date_str}")
            return None

        self._rate_limit()
        params = urllib.parse.urlencode({"date": date_str, "span": "1"})
        data = self._get_json(f"{API_BASE}/flights?{params}")
        if data is not None and self.cache is not None:
            self.cache.write_flights(date_str, data)
        return data

    # -- airlines --------------------------------------------------------
    def fetch_airlines_meta(self):
        """Airline metadata plus how it was obtained.

        Returns ``{"airlines": list, "source": "api"|"cache"|"none",
        "ok": bool, "error": str|None}`` so the UI can tell "loaded empty"
        apart from "failed to load".
        """
        use_cache = self.cache is not None and not self.bypass_cache
        if use_cache:
            cached = self.cache.read_airlines()
            if cached:
                age = self.cache.cache_age_minutes(self.cache.airlines_path)
                if 0 <= age < self.airlines_cache_hours * 60:
                    return {"airlines": cached, "source": "cache",
                            "ok": True, "error": None}

        self._rate_limit()
        data = self._get_json(f"{API_BASE}/airlines")
        if data is not None:
            airlines = data if isinstance(data, list) else []
            if self.cache is not None:
                self.cache.write_airlines(airlines)
            return {"airlines": airlines, "source": "api", "ok": True, "error": None}

        if use_cache:
            fallback = self.cache.read_airlines()
            if fallback:
                return {"airlines": fallback, "source": "cache",
                        "ok": True, "error": "api_failed"}
        return {"airlines": [], "source": "none", "ok": False, "error": "api_failed"}

    def fetch_airlines(self):
        """Airline metadata as a plain list (empty on failure)."""
        return self.fetch_airlines_meta()["airlines"]
