"""
HKG Flight Data v3 - Terminal Views.

Pure rendering of the workbench into plain strings. The Textual adapter turns
these strings into widgets; the plain adapter prints them. Both drive the same
row primitives, so the two front-ends cannot drift apart.

When ``color`` is True, statuses are wrapped in rich markup; ``NO_COLOR``
forces ``color=False``. Data values are escaped before they enter markup, so an
API string can never be interpreted as a style tag.

Geometry is measured in display cells, not ``len()``: CJK and full-width
characters occupy two cells. Control characters and markup-like sequences are
already stripped at the data boundary (``utils.clean_text``), so nothing here
has to defend against them again.
"""

import re
import unicodedata

from .presenter import (
    DEPARTURES, ARRIVALS, ALERTS, AIRLINES,
    FLIGHT_PAGES,
    visible_rows, alert_rows, airline_rows, detail_lines, alert_identity,
    alert_change_text,
)

PAGE_KEYS = {
    DEPARTURES: "1",
    ARRIVALS: "2",
    ALERTS: "5",
    AIRLINES: "6",
}
PAGE_TITLES = {
    DEPARTURES: "Departures",
    ARRIVALS: "Arrivals",
    ALERTS: "Alerts",
    AIRLINES: "Airlines",
}

STATUS_COLORS = {
    "boarding": "green",
    "departed": "green",
    "landed": "green",
    "at_gate": "green",
    "taxiing": "green",
    "delayed": "yellow",
    "estimated": "yellow",
    "cancelled": "red",
    "gate_closed": "yellow",
    "final_call": "yellow",
    "boarding_soon": "cyan",
}

ELLIPSIS = "…"

# Below this width a flight row switches to the two-line compact form: the
# single-line row would squeeze every column, and on a phone-sized terminal it
# would not fit at all.
COMPACT_BELOW = 80

# A tag must not be preceded by a backslash, so an escaped "\[" in data is
# never mistaken for the start of markup.
_TAG_RE = re.compile(r"(?<!\\)\[/?[A-Za-z_][A-Za-z0-9_]*\]")


# -- display geometry ----------------------------------------------------

def escape_markup(text):
    """Escape ``[`` so a data value can never be read as a rich markup tag."""
    return str(text or "").replace("[", r"\[")


def strip_tags(text):
    """Remove markup tags and unescape, for width maths."""
    return _TAG_RE.sub("", str(text or "")).replace(r"\[", "[")


def _cell(char):
    """Display cells for one character (2 for wide/full-width, else 1)."""
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def text_width(text):
    """Width of ``text`` in display cells; markup tags count as zero."""
    return sum(_cell(char) for char in strip_tags(text))


def truncate(text, width):
    """Truncate to ``width`` display cells, closing any markup left open."""
    text = str(text or "")
    if width <= 0:
        return ""
    if text_width(text) <= width:
        return text

    budget = max(0, width - 1)  # reserve one cell for the ellipsis
    out, used, opened, pos = [], 0, [], 0

    def close():
        return "".join(out) + ELLIPSIS + "".join(f"[/{t}]" for t in reversed(opened))

    for tag in _TAG_RE.finditer(text):
        for char in text[pos:tag.start()]:
            if used + _cell(char) > budget:
                return close()
            used += _cell(char)
            out.append(char)
        raw = tag.group(0)
        if raw.startswith("[/"):
            name = raw[2:-1]
            if name in opened:
                opened.remove(name)
        else:
            opened.append(raw[1:-1])
        out.append(raw)
        pos = tag.end()

    for char in text[pos:]:
        if used + _cell(char) > budget:
            break
        used += _cell(char)
        out.append(char)
    return close()


def pad(text, width):
    """Truncate then right-pad with spaces to exactly ``width`` cells."""
    text = truncate(text, width)
    return text + " " * max(0, width - text_width(text))


