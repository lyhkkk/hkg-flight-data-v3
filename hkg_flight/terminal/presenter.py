"""
HKG Flight Data v3 - Terminal Presenter
Pure field projection, whitelist search, stable ordering and row identity.

This module has no terminal, network or framework dependency; it is the
single owner of "what a flight row looks like" for both the Textual and the
plain adapters, and of the search semantics defined in the rebuild report.
"""

from ..utils import (
    normalize_flight_number,
    route_text,
    gate_stand_text,
    sort_flights,
)

DEPARTURES = "departures"
ARRIVALS = "arrivals"
ALERTS = "alerts"
AIRLINES = "airlines"

FLIGHT_PAGES = (DEPARTURES, ARRIVALS)
AUX_PAGES = (ALERTS, AIRLINES)
ALL_PAGES = FLIGHT_PAGES + AUX_PAGES

# Whitelisted search fields (report section 05). Codeshare numbers are
# carried in ``all_flight_numbers``; the flight-number field is matched with
# spaces stripped so "CX 759" finds "CX759".
SEARCH_FIELDS = (
    "all_flight_numbers",
    "airline_code",
    "origin",
    "destination",
    "gate",
    "stand",
    "terminal",
    "status",
)

STATUS_FILTERS = (
    "scheduled",
    "boarding",
    "delayed",
    "cancelled",
    "departed",
    "landed",
)

# Stable row-identity fields, ordered. Only *schedule* attributes belong
# here: they answer "which flight is this" and never change while the row is
# on screen, so a gate or status update cannot make one flight look like two.
ROW_ID_FIELDS = (
    "date",
    "type",
    "flight_number",
    "time",
    "origin",
    "destination",
    "airline_code",
    "all_flight_numbers",
)

# Recorded explicitly (and covered by tests): these are operational fields.
# They are updated throughout the day -- a gate change, a boarding status, a
# baggage belt reassignment -- so they are deliberately excluded from
# identity even though real samples use them to tell duplicate segments apart.
MUTABLE_OPERATION_FIELDS = (
    "gate",
    "stand",
    "aisle",
    "hall",
    "belt",
    "terminal",
    "status",
    "status_code",
)

DUPLICATE_MARKER = "dup"


def _stable_key(rec):
    """Tuple form of the stable projection; used to group duplicate segments."""
    return tuple(str(rec.get(field) or "") for field in ROW_ID_FIELDS)


def row_identity(rec, duplicate_ordinal=0):
    """Return a UI-local, stable identity string for a flight record.

    Built from :data:`ROW_ID_FIELDS` only. Two segments can share every stable
    attribute (same date, direction, flight number, time, route and airline)
    and still be two different entities -- real samples contain such
    same-day duplicates -- so identity then carries a deterministic
    ``duplicate_ordinal`` from :func:`duplicate_ordinals`.

    This is distinct from the cache/alert key format and is never persisted.
    """
    parts = list(_stable_key(rec))
    if duplicate_ordinal:
        parts.append("{}:{}".format(DUPLICATE_MARKER, duplicate_ordinal))
    return "|".join(parts)


def duplicate_ordinals(records):
    """Deterministic per-segment ordinal for same-day duplicate segments.

    ``records`` must already be in stable sorted order (``sort_flights``, whose
    key is date / time / flight number). Segments sharing a stable key receive
    0, 1, 2 … in that order. Because the sort key is built from stable fields
    the ordinal does not move when a gate, stand or status changes; because it
    is computed on the *unfiltered* page it does not move while the user
    types a search or toggles a filter.

    It is never a random value and never a per-refresh counter: the same
    dataset always yields the same ordinals.
    """
    seen = {}
    ordinals = []
    for rec in records:
        key = _stable_key(rec)
        ordinal = seen.get(key, 0)
        seen[key] = ordinal + 1
        ordinals.append(ordinal)
    return ordinals


def tokenize(text):
    """Split a search query into lowercased, whitespace-separated tokens."""
    return [token.lower() for token in (text or "").split() if token]


def _token_matches(rec, token):
    """True when a single token matches any whitelisted field of a record."""
    token_ns = normalize_flight_number(token)
    flight_number = normalize_flight_number(rec.get("flight_number", ""))
    if token_ns and token_ns in flight_number:
        return True
    for field in SEARCH_FIELDS:
        value = str(rec.get(field) or "").lower()
        if token in value:
            return True
    return False


def match_record(rec, tokens):
    """AND across tokens, OR across fields within a token."""
    if not tokens:
        return True
    for token in tokens:
        if not _token_matches(rec, token):
            return False
    return True


def matches_filters(rec, airline="", status=""):
    """True when one record passes the structured airline/status filters."""
    if airline:
        wanted = str(airline).upper()
        if not (str(rec.get("airline_code", "")).upper() == wanted
                or normalize_flight_number(rec.get("flight_number", "")).startswith(wanted)):
            return False
    if status and rec.get("status_category") != status:
        return False
    return True


