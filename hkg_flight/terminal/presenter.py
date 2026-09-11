"""
HKG Flight Data v3 - Terminal Presenter.

Pure projection, whitelist search, stable ordering and row identity. No
terminal, network or framework dependency: this is the single owner of "what a
flight row looks like" for both the Textual and the plain adapter.
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

# Whitelisted search fields. Codeshare numbers live in ``all_flight_numbers``;
# the flight-number field is space-normalized, so "CX 759" finds "CX759".
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

# Row identity is built from *schedule* attributes only: they answer "which
# flight is this" and never change while the row is on screen. Operational
# fields (gate, stand, status, ...) change throughout the day and are
# deliberately excluded, so a gate update cannot make one flight look like two.
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

_DUPLICATE_MARKER = "dup"


def _stable_key(rec):
    return tuple(str(rec.get(field) or "") for field in ROW_ID_FIELDS)


def row_identity(rec, duplicate_ordinal=0):
    """UI-local, stable identity string for a flight record.

    Two segments can share every stable attribute and still be distinct
    entities (real HKIA samples contain same-day duplicates), so identity then
    carries a deterministic ordinal from :func:`duplicate_ordinals`. This is
    never persisted and is unrelated to the cache/alert key format.
    """
    parts = list(_stable_key(rec))
    if duplicate_ordinal:
        parts.append(f"{_DUPLICATE_MARKER}:{duplicate_ordinal}")
    return "|".join(parts)


def duplicate_ordinals(records):
    """Deterministic per-segment ordinal for same-day duplicate segments.

    ``records`` must already be in stable sorted order. Segments sharing a
    stable key receive 0, 1, 2 ... in that order. The sort key is built from
    stable fields, so the ordinal does not move when a gate or status changes;
    it is computed on the *unfiltered* page, so it does not move while the user
    types. The same dataset always yields the same ordinals.
    """
    seen = {}
    ordinals = []
    for rec in records:
        key = _stable_key(rec)
        ordinal = seen.get(key, 0)
        seen[key] = ordinal + 1
        ordinals.append(ordinal)
    return ordinals


# -- search --------------------------------------------------------------

def tokenize(text):
    """Split a search query into lowercased, whitespace-separated tokens."""
    return [token.lower() for token in (text or "").split() if token]


def _token_matches(rec, token):
    """True when one token matches any whitelisted field of a record."""
    token_ns = normalize_flight_number(token)
    if token_ns and token_ns in normalize_flight_number(rec.get("flight_number", "")):
        return True
    for field in SEARCH_FIELDS:
        if token in str(rec.get(field) or "").lower():
            return True
    return False


def match_record(rec, tokens):
    """AND across tokens, OR across fields within a token."""
    return all(_token_matches(rec, token) for token in tokens)


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


# -- projections ---------------------------------------------------------

def page_flights(snapshot, page_name):
    """Sorted flight records for a page."""
    records = snapshot.get("records", [])
    if page_name == DEPARTURES:
        wanted = "departure"
    elif page_name == ARRIVALS:
        wanted = "arrival"
    else:
        return []
    return [r for r in records if r.get("type") == wanted]


def visible_rows(snapshot, page_name, search_text, airline="", status=""):
    """Sorted + filtered list of ``{"id", "record"}`` rows for a page.

    Row ids are computed from the sorted *unfiltered* page, so typing in the
    search box never re-keys the rows the user is looking at.
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
    return sorted(
        alerts,
        key=lambda a: (a.get("raised_at", ""), a.get("flight_number", ""), a.get("field", "")),
        reverse=True,
    )


def alert_identity(alert):
    """Deterministic identity for an alert row."""
    return "{}|{}|{}|{}".format(
        alert.get("raised_at", ""),
        alert.get("flight_number", ""),
        alert.get("field", ""),
        alert.get("new_value", ""),
    )


def alert_change_text(alert):
    """The divergence itself, e.g. ``62 → 63`` / ``N24 → —`` (released)."""
    old = str(alert.get("old_value") or "") or "—"
    new = str(alert.get("new_value") or "") or "—"
    return f"{old} → {new}"


def alert_rows(alerts, search_text):
    """Project + filter alerts into ``{"id", "record"}`` rows."""
    tokens = tokenize(search_text)
    rows = []
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
        rows.append({"id": alert_identity(alert), "record": alert})
    return rows


def airline_name(airline):
    """Airline display name: description[0], falling back to the code."""
    description = airline.get("description")
    if isinstance(description, list) and description:
        return str(description[0])
    return str(airline.get("code", ""))


def airline_rows(airlines, search_text):
    """Project + filter airlines into rows sorted by code."""
    tokens = tokenize(search_text)
    rows = []
    for airline in airlines:
        code = str(airline.get("code", ""))
        name = airline_name(airline)
        if tokens and not all(t in f"{code} {name}".lower() for t in tokens):
            continue
        rows.append({"id": code, "record": airline, "code": code, "name": name})
    rows.sort(key=lambda r: r["code"])
    return rows


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
    for label, field in (("Aisle", "aisle"), ("Hall", "hall"), ("Belt", "belt")):
        if rec.get(field):
            lines.append((label, rec[field]))
    codeshares = [n for n in (rec.get("all_flight_numbers") or "").split("|") if n]
    if codeshares:
        lines.append(("Codeshare", ", ".join(codeshares)))
    return lines
