"""
HKG Flight Data v3
A flight information retrieval system for Hong Kong International Airport.

Provides:
- Flight data polling from the HKIA API, with local cache fallback
- Gate/stand change alerts
- Terminal workbench (optional Textual UI, stdlib plain fallback)
- Web dashboard and CLI commands for quick queries

Usage:
    python -m hkg_flight                  # Terminal workbench
    python -m hkg_flight web              # Web server
    python -m hkg_flight query CX759      # Search a flight
    python -m hkg_flight departures       # Today's departures
    python -m hkg_flight arrivals         # Today's arrivals
    python -m hkg_flight alerts           # Active alerts
"""

from .cache import (
    CacheSystem,
    DEFAULT_CACHE_DIR,
    DEFAULT_MIN_API_INTERVAL,
    DEFAULT_WEB_PORT,
)
from .api import APIClient, API_BASE
from .alerts import AlertManager
from .poller import Poller
from .utils import (
    today_str,
    validate_date,
    clean_text,
    normalize_flight_number,
    make_flight_key,
    route_text,
    gate_stand_text,
    log,
    status_category,
    normalize_flights,
    sort_flights,
)
# Imported last: the CLI depends on the modules above.
from .cli import search_flights, flights_for_date, load_airlines

__version__ = "3.0.0"

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
    # Utilities
    "today_str",
    "validate_date",
    "clean_text",
    "normalize_flight_number",
    "make_flight_key",
    "route_text",
    "gate_stand_text",
    "log",
    "status_category",
    "normalize_flights",
    "sort_flights",
    # Query helpers
    "search_flights",
    "flights_for_date",
    "load_airlines",
]


def main():
    """Entry point for ``python -m hkg_flight``."""
    from .cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
