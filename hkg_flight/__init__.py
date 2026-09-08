"""
HKG Flight Data v3
A modular flight information retrieval system for Hong Kong International Airport (HKIA).

This package provides:
- Flight data polling from HKIA API
- Local caching with offline fallback
- Gate/stand change alerts
- Curses TUI and Web dashboard
- CLI commands for quick queries

Usage:
    python -m hkg_flight                  # Start TUI
    python -m hkg_flight web              # Start web server
    python -m hkg_flight query CX759      # Search flight
    python -m hkg_flight departures       # Today's departures
    python -m hkg_flight arrivals         # Today's arrivals
    python -m hkg_flight alerts           # Show active alerts
"""

from .cache import CacheSystem, DEFAULT_CACHE_DIR, DEFAULT_MIN_API_INTERVAL, DEFAULT_WEB_PORT
from .api import APIClient, API_BASE
from .alerts import AlertManager
from .poller import Poller
from .utils import (
    today_str,
    normalize_flight_number,
    make_flight_key,
    route_text,
    gate_stand_text,
    format_time,
    format_raw_time,
    log,
    get_status_info,
    status_pair,
    normalize_flights,
    sort_flights,
    filter_records,
)

__version__ = "3.0.0"
__author__ = "HKG Flight Data Team"

# Import query functions from cli module
# These are placed here to avoid circular imports
from .cli import search_flights, flights_for_date, load_airlines

__all__ = [
    # Core classes
    "CacheSystem",
    "APIClient",
    "AlertManager",
    "Poller",
    # Constants
    "DEFAULT_CACHE_DIR",
    "DEFAULT_MIN_API_INTERVAL",
    "DEFAULT_WEB_PORT",
    "API_BASE",
    # Utility functions
    "today_str",
    "normalize_flight_number",
    "make_flight_key",
    "route_text",
    "gate_stand_text",
    "format_time",
    "format_raw_time",
    "log",
    "get_status_info",
    "status_pair",
    "normalize_flights",
    "sort_flights",
    "filter_records",
    # Query functions
    "search_flights",
    "flights_for_date",
    "load_airlines",
]


def main():
    """Entry point for running as a module."""
    from .cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