def filter_flights(records, airline="", status=""):
    """Apply structured airline/status filters (empty means no filter)."""
    return [r for r in records if matches_filters(r, airline=airline, status=status)]


def page_flights(snapshot, page_name):
    """Return the (already sorted) flight records for a page."""
    records = snapshot.get("records", [])
    if page_name == DEPARTURES:
        return [r for r in records if r.get("type") == "departure"]
    if page_name == ARRIVALS:
        return [r for r in records if r.get("type") == "arrival"]
    return []


def visible_rows(snapshot, page_name, search_text, airline="", status=""):
    """Sorted + filtered list of ``{...record, id}`` rows for a page.

    Returns a list of dicts, each carrying the record plus its UI row id. The
    id is computed from the sorted, *unfiltered* page so that it never depends
    on the current search text, airline filter or status filter: typing in the
    search box must not re-key the rows the user is looking at.
    """
    if page_name not in FLIGHT_PAGES:
        return []
    records = sort_flights(page_flights(snapshot, page_name))
    ordinals = duplicate_ordinals(records)
    tokens = tokenize(search_text)
    rows = []
    for rec, ordinal in zip(records, ordinals):
        if not matches_filters(rec, airline=airline, status=status):
            continue
        if not match_record(rec, tokens):
            continue
        rows.append({"id": row_identity(rec, ordinal), "record": rec})
    return rows


def sort_alerts(alerts):
    """Alerts newest-first with a deterministic tiebreak."""
    def key(alert):
        return (
            alert.get("raised_at", ""),
            alert.get("flight_number", ""),
            alert.get("field", ""),
        )
    return sorted(alerts, key=key, reverse=True)


def alert_rows(alerts, search_text):
    """Project + filter alerts into rows (``{id, record}``)."""
    rows = []
    tokens = tokenize(search_text)
    for alert in sort_alerts(alerts):
        haystack = " ".join([
            str(alert.get("flight_number", "")),
            str(alert.get("field", "")),
            str(alert.get("old_value", "")),
            str(alert.get("new_value", "")),
            str(alert.get("status", "")),
        ]).lower()
        if tokens and not all(t in haystack for t in tokens):
            continue
        rows.append({"id": _alert_identity(alert), "record": alert})
    return rows


def _alert_identity(alert):
    """Deterministic identity for an alert row."""
    return "{}|{}|{}|{}".format(
        alert.get("raised_at", ""),
        alert.get("flight_number", ""),
        alert.get("field", ""),
        alert.get("new_value", ""),
    )


def airline_rows(airlines, search_text):
    """Project + filter airlines into rows sorted by code."""
    rows = []
    tokens = tokenize(search_text)
    for airline in airlines:
        code = str(airline.get("code", ""))
        name = airline_name(airline)
        haystack = "{} {}".format(code, name).lower()
        if tokens and not all(t in haystack for t in tokens):
            continue
        rows.append({"id": code, "record": airline, "code": code, "name": name})
    rows.sort(key=lambda r: r["code"])
    return rows


def airline_name(airline):
    """Airline display name: description[0], falling back to code."""
    description = airline.get("description")
    if isinstance(description, list) and description:
        return str(description[0])
    return str(airline.get("code", ""))


def project_flight(rec, duplicate_ordinal=0):
    """Project a flight record to the fields the UI renders."""
    return {
        "id": row_identity(rec, duplicate_ordinal),
        "time": rec.get("time", "--:--"),
        "flight_number": rec.get("flight_number", ""),
        "airline_code": rec.get("airline_code", ""),
        "type": rec.get("type", ""),
        "status": rec.get("status", ""),
        "status_category": rec.get("status_category", "scheduled"),
        "route": route_text(rec),
        "gate_stand": gate_stand_text(rec),
        "gate": rec.get("gate", ""),
        "stand": rec.get("stand", ""),
        "terminal": rec.get("terminal", ""),
        "aisle": rec.get("aisle", ""),
        "hall": rec.get("hall", ""),
        "belt": rec.get("belt", ""),
        "codeshares": [n for n in (rec.get("all_flight_numbers", "") or "").split("|") if n],
    }


def detail_lines(rec):
    """Labeled detail lines for a selected flight."""
    lines = [
        ("Flight", rec.get("flight_number", "N/A")),
        ("Type", "Departure" if rec.get("type") == "departure" else "Arrival"),
        ("Date", rec.get("date", "")),
        ("Time", rec.get("time", "")),
        ("Status", rec.get("status", "")),
        ("Route", route_text(rec)),
        ("Gate/Stand", gate_stand_text(rec)),
        ("Terminal", rec.get("terminal", "") or "—"),
    ]
    if rec.get("aisle"):
        lines.append(("Aisle", rec.get("aisle")))
    if rec.get("hall"):
        lines.append(("Hall", rec.get("hall")))
    if rec.get("belt"):
        lines.append(("Belt", rec.get("belt")))
    codeshares = [n for n in (rec.get("all_flight_numbers", "") or "").split("|") if n]
    if codeshares:
        lines.append(("Codeshare", ", ".join(codeshares)))
    return lines
