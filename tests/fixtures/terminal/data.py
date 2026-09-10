"""
Deterministic offline fixtures for the terminal test suite.

Flight records are normalized records (the form the presenter consumes).
They include same-day same-direction duplicates, missing fields, unicode and
codeshares so identity/search/ordering behaviour can be tested offline.
"""

from hkg_flight.utils import make_flight_key


DESTINATIONS = [
    "SIN", "LHR", "LAX", "NRT", "BKK", "TPE", "CDG", "FRA", "DXB", "SYD",
    "PEK", "PVG", "JFK", "ORD", "ICN", "KUL", "MNL", "HAN", "SGN", "DEL",
]
ORIGINS = [
    "SIN", "LHR", "LAX", "NRT", "BKK", "TPE", "CDG", "FRA", "DXB", "SYD",
]
AIRLINE_CODES = ["CX", "HX", "UO", "KA", "NH", "SQ", "JL", "TG", "BR", "CI"]
ICAO_CODES = ["CPA", "CRK", "HKE", "HDA", "ANA", "SIA", "JAL", "THA", "EVA", "CAL"]
STATUSES = [
    ("Scheduled", "scheduled"),
    ("Boarding", "boarding"),
    ("Delayed", "delayed"),
    ("Cancelled", "cancelled"),
    ("Departed 08:54", "departed"),
    ("Landed", "landed"),
]
TERMINALS = ["T1", "T1", "T1", "T2", ""]


def make_flight(index, date="2026-09-09"):
    """Build one normalized flight record (deterministic per index)."""
    airline_i = index % len(AIRLINE_CODES)
    airline = AIRLINE_CODES[airline_i]
    icao = ICAO_CODES[airline_i]
    number = airline + str(100 + (index % 800))
    is_arrival = (index % 2) == 1
    status_raw, category = STATUSES[index % len(STATUSES)]
    codeshare = ""
    if index % 7 == 0:
        codeshare = "|".join(["{}".format(number), "QR{}".format(9000 + index % 999)])
    rec = {
        "key": make_flight_key(date, number),
        "date": date,
        "time": "{:02d}:{:02d}".format((index * 7) % 24, (index * 11) % 60),
        "flight_number": number,
        "airline_code": icao,
        "all_flight_numbers": codeshare or number,
        "type": "arrival" if is_arrival else "departure",
        "status": status_raw,
        "statusCode": None,
        "status_category": category,
        "status_display": status_raw,
        "status_label": status_raw,
        "terminal": TERMINALS[index % len(TERMINALS)],
        "gate": str(1 + (index % 80)) if not is_arrival and index % 5 else "",
        "aisle": "ABCDE"[index % 5] if not is_arrival else "",
        "hall": "AB"[index % 2] if is_arrival else "",
        "belt": str(1 + (index % 12)) if is_arrival and index % 4 else "",
        "stand": ("WNRSE"[index % 5] + str(1 + (index % 60))) if is_arrival and index % 3 else "",
        "origin": "|".join([ORIGINS[index % len(ORIGINS)]]) if is_arrival else "HKG",
        "destination": DESTINATIONS[index % len(DESTINATIONS)] if not is_arrival else "HKG",
    }
    if index % 11 == 0:
        # long / unicode route sample (Chinese + combining mark)
        rec["destination"] = "北京" if not is_arrival else rec["destination"]
        rec["origin"] = "東京" if is_arrival else rec["origin"]
    return rec


def make_flights(count, date="2026-09-09"):
    """Generate ``count`` normalized flight records."""
    records = [make_flight(i, date=date) for i in range(count)]
    # Inject same-day, same-direction duplicate segments (distinct stand/belt).
    if count >= 30:
        dup = dict(make_flight(1, date=date))
        dup["stand"] = "R21"
        dup["belt"] = "10"
        records.append(dup)
        dup2 = dict(make_flight(3, date=date))
        dup2["stand"] = "D316"
        records.append(dup2)
    return records


def make_alert(index, date="2026-09-09"):
    """Build one active alert dict."""
    flight = make_flight(index, date=date)
    field = "GATE" if index % 2 == 0 else "STAND"
    if field == "GATE":
        new_value = flight.get("gate") or "63"
    else:
        new_value = flight.get("stand") or "W63"
    return {
        "key": flight["key"],
        "flight_number": flight["flight_number"],
        "date": date,
        "time": flight["time"],
        "type": flight["type"],
        "field": field,
        "old_value": "62" if field == "GATE" else "W62",
        "new_value": new_value,
        "status": flight["status"],
        "raised_at": "2026-09-09T{:02d}:{:02d}:00".format(23 - (index % 24), 59 - (index % 60)),
    }


def make_alerts(count, date="2026-09-09"):
    return [make_alert(i, date=date) for i in range(count)]


def make_airline(index):
    code = "{}{}{}".format(chr(65 + (index % 26)), chr(65 + ((index // 26) % 26)), str(index % 10))
    return {
        "code": code,
        "description": ["Airline {} 航空".format(index), "Airline {} 航空".format(index)],
        "icon": "wmo{}".format(code.lower()),
    }


def make_airlines(count):
    return [make_airline(i) for i in range(count)]


def make_flights_snapshot(count, date="2026-09-09", source="api"):
    """A snapshot dict in the poller's shape."""
    return {
        "revision": 1,
        "records_date": date,
        "records": make_flights(count, date=date),
        "source": source,
        "last_attempt_at": "2026-09-09T08:00:00",
        "last_api_success_at": "2026-09-09T08:00:00" if source == "api" else None,
        "cache_saved_at": None,
        "last_error": None,
        "refreshing": False,
        "polling_enabled": True,
        "next_refresh_at": None,
    }


def make_combined_snapshot(count, date="2026-09-09", source="api"):
    """A full session snapshot: flights + alerts + airlines + web."""
    return {
        "flights": make_flights_snapshot(count, date=date, source=source),
        "alerts": {"revision": 1, "alerts": make_alerts(20, date=date)},
        "airlines": {
            "revision": 1,
            "airlines": make_airlines(10),
            "source": "api",
            "error": None,
            "loaded": True,
        },
        "web": {"status": "off", "error": None, "port": 8080},
    }
