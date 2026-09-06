"""
HKG Flight Data v3 - API Client Module
Handles communication with the HKIA flight API.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .utils import log


API_BASE = "https://www.hongkongairport.com/flightinfo-rest/rest"


def _validate_date(date_str):
    """Validate date string format (YYYY-MM-DD). Returns True if valid."""
    if not isinstance(date_str, str):
        return False
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str))


class APIClient(object):
    """
    HKIA REST API client with rate limiting and caching.
    """

    def __init__(self, cache=None, min_interval=0.6, airlines_cache_hours=24):
        self.cache = cache
        self.min_interval = min_interval
        self.airlines_cache_hours = airlines_cache_hours
        self._last_call = 0.0
        self._lock = False
        self._airlines_cache = None
        self._airlines_cache_time = 0.0

    def _rate_limit(self):
        """Enforce minimum interval between API calls."""
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
        if not _validate_date(date_str):
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
        # Use cache if fresh enough
        if self.cache is not None:
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
        # Fallback to cache
        if self.cache is not None:
            return self.cache.read_airlines()
        return []

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
