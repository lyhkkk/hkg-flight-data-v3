"""
HKG Flight Data v3 - Utilities Module
Helper functions for flight data processing.
"""

from datetime import date, datetime
import re
import sys


def today_str():
    """Return today's date as YYYY-MM-DD."""
    return date.today().isoformat()


def validate_date(date_str):
    """Validate date string format (YYYY-MM-DD). Returns True if valid."""
    if not isinstance(date_str, str):
        return False
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str))


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
        return "{} -> HKG".format(origin)
    dest = rec.get("destination", "").replace("|", "/")
    return "HKG -> {}".format(dest)


def gate_stand_text(rec):
    """Human readable gate/stand for a normalized flight record."""
    if rec.get("type") == "departure":
        g = rec.get("gate")
        return "Gate {}".format(g) if g else "--"
    s = rec.get("stand")
    return "Stand {}".format(s) if s else "--"


def format_time(value):
    """Format time string (e.g. '0840' -> '08:40')."""
    s = str(value or "").strip()
    if not s:
        return ""
    s = s.replace(":", "")
    if len(s) == 4 and s.isdigit():
        return "{}:{}".format(s[:2], s[2:])
    return value


def format_raw_time(value):
    """Ensure time is in HH:MM format."""
    s = str(value or "").strip()
    if not s:
        return ""
    s = s.replace(":", "")
    if len(s) == 3 and s.isdigit():
        return "0{}:{}".format(s[0], s[1:])
    if len(s) == 4 and s.isdigit():
        return "{}:{}".format(s[:2], s[2:])
    return value


def log(msg):
    """Timestamped stderr log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("[hkg_flight] {} {}".format(ts, msg), file=sys.stderr)


def get_status_info(raw_status, flight_type=None):
    """
    Parse status string into (category, display, label).

    Returns:
        tuple: (category, display_text, label)
    """
    s = str(raw_status or "").strip().lower()
    if not s:
        return ("unknown", raw_status or "", raw_status or "")

    # Cancelled
    if "cancel" in s:
        return ("cancelled", "Cancelled", "Cancelled")

    # Departed / Landed / At Gate
    if "departed" in s or "depart" in s:
        return ("departed", "Departed", "Departed")
    if "landed" in s or "land" in s:
        return ("landed", "Landed", "Landed")
    if "at gate" in s:
        return ("at_gate", "At Gate", "At Gate")
    if "taxi" in s:
        return ("taxiing", "Taxiing", "Taxiing")

    # Boarding
    if "boarding" in s or "board" in s:
        return ("boarding", "Boarding", "Boarding")
    if "final call" in s:
        return ("final_call", "Final Call", "Final Call")
    if "gate closed" in s or "gate close" in s:
        return ("gate_closed", "Gate Closed", "Gate Closed")
    if "boarding soon" in s:
        return ("boarding_soon", "Boarding Soon", "Boarding Soon")

    # Delayed
    if "delay" in s:
        return ("delayed", "Delayed", "Delayed")

    # Estimated time
    if "est" in s or "eta" in s:
        return ("estimated", "Est", "Estimated")

    # Scheduled
    if "scheduled" in s or s == "":
        return ("scheduled", "Scheduled", "Scheduled")

    return ("unknown", raw_status, raw_status)


def status_pair(category):
    """Return curses color pair id and icon for status category."""
    # Returns a simple identifier for color mapping
    status_map = {
        "scheduled": 5,
        "gate_closed": 1,
        "boarding_soon": 4,
        "final_call": 4,
        "boarding": 2,
        "departed": 2,
        "estimated": 1,
        "delayed": 3,
        "landed": 2,
        "at_gate": 2,
        "taxiing": 2,
        "cancelled": 3,
    }
    return status_map.get(category, 0)


# =========================================================================
# Flight Data Processing
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

    text_lower = text.lower()
    results = []

    for rec in records:
        # Check flight number
        if text_lower in rec.get("flight_number", "").lower():
            results.append(rec)
            continue
        # Check all flight numbers (codeshares)
        if text_lower in rec.get("all_flight_numbers", "").lower():
            results.append(rec)
            continue
        # Check route (origin/destination)
        if text_lower in rec.get("origin", "").lower():
            results.append(rec)
            continue
        if text_lower in rec.get("destination", "").lower():
            results.append(rec)
            continue
        # Check status
        if text_lower in rec.get("status", "").lower():
            results.append(rec)
            continue
        # Check terminal
        if text_lower in rec.get("terminal", "").lower():
            results.append(rec)
            continue

    return results