# Column weights shared by the header and every flight row, so the two stay
# aligned at any width. Weights are relative: the space left after the
# single-space gaps is shared out proportionally.
FLIGHT_COLUMNS = (
    ("TIME", 2),
    ("FLIGHT", 3),
    ("ROUTE", 5),
    ("STATUS", 4),
    ("GATE/STAND", 3),
    ("TERM", 1),
)

# Alert rows: when the change was seen, which flight, what moved, current status.
ALERT_COLUMNS = (
    ("CHANGED", 2),
    ("FLIGHT", 3),
    ("CHANGE", 6),
    ("STATUS", 4),
)


def layout(cells, width, gap=1):
    """Lay weighted columns across ``width`` display cells.

    Space left after the mandatory gaps is shared out by weight (largest
    remainder). Every cell goes through :func:`pad`, so a row degrades
    gracefully at 40 cells instead of overflowing the terminal.
    """
    cells = [(text, max(0.0, float(weight))) for text, weight in cells]
    count = len(cells)
    if count == 0 or width <= 0:
        return ""
    budget = max(count, width - gap * (count - 1))
    total = sum(weight for _text, weight in cells)

    if total <= 0:
        shares = [budget // count] * count
    else:
        exact = [budget * weight / total for _text, weight in cells]
        shares = [int(value) for value in exact]
        order = sorted(range(count), key=lambda i: exact[i] - shares[i], reverse=True)
        for index in order[:budget - sum(shares)]:
            shares[index] += 1

    line = (" " * gap).join(
        pad(text, shares[index]) for index, (text, _weight) in enumerate(cells))
    return truncate(line, width)


def _paged(lines, available, width, scroll=0):
    """Clamp a scrollable block to ``available`` rows, counting the hidden tail."""
    lines = [truncate(line, width) for line in lines]
    if available <= 0:
        return []
    if len(lines) <= available:
        return lines
    if available == 1:
        return [truncate(f"… 1 of {len(lines)} lines", width)]
    keep = available - 1
    scroll = max(0, min(int(scroll or 0), len(lines) - keep))
    window = lines[scroll:scroll + keep]
    hidden = len(lines) - scroll - keep
    if hidden > 0:
        window.append(truncate(f"… {hidden} more", width))
    return window


def _window(rows, page, available, line_cost=1):
    """Slice of ``rows`` that fits, with the selection kept visible.

    The offset is derived for rendering only and never written back to state,
    so the selected row can never scroll out of sight.
    """
    if not rows:
        return []
    capacity = max(1, (max(1, available) - 2) // max(1, line_cost))
    offset = max(0, min(int(getattr(page, "offset", 0) or 0), len(rows) - 1))
    selected = max(0, min(int(getattr(page, "selected_index", 0) or 0), len(rows) - 1))
    if selected < offset:
        offset = selected
    elif selected >= offset + capacity:
        offset = selected - capacity + 1
    offset = max(0, min(offset, max(0, len(rows) - capacity)))
    return rows[offset:offset + capacity]


def layout_tier(width, height):
    """Return wide / normal / compact / size_hint for a terminal size."""
    if width < 40 or height < 16:
        return "size_hint"
    if width >= 120 and height >= 24:
        return "wide"
    if width >= COMPACT_BELOW:
        return "normal"
    return "compact"


def is_compact(width):
    """True when a flight row should use the two-line compact form.

    Width-only counterpart of :func:`layout_tier`, for front-ends that have no
    terminal height (the CLI and the plain adapter).
    """
    return width < COMPACT_BELOW


# -- status / health -----------------------------------------------------

def _to_epoch(value):
    """Convert a snapshot timestamp (epoch seconds or isoformat) to epoch."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value)).timestamp()
    except Exception:
        return None


def _health(snap):
    flights = snap["flights"]
    source = flights.get("source", "none")
    if source == "api":
        return "API", flights.get("last_api_success_at") or "—"
    if source == "cache":
        return "CACHE", flights.get("cache_saved_at") or "UNKNOWN AGE"
    if source == "memory":
        return "MEMORY/ERROR", ""
    return "NONE", ""


def freshness(flights, now=None, poll_interval=30):
    """STALE / API OK / CACHE / ERROR / MANUAL / LOADING label."""
    source = flights.get("source", "none")
    if flights.get("refreshing"):
        return "LOADING"
    if not flights.get("polling_enabled", True):
        return "MANUAL"

    stale_after = max(2 * poll_interval, 60)
    if source == "api":
        epoch = _to_epoch(flights.get("last_api_success_at"))
        if epoch is None:
            return "API OK"
        if now is not None and (now - epoch) > stale_after:
            return "STALE"
        return "API OK"
    if source == "cache":
        epoch = _to_epoch(flights.get("cache_saved_at"))
        if epoch is None:
            return "CACHE (age UNKNOWN)"
        if now is not None and (now - epoch) > stale_after:
            return "STALE"
        return "CACHE"
    if source == "memory":
        return "ERROR"
    return "no data"


def status_line(snap, now=None, poll_interval=30):
    """One-line data-source summary (shared by the plain adapter)."""
    flights = snap["flights"]
    source = str(flights.get("source", "none")).upper()
    date = flights.get("records_date", "")
    parts = [f"Data date {date or '—'}", f"Source {source}"]
    if flights.get("last_error"):
        parts.append(f"error: {flights['last_error']}")
    parts.append(freshness(flights, now=now, poll_interval=poll_interval))
    return " | ".join(parts)


def header_line(snap, web, now=None, poll_interval=30, today=None):
    flights = snap["flights"]
    source_label, source_time = _health(snap)
    date = flights.get("records_date", "")
    if today is not None and date and date != today:
        date = f"{date} (previous)"
    text = f" HKG FLIGHT | Data date {date or '—'} | {freshness(flights, now, poll_interval)}"
    if source_time:
        text += f" | {source_time}"
    if flights.get("last_error"):
        text += " | ERR"
    if web["status"] == "on":
        text += f" | Web :{web['port']} ON"
    elif web["status"] == "error":
        text += f" | Web ERROR (port {web['port']})"
    return text


def nav_line(state, alerts_count, poll_enabled, web_status):
    parts = []
    for page in (DEPARTURES, ARRIVALS, ALERTS, AIRLINES):
        label = PAGE_TITLES[page]
        if page == ALERTS and alerts_count:
            label = f"{label} {alerts_count}"
        marker = "[" if state.current == page else " "
        close = "]" if state.current == page else ""
        parts.append(f"{marker}{PAGE_KEYS[page]} {label}{close}")
    poll = "Poll ON" if poll_enabled else "Poll OFF"
    return " " + "  ".join(parts) + "   " + poll + f"   Web {web_status.upper()}"


def footer_line(tier, state):
    if state.focus == "search":
        return " / typing…  Enter submit  Esc cancel  Ctrl+Q quit"
    return "/ Search  Enter Detail  f Filter  r Refresh  w Web  ? Help  q Quit"


def search_line(state, snap):
    page = state.pages[state.current]
    if state.current in FLIGHT_PAGES:
        rows = visible_rows(
            snap["flights"], state.current,
            search_text=page.search_text,
            airline=page.airline_filter,
            status=page.status_filter,
        )
        text = f"Search: {page.search_text or '—'}"
        if page.airline_filter:
            text += f"   Airline: {page.airline_filter}"
        if page.status_filter:
            text += f"   Status: {page.status_filter}"
        total = sum(1 for r in snap["flights"].get("records", [])
                    if r.get("type") == ("departure" if state.current == DEPARTURES else "arrival"))
        return f"{text}   Matches {len(rows)} / Total {total}"
    if state.current == ALERTS:
        rows = alert_rows(snap["alerts"]["alerts"], page.search_text)
    else:
        rows = airline_rows(snap["airlines"]["airlines"], page.search_text)
    return f"Search: {page.search_text or '—'}   Matches {len(rows)}"


# -- rows (shared by Textual and plain) ----------------------------------

def _status_cell(rec, color):
    status = escape_markup(rec.get("status", ""))
    if color:
        col = STATUS_COLORS.get(rec.get("status_category", ""))
        if col:
            return f"[{col}]{status}[/{col}]"
    return status


def gate_stand_short(rec):
    """Compact gate/stand cell, e.g. ``G63`` / ``W63`` / ``--``.

    HKIA returns the gate as a bare number but the stand already carries its
    letter (``W69``, ``D201``, ``S25``), so only the gate needs a prefix. A
    departure is identified by its gate and an arrival by its stand.
    """
    if rec.get("type") == "departure":
        gate = rec.get("gate")
        return f"G{gate}" if gate else "--"
    return rec.get("stand") or "--"


def route_short(rec):
    """Compact route cell: ``→ KIX`` when leaving for KIX, ``← KIX`` from KIX.

    The bare airport code is ambiguous in a mixed list, and the same number can
    appear as both an arrival and a departure.
    """
    if rec.get("type") == "departure":
        return f"→ {rec.get('destination') or '—'}"
    return f"← {rec.get('origin') or '—'}"


def flight_header(width, marker_width=2):
    """Column header aligned with :func:`flight_row`."""
    return truncate(" " * marker_width + layout(list(FLIGHT_COLUMNS), width - marker_width), width)


def flight_row(rec, width, color=False, selected=False, compact=False):
    """Render one flight record as one or two lines inside ``width`` cells."""
    marker = "> " if selected else "  "
    route = route_short(rec)
    status = _status_cell(rec, color)
    gate = gate_stand_short(rec)
    term = rec.get("terminal", "") or "-"

    if compact:
        # Same column order as the single-line row, so widening a terminal
        # never reorders the fields. The terminal already reads "T1", so it is
        # not prefixed again.
        line1 = truncate(marker + layout(
            [(rec.get("time", "--:--"), 2), (rec.get("flight_number", ""), 3), (status, 4)],
            width - 2), width)
        line2 = truncate("   " + layout(
            [(route, 3), (gate, 1), (term, 1)], width - 3), width)
        return [line1, line2]

    cells = [
        (rec.get("time", "--:--"), 2),
        (rec.get("flight_number", ""), 3),
        (route, 5),
        (status, 4),
        (gate, 3),
        (term, 1),
    ]
    return [truncate(marker + layout(cells, width - 2), width)]


def _short_time(value):
    """``2026-09-11T09:12:00`` -> ``09:12`` (falls back to ``--:--``)."""
    text = str(value or "")
    if "T" in text:
        text = text.split("T", 1)[1]
    return text[:5] if len(text) >= 5 else (text or "--:--")


def alert_header(width, marker_width=2):
    """Column header aligned with :func:`alert_line`."""
    return truncate(" " * marker_width + layout(list(ALERT_COLUMNS), width - marker_width), width)


def alert_line(alert, width, color=False, selected=False):
    """One gate/stand divergence as a single aligned row."""
    marker = "> " if selected else "  "
    change = f"{alert.get('field', '?')} {alert_change_text(alert)}"
    status = escape_markup(alert.get("status", ""))
    if color:
        col = STATUS_COLORS.get(alert.get("status_category", ""))
        if col:
            status = f"[{col}]{status}[/{col}]"
    cells = [
        (_short_time(alert.get("raised_at", "")), 2),
        (escape_markup(alert.get("flight_number", "?")), 3),
        (escape_markup(change), 6),
        (status, 4),
    ]
    return truncate(marker + layout(cells, width - 2), width)


def airline_line(row, width, selected=False):
    marker = "> " if selected else "  "
    return truncate(f"{marker}{row['code']}  {row['name']}", width)


def rule(width, span=78):
    return "-" * max(0, min(span, width))


def date_separator(date_str, width):
    """Dated divider, e.g. ``-- 2026-09-11 ----------------``.

    ``query`` searches two dates across midnight; without a divider the same
    scheduled time on consecutive days reads as a duplicated row.
    """
    label = f"-- {date_str} "
    return truncate(label + "-" * max(0, width - text_width(label)), width)


# -- detail blocks -------------------------------------------------------

def detail_block(rec, width):
    return [truncate(f"{label}: {value}", width) for label, value in detail_lines(rec)]


def alert_detail_lines(snap, alert_id, width):
    alert = next(
        (a for a in snap["alerts"]["alerts"] if alert_identity(a) == alert_id), None)
    if alert is None:
        return ["Alert no longer available"]
    lines = [
        "{} — {} change".format(alert.get("flight_number", "?"), alert.get("field", "?")),
        "",
        f"Changed: {alert_change_text(alert)}",
        f"When:    {alert.get('raised_at', '')}",
        f"Status:  {alert.get('status', '')}",
        "Flight:  {} {} {}".format(
            alert.get("type", ""), alert.get("time", ""), alert.get("date", "")),
        "",
    ]
    flight = next(
        (r for r in snap["flights"]["records"] if r.get("key") == alert.get("key")), None)
    if flight is not None:
        lines.append("current flight")
        lines.extend(detail_block(flight, width))
    else:
        lines.append("(flight not in current data)")
    return lines


def airline_detail(row, width):
    return [truncate(f"{row['code']} — {row['name']}", width)]


# -- body (Textual) ------------------------------------------------------

def _rows_for(state, snap):
    if state.current in FLIGHT_PAGES:
        page = state.pages[state.current]
        return visible_rows(
            snap["flights"], state.current,
            search_text=page.search_text,
            airline=page.airline_filter,
            status=page.status_filter,
        )
    if state.current == ALERTS:
        return alert_rows(snap["alerts"]["alerts"], state.pages[ALERTS].search_text)
    if state.current == AIRLINES:
        return airline_rows(snap["airlines"]["airlines"], state.pages[AIRLINES].search_text)
    return []


def _empty_lines(state, snap):
    if state.current == AIRLINES:
        src = snap["airlines"]
        if src.get("error"):
            return [f"Airlines error: {src['error']} (r refresh)"]
        if not src.get("loaded"):
            return ["Loading airlines…"]
        return ["No airlines found."]
    if snap["flights"].get("source") == "none" and not snap["flights"].get("records"):
        return ["Cannot load data, no cache available.", "Press r to retry."]
    return ["No matches for current filters.", "Press Esc to clear filters."]


def _help_block(available, width):
    return _paged([
        "HELP",
        "1/2/5/6  page        /  search        Enter  detail/apply",
        "Esc      close/clear/back          Tab  focus",
        "up/down/PgUp/PgDn/Home/End  move   f  filter",
        "r refresh   w web   ? help   q quit   Ctrl+Q/Ctrl+C quit",
        "In search, letters/digits/W/Q type text (Ctrl+Q quits).",
    ], available, width)


def _filter_block(state, available, width):
    page = state.pages[state.current]
    return _paged([
        f"FILTER — {PAGE_TITLES[state.current]} / {state.current}",
        f"Status: {page.status_filter or 'ALL'}",
        f"Airline: {page.airline_filter or 'ALL (set from Airlines page)'}",
        "up/down cycles status, Enter applies, Esc closes.",
    ], available, width)


def body_lines(state, snap, width, height, color, detail_scroll=0):
    """Render the body area for the current state (list + overlays)."""
    rows = _rows_for(state, snap)
    tier = layout_tier(width, height)
    if tier == "size_hint":
        return [
            f"Terminal too small: {width}x{height} (min 40x16)",
            "Resize to continue; state is preserved.",
            "Press q to quit, ? for help.",
        ]

    available = max(1, height - 3)
    if state.help_open:
        return _help_block(available, width)
    if state.filter_open and state.current in FLIGHT_PAGES:
        return _filter_block(state, available, width)
    if state.detail_id and tier == "wide":
        return _wide_body(state, snap, rows, width, available, color, detail_scroll)
    if state.detail_id:
        return _detail_overlay(state, snap, rows, width, available, detail_scroll)
    if not rows:
        return [truncate(line, width) for line in _empty_lines(state, snap)[:available]]

    page = state.pages[state.current]
    line_cost = 2 if tier == "compact" else 1
    window = _window(rows, page, available, line_cost)

    out = []
    if state.current in FLIGHT_PAGES:
        header = "COMPACT" if tier == "compact" else flight_header(width)
        out.append(truncate(header, width))
        out.append(rule(width))
    elif state.current == ALERTS:
        out.append(truncate(f"GATE/STAND CHANGES ({len(rows)})", width))
        out.append(truncate(alert_header(width), width))
        out.append(rule(width))
    else:
        out.append(truncate(f"AIRLINES ({len(rows)})", width))
        out.append(rule(width))

    for row in window:
        selected = row["id"] == page.selected_id
        if state.current in FLIGHT_PAGES:
            out.extend(flight_row(row["record"], width, color, selected,
                                  compact=(tier == "compact")))
        elif state.current == ALERTS:
            out.append(alert_line(row["record"], width, color, selected))
        else:
            out.append(airline_line(row, width, selected))
    return out


def _wide_body(state, snap, rows, width, available, color, scroll=0):
    """List (left) + selected detail (right) for wide terminals."""
    page = state.pages[state.current]
    right_width = min(36, max(20, width - 80))
    left_width = width - right_width
    window = _window(rows, page, available, 1)

    if state.current in FLIGHT_PAGES:
        left = [truncate(flight_header(left_width), left_width),
                rule(left_width, left_width - 1)]
        for row in window:
            selected = row["id"] == page.selected_id
            left.extend(flight_row(row["record"], left_width, color, selected))
    elif state.current == ALERTS:
        left = [truncate(alert_header(left_width), left_width),
                rule(left_width, left_width - 1)]
        for row in window:
            selected = row["id"] == page.selected_id
            left.append(alert_line(row["record"], left_width, color, selected))
    else:
        left = [truncate("  AIRLINES", left_width), rule(left_width, left_width - 1)]
        for row in window:
            selected = row["id"] == page.selected_id
            left.append(airline_line(row, left_width, selected))

    right = []
    if state.current in FLIGHT_PAGES:
        rec = next((r["record"] for r in rows if r["id"] == state.detail_id), None)
        if rec is not None:
            right = detail_block(rec, right_width - 2)
    elif state.current == ALERTS:
        right = alert_detail_lines(snap, state.detail_id, right_width - 2)
    else:
        row = next((r for r in rows if r["id"] == state.detail_id), None)
        if row is not None:
            right = airline_detail(row, right_width - 2)
    right = _paged(right, available, right_width - 2, scroll)

    lines = []
    for i in range(max(len(left), len(right))):
        left_line = left[i] if i < len(left) else ""
        right_line = right[i] if i < len(right) else ""
        lines.append(pad(left_line, left_width) + "| " + pad(right_line, right_width - 2))
    return lines


def _detail_overlay(state, snap, rows, width, available, scroll=0):
    """Full-width detail overlay, scrolled by ``scroll`` and bounded by height."""
    if state.current in FLIGHT_PAGES:
        rec = next((r["record"] for r in rows if r["id"] == state.detail_id), None)
        if rec is None:
            return _paged(["Flight no longer available.", "Press Esc to close."], available, width)
        return _paged(detail_block(rec, width), available, width, scroll)
    if state.current == ALERTS:
        return _paged(alert_detail_lines(snap, state.detail_id, width), available, width, scroll)
    row = next((r for r in rows if r["id"] == state.detail_id), None)
    if row is not None:
        return _paged(airline_detail(row, width), available, width, scroll)
    return ["Press Esc to close."]
