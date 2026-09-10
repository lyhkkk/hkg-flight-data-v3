"""
HKG Flight Data v3 - API Client Module
Handles communication with the HKIA flight API.
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .utils import log, validate_date


API_BASE = "https://www.hongkongairport.com/flightinfo-rest/rest"


class APIClient(object):
    """
    HKIA REST API client with rate limiting and caching.
    """

    def __init__(self, cache=None, min_interval=0.6, airlines_cache_hours=24, bypass_cache=False):
        self.cache = cache
        self.min_interval = min_interval
        self.airlines_cache_hours = airlines_cache_hours
        self.bypass_cache = bypass_cache
        self._last_call = 0.0
        self._airlines_cache = None
        self._airlines_cache_time = 0.0
        self._rate_lock = threading.Lock()

    def _rate_limit(self):
        """Enforce minimum interval between API calls.

        The timing decision itself is serialized so concurrent callers
        (flights poller, airline loader, web queries) cannot all observe the
        same free slot and bypass the polite interval.
        """
        with self._rate_lock:
            now = time.time()
            wait = self.min_interval - (now - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()

    def _request_json(self, url):
        """Make HTTP GET request and return parsed JSON."""
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "HKGFlightData/3.0")
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            log("HTTP {} for {}".format(exc.code, url))
            return None
        except Exception as exc:
            log("request failed {}: {}".format(url, exc))
            return None

    def fetch_flights(self, date_str):
        """
        Fetch flights for a specific date.

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            list: Raw flight data from API, or None on failure
        """
        # Validate date format to prevent path traversal and injection
        if not validate_date(date_str):
            log("Invalid date format: {}".format(date_str))
            return None
        
        self._rate_limit()
        # Use urlencode to safely construct query parameters
        params = urllib.parse.urlencode({"date": date_str, "span": "1"})
        url = "{}/flights?{}".format(API_BASE, params)
        data = self._request_json(url)
        if data is not None and self.cache is not None:
            self.cache.write_flights(date_str, data)
        return data

    def fetch_airlines(self):
        """
        Fetch airline metadata.

        Returns:
            list: Airline data, or empty list on failure
        """
        # Use cache if fresh enough unless this run explicitly bypasses it.
        if self.cache is not None and not self.bypass_cache:
            cached = self.cache.read_airlines()
            if cached:
                cache_age = self.cache.cache_age_minutes(self.cache.airlines_path)
                if cache_age >= 0 and cache_age < (self.airlines_cache_hours * 60):
                    return cached

        self._rate_limit()
        url = "{}/airlines".format(API_BASE)
        data = self._request_json(url)
        if data is not None:
            if not isinstance(data, list):
                data = []
            if self.cache is not None:
                self.cache.write_airlines(data)
            return data
        # Fall back to cache unless this run explicitly bypasses cached data.
        if self.cache is not None and not self.bypass_cache:
            return self.cache.read_airlines()
        return []

    def fetch_airlines_meta(self):
        """
        Fetch airline metadata with failure/result metadata.

        Unlike ``fetch_airlines`` (which returns ``[]`` for both failure and
        an empty result), this reports the outcome so the UI can distinguish
        "loaded empty" from "failed to load".

        Returns:
            dict with keys ``airlines`` (list), ``source``
            (``"api"|"cache"|"none"``), ``ok`` (bool) and ``error`` (str or None).
        """
        # Fresh cache hit (respects --force).
        if self.cache is not None and not self.bypass_cache:
            cached = self.cache.read_airlines()
            if cached:
                cache_age = self.cache.cache_age_minutes(self.cache.airlines_path)
                if cache_age >= 0 and cache_age < (self.airlines_cache_hours * 60):
                    return {"airlines": cached, "source": "cache", "ok": True, "error": None}

        self._rate_limit()
        url = "{}/airlines".format(API_BASE)
        data = self._request_json(url)
        if data is not None:
            if not isinstance(data, list):
                data = []
            if self.cache is not None:
                self.cache.write_airlines(data)
            return {"airlines": data, "source": "api", "ok": True, "error": None}

        # API failed: fall back to cache unless this run bypasses it.
        if self.cache is not None and not self.bypass_cache:
            fallback = self.cache.read_airlines()
            if fallback:
                return {"airlines": fallback, "source": "cache", "ok": True, "error": "api_failed"}
        return {"airlines": [], "source": "none", "ok": False, "error": "api_failed"}

    def fetch_fvm_registrations(self):
        """
        Fetch FVM (Flight View Monitor) registration data.

        Returns:
            list: FVM data, or empty list on failure
        """
        self._rate_limit()
        url = "{}/fvm".format(API_BASE)
        data = self._request_json(url)
        if data is not None:
            if not isinstance(data, list):
                data = []
            if self.cache is not None:
                self.cache.merge_fvm_snapshot(data)
            return data
        return []
