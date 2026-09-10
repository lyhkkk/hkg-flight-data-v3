"""
HKG Flight Data v3 - Terminal package.

This package holds the rebuilt terminal workbench. It MUST NOT import Textual
at module level: importing ``hkg_flight`` or ``hkg_flight.terminal`` stays
dependency-free and Python 3.7-importable. The optional Textual adapter is
loaded only by the session's backend selector (see ``textual_app``).
"""

from .presenter import (
    DEPARTURES,
    ARRIVALS,
    ALERTS,
    AIRLINES,
    FLIGHT_PAGES,
    AUX_PAGES,
    ALL_PAGES,
)
from .state import AppState, dispatch, reconcile

__all__ = [
    "DEPARTURES",
    "ARRIVALS",
    "ALERTS",
    "AIRLINES",
    "FLIGHT_PAGES",
    "AUX_PAGES",
    "ALL_PAGES",
    "AppState",
    "dispatch",
    "reconcile",
]
