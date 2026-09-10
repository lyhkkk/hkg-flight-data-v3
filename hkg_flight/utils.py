"""
HKG Flight Data v3 - Utilities.

Pure helpers shared by the API client, the cache, the poller and both terminal
front-ends. No I/O, no threads, no third-party imports.

Untrusted API strings are sanitised here, at the single point where they enter
the system, so no renderer has to defend itself against control characters or
markup-like text later on.
"""

from datetime import date, datetime
import re
import sys


# -- dates ---------------------------------------------------------------

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def today_str():
    """Today's date as YYYY-MM-DD."""
    return date.today().isoformat()


def validate_date(date_str):
    """True when ``date_str`` is a YYYY-MM-DD string."""
    return isinstance(date_str, str) and bool(_DATE_RE.fullmatch(date_str))


# -- text ----------------------------------------------------------------

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def clean_text(value):
    """Strip control characters from an untrusted API string.

    This is the trust boundary: everything downstream (projection, rendering,
    the Textual markup layer) may assume a field is plain printable text.
    """
    return _CONTROL_RE.sub("", str(value or ""))


def normalize_flight_number(no):
    """Normalize a flight number: ``'CX 759'`` -> ``'CX759'``."""
    if no is None:
        return ""
    return str(no).strip().replace(" ", "").upper()


def make_flight_key(date_str, flight_number):
    """Stable per-flight key, e.g. ``2026-08-16_CX759``."""
    return f"{date_str}_{normalize_flight_number(flight_number)}"


def log(msg):
    """Timestamped stderr log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[hkg_flight] {ts} {msg}", file=sys.stderr)


# -- display text --------------------------------------------------------

def route_text(rec):
    """Human readable route for a normalized flight record."""
    if rec.get("type") == "arrival":
        origin = str(rec.get("origin", "")).replace("|", "/")
        return f"{origin} -> HKG"
    dest = str(rec.get("destination", "")).replace("|", "/")
    return f"HKG -> {dest}"


def gate_stand_text(rec):
    """Human readable gate/stand for a normalized flight record."""
    if rec.get("type") == "departure":
        gate = rec.get("gate")
        return f"Gate {gate}" if gate else "--"
    stand = rec.get("stand")
    return f"Stand {stand}" if stand else "--"


# -- status --------------------------------------------------------------

# Ordered: the first substring match wins, so the more specific phrases must
# come before their prefixes ("boarding soon" before "board").
_STATUS_RULES = (
    ("cancel", "cancelled"),
    ("depart", "departed"),
    ("land", "landed"),
    ("at gate", "at_gate"),
    ("taxi", "taxiing"),
    ("boarding soon", "boarding_soon"),
    ("board", "boarding"),
    ("final call", "final_call"),
    ("gate clos", "gate_closed"),
    ("delay", "delayed"),
    ("est", "estimated"),
    ("eta", "estimated"),
    ("scheduled", "scheduled"),
)


def status_category(raw_status):
    """Map a raw HKIA status string onto a stable category."""
    s = str(raw_status or "").strip().lower()
    if not s:
        return "unknown"
    for needle, category in _STATUS_RULES:
        if needle in s:
            return category
    return "unknown"


# -- flight data ---------------------------------------------------------

def _full_flight_number(primary):
    """Complete flight number, tolerating payloads that carry only digits.

    Real HKIA payloads look like ``{"airline": "CKS", "no": "K4 701"}``: ``no``
    already carries the IATA prefix and ``airline`` is the 3-letter ICAO code.
    A numeric-only ``no`` is completed with a 2-letter airline code, so
    ``query CX759`` keeps working against either shape.
    """
    number = normalize_flight_number(primary.get("no", ""))
    if not number or number[0].isalpha():
        return number
    airline = normalize_flight_number(primary.get("airline", ""))
    return f"{airline}{number}" if len(airline) == 2 else number


def normalize_flights(raw_data):
    """Flatten the raw HKIA API array into normalized records.

    Cargo entries are skipped; codeshares are preserved in
    ``all_flight_numbers`` so they stay searchable.
    """
    records = []
    if not isinstance(raw_data, list):
        return records

    for entry in raw_data:
        if not isinstance(entry, dict) or entry.get("cargo"):
            continue

        is_arrival = bool(entry.get("arrival"))
        entry_date = clean_text(entry.get("date"))

        for flight_obj in entry.get("list") or []:
            if not isinstance(flight_obj, dict):
                continue

            flight_list = flight_obj.get("flight") or []
            if not isinstance(flight_list, list) or not flight_list:
                continue
            primary = flight_list[0]
            if not isinstance(primary, dict):
                continue

            flight_number = _full_flight_number(primary)
            if not flight_number:
                continue

            all_nos = [
                _full_flight_number(item)
                for item in flight_list
                if isinstance(item, dict) and item.get("no")
            ]

            origin = flight_obj.get("origin") or []
            destination = flight_obj.get("destination") or []
            if isinstance(origin, str):
                origin = [origin]
            if isinstance(destination, str):
                destination = [destination]

            raw_status = clean_text(flight_obj.get("status"))

            records.append({
                "key": make_flight_key(entry_date, flight_number),
                "date": entry_date,
                "time": clean_text(flight_obj.get("time")),
                "flight_number": flight_number,
                "airline_code": clean_text(primary.get("airline")),
                "all_flight_numbers": "|".join(all_nos),
                "type": "arrival" if is_arrival else "departure",
                "status": raw_status,
                "status_category": status_category(raw_status),
                "terminal": clean_text(flight_obj.get("terminal")),
                "gate": clean_text(flight_obj.get("gate")),
                "aisle": clean_text(flight_obj.get("aisle")),
                "hall": clean_text(flight_obj.get("hall")),
                "belt": clean_text(flight_obj.get("baggage") or flight_obj.get("belt")),
                "stand": clean_text(flight_obj.get("stand")),
                "origin": "|".join(clean_text(x) for x in origin if x),
                "destination": "|".join(clean_text(x) for x in destination if x),
            })

    return records


def sort_flights(records):
    """Sort by date, then scheduled time, then flight number."""
    return sorted(
        records,
        key=lambda r: (r.get("date", ""), r.get("time", ""), r.get("flight_number", "")),
    )
