"""
HKG Flight Data v3 - Terminal Views
Pure rendering of the workbench into plain strings.

The Textual adapter turns these strings into widgets; tests snapshot them at
several terminal sizes. When ``color`` is True, rich markup wraps statuses and
the selected row; ``NO_COLOR`` forces ``color=False``.

All geometry here is measured in *display cells*, never in ``len()``: CJK and
full-width characters occupy two cells, and controls / untrusted markup are
removed instead of being rendered.
"""

import re
import unicodedata

from .presenter import (
    DEPARTURES, ARRIVALS, ALERTS, AIRLINES,
    FLIGHT_PAGES,
    visible_rows, alert_rows, airline_rows, detail_lines,
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


# -- display geometry ----------------------------------------------------
# A bracketed sequence is only markup when it names one of the colours this
# module emits; anything else (injected "[bold red]", "[url]", ...) is treated
# as untrusted and stripped instead of being passed through to the renderer.
_MARKUP_RE = re.compile(r"\[/?[A-Za-z][A-Za-z0-9 _#/-]*\]")
ELLIPSIS = "…"


def _is_control(char):
    """C0/C1/DEL control codes never occupy a display cell."""
    return ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F


def _is_combining(char):
    """Combining marks stay attached to the base character they follow."""
    return bool(unicodedata.combining(char)) or unicodedata.category(char) in ("Mn", "Me")


def sanitize(text):
    """Drop control codes and untrusted markup-like sequences from data."""
    text = "".join(char for char in str(text or "") if not _is_control(char))

    def _replace(match):
        name = match.group(0)[1:-1].strip().lstrip("/").strip()
        return match.group(0) if name in STATUS_COLORS.values() else ""

    return _MARKUP_RE.sub(_replace, text)


def _cell_width(char):
    """Display cells for one character (2 for wide/full-width, else 1)."""
    if unicodedata.east_asian_width(char) in ("W", "F"):
        return 2
    return 1


def display_width(text):
    """Width of ``text`` in display cells; markup tags count as zero."""
    return sum(_cell_width(char) for char in _MARKUP_RE.sub("", sanitize(text)))


def _clusters(text):
    """Split into base+combining clusters so truncation never splits them."""
    clusters = []
    for char in text:
        if clusters and _is_combining(char):
            clusters[-1] += char
        else:
            clusters.append(char)
    return clusters


def _tokens(text):
    """Yield ``("open"|"close"|"text", value)`` over tags and clusters."""
    position = 0
    for match in _MARKUP_RE.finditer(text):
        for cluster in _clusters(text[position:match.start()]):
            yield ("text", cluster)
        name = match.group(0)[1:-1].strip()
        yield ("close", name[1:]) if name.startswith("/") else ("open", name)
        position = match.end()
    for cluster in _clusters(text[position:]):
        yield ("text", cluster)


def truncate(text, width):
    """Truncate to ``width`` display cells without leaving markup open.

    CJK counts two cells, combining marks stay with their base character, the
    ellipsis is reserved up front, and any tag opened before the cut is closed
    again so the renderer never sees an unbalanced tag.
    """
    text = sanitize(str(text or ""))
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    if width <= _cell_width(ELLIPSIS):
        return ELLIPSIS
    budget = width - _cell_width(ELLIPSIS)
    parts = []
    used = 0
    open_tags = []
    for kind, value in _tokens(text):
        if kind == "text":
            cost = sum(_cell_width(char) for char in value)
            if used + cost > budget:
                break
            used += cost
            parts.append(value)
        elif kind == "open":
            open_tags.append(value)
            parts.append("[{}]".format(value))
        else:
            if value in open_tags:
                del open_tags[len(open_tags) - 1 - open_tags[::-1].index(value)]
            parts.append("[/{}]".format(value))
    return "".join(parts) + ELLIPSIS + "".join(
        "[/{}]".format(name) for name in reversed(open_tags))


def pad(text, width):
    """Truncate then right-pad with spaces to exactly ``width`` cells."""
    text = truncate(text, width)
    return text + " " * max(0, width - display_width(text))


# Historic private aliases (kept so callers written against them keep working).
_trunc = truncate
_pad = pad


# Column weights shared by the header and every flight row, so the two stay
# aligned at any width. Weights are relative: the space left after the
# single-space gaps is shared out proportionally.
FLIGHT_COLUMN_WEIGHTS = (
    ("TIME", 2),
    ("FLIGHT", 3),
    ("ROUTE", 5),
    ("STATUS", 4),
    ("GATE/STAND", 3),
    ("TERM", 1),
)
# Compact mode splits one record over two lines because a 40-cell terminal
# cannot show six columns side by side.
COMPACT_LINE1_WEIGHTS = (("FLIGHT", 3), ("TIME", 2), ("STATUS", 4))
COMPACT_LINE2_WEIGHTS = (("ROUTE", 3), ("GATE/STAND", 1), ("TERM", 1))


def _layout(cells, width, gap=1):
    """Lay weighted columns out across ``width`` display cells.

    Space left after the mandatory single-space gaps is shared out by weight
    (largest remainder). Every cell is emitted through :func:`pad`, so a row
    degrades gracefully at 40 cells instead of overflowing the terminal, and
    the final :func:`truncate` is only a safety net for degenerate widths.
    """
    cells = [(text, max(0.0, float(weight))) for text, weight in cells]
    count = len(cells)
    if count == 0 or width <= 0:
        return ""
    budget = width - gap * (count - 1)
    if budget < count:
        budget = count
    total = sum(weight for _text, weight in cells)
    if total <= 0:
        shares = [budget // count] * count
        for index in range(budget - sum(shares)):
            shares[index] += 1
    else:
        exact = [budget * weight / total for _text, weight in cells]
        shares = [int(value) for value in exact]
        order = sorted(range(count), key=lambda i: exact[i] - shares[i], reverse=True)
        for index in order[:max(0, budget - sum(shares))]:
            shares[index] += 1
    line = (" " * gap).join(
        pad(text, shares[index]) for index, (text, _weight) in enumerate(cells))
    return truncate(line, width)


def _paged(lines, available, width, scroll=0):
    """Clamp a scrollable block to ``available`` rows at ``width`` cells.

    Nothing is dropped in silence: when the block is taller than the hole it
    lives in, ``scroll`` moves the window and the hidden tail is counted in a
    trailing marker. Callers can therefore page through long detail blocks
    instead of the renderer pretending the rest does not exist.
    """
    lines = [truncate(line, width) for line in lines]
    if available <= 0:
        return []
    if len(lines) <= available:
        return lines
    if available == 1:
        return [truncate("… 1 of {} lines".format(len(lines)), width)]
    keep = available - 1
    scroll = max(0, min(int(scroll or 0), len(lines) - keep))
    window = lines[scroll:scroll + keep]
    hidden = len(lines) - scroll - keep
    if hidden > 0:
        window.append(truncate("… {} more".format(hidden), width))
    return window


def _window(rows, page, available, line_cost=1):
    """Return the slice of ``rows`` that fits, keeping the selection visible.

    ``line_cost`` is how many terminal rows one record needs (2 in compact
    mode). The offset is derived for rendering only — never written back to
    state — so the selected row can never scroll out of sight.
    """
    if not rows:
        return []
    chrome = 2  # header + rule
    capacity = max(1, (max(1, available) - chrome) // max(1, line_cost))
    offset = max(0, min(int(getattr(page, "offset", 0) or 0), len(rows) - 1))
    selected = max(0, min(int(getattr(page, "selected_index", 0) or 0), len(rows) - 1))
    if selected < offset:
        offset = selected
    elif selected >= offset + capacity:
        offset = selected - capacity + 1
    offset = max(0, min(offset, max(0, len(rows) - capacity)))
    return rows[offset:offset + capacity]


def layout_tier(width, height):
    """Return wide/normal/compact/size_hint for a terminal size."""
    if width < 40 or height < 16:
        return "size_hint"
    if width >= 120 and height >= 24:
        return "wide"
    if width >= 80:
        return "normal"
    return "compact"


def _health(snap):
    flights = snap["flights"]
    source = flights.get("source", "none")
    if source == "api":
        return "API", flights.get("last_api_success_at") or "—"
    if source == "cache":
        saved = flights.get("cache_saved_at")
        return "CACHE", (saved or "UNKNOWN AGE")
    if source == "memory":
        return "MEMORY/ERROR", ""
    return "NONE", ""


def _to_epoch(value):
    """Tolerantly convert a snapshot timestamp (epoch or isoformat) to epoch."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value)).timestamp()
    except Exception:
        return None


def freshness(flights, now=None, poll_interval=30):
    """STALE/API OK/CACHE/ERROR/MANUAL/LOADING label for the data source."""
    source = flights.get("source", "none")
    if flights.get("refreshing"):
        return "LOADING"
    if not flights.get("polling_enabled", True):
        return "MANUAL"
    if source == "api":
        epoch = _to_epoch(flights.get("last_api_success_at"))
        if epoch is None:
            return "API OK"
        if now is not None and (now - epoch) > max(2 * poll_interval, 60):
            return "STALE"
        return "API OK"
    if source == "cache":
        epoch = _to_epoch(flights.get("cache_saved_at"))
        if epoch is None:
            return "CACHE (age UNKNOWN)"
        if now is not None and (now - epoch) > max(2 * poll_interval, 60):
            return "STALE"
        return "CACHE"
    if source == "memory":
        return "ERROR"
    return "no data"


def header_line(snap, web, now=None, poll_interval=30, today=None):
    flights = snap["flights"]
    source_label, source_time = _health(snap)
    date = flights.get("records_date", "")
    if today is not None and date and date != today:
        date = "{} (previous)".format(date)
    text = " HKG FLIGHT | Data date {} | {}".format(date or "—", freshness(flights, now, poll_interval))
    if source_time:
        text += " | {}".format(source_time)
    if flights.get("last_error"):
        text += " | ERR"
    if web["status"] == "on":
        text += " | Web :{} ON".format(web["port"])
    elif web["status"] == "error":
        text += " | Web ERROR (port {})".format(web["port"])
    return text


def nav_line(state, alerts_count, poll_enabled, web_status):
    parts = []
    for page in (DEPARTURES, ARRIVALS, ALERTS, AIRLINES):
        key = PAGE_KEYS[page]
        label = PAGE_TITLES[page]
        if page == ALERTS and alerts_count:
            label = "{} {}".format(label, alerts_count)
        marker = "[" if state.current == page else " "
        close = "]" if state.current == page else ""
        parts.append("{}{} {}{}".format(marker, key, label, close))
    poll = "Poll ON" if poll_enabled else "Poll OFF"
    web = "Web {}".format(web_status.upper())
    return " " + "  ".join(parts) + "   " + poll + "   " + web


def _status_cell(rec, color):
    status = rec.get("status", "")
    if color:
        col = STATUS_COLORS.get(rec.get("status_category", ""))
        if col:
            return "[{}]{}[/{}]".format(col, status, col)
    return status


def _gate_stand(rec):
    if rec.get("type") == "departure":
        g = rec.get("gate")
        return "G{}".format(g) if g else "--"
    s = rec.get("stand")
    return "S{}".format(s) if s else "--"


def _flight_row(rec, color, selected, width, compact=False):
    """Render one flight row inside ``width`` display cells.

    Compact mode spreads a record over two lines: line 1 carries flight /
    time / status, line 2 carries route / gate-stand / terminal. The selection
    marker is emitted first on line 1 so it survives truncation.
    """
    marker = "> " if selected else "  "
    time = rec.get("time", "--:--")
    flight = rec.get("flight_number", "")
    status = _status_cell(rec, color)
    gate = _gate_stand(rec)
    term = rec.get("terminal", "") or "-"
    route = (rec.get("destination") if rec.get("type") == "departure"
             else rec.get("origin"))
    if compact:
        return [
            marker + _layout([(flight, 3), (time, 2), (status, 4)], width - 2),
            "   " + _layout([(route, 3), (gate, 1), ("T" + term, 1)], width - 3),
        ]
    cells = [(time, 2), (flight, 3), (route, 5), (status, 4), (gate, 3), (term, 1)]
    return [marker + _layout(cells, width - 2)]


def _flight_header(width):
    return "  " + _layout(list(FLIGHT_COLUMN_WEIGHTS), width - 2)


def _rule(width, span=78):
    return "-" * max(0, min(span, width))


def _detail_block(rec, width, color):
    lines = []
    for label, value in detail_lines(rec):
        lines.append(truncate("{}: {}".format(label, value), width))
    return lines


def _alert_detail_lines(session_snap, alert_id, width):
    alerts = session_snap["alerts"]["alerts"]
    alert = None
    for candidate in alerts:
        from .presenter import _alert_identity
        if _alert_identity(candidate) == alert_id:
            alert = candidate
            break
    if alert is None:
        return ["Alert no longer available"]
    lines = [
        "Alert: {}".format(alert.get("flight_number", "?")),
        "Change: {} {} -> {}".format(
            alert.get("field", "?"), alert.get("old_value", ""), alert.get("new_value", "")),
        "Status: {}".format(alert.get("status", "")),
        "Raised: {}".format(alert.get("raised_at", "")),
    ]
    records = session_snap["flights"]["records"]
    flight = None
    for rec in records:
        if rec.get("key") == alert.get("key"):
            flight = rec
            break
    if flight is not None:
        lines.append("")
        lines.extend(_detail_block(flight, width, False))
    else:
        lines.append("")
        lines.append("(flight not in current data)")
    return lines


def _airline_detail(row, width):
    return [truncate("{} — {}".format(row["code"], row["name"]), width)]


def body_lines(state, snap, width, height, color, detail_scroll=0):
    """Render the body area for the current state (list + overlays).

    ``detail_scroll`` pages long detail blocks; it is optional so existing
    callers keep working and the app layer can wire a scroll key later.
    """
    rows = []
    if state.current in FLIGHT_PAGES:
        page = state.pages[state.current]
        rows = visible_rows(
            snap["flights"], state.current,
            search_text=page.search_text,
            airline=page.airline_filter,
            status=page.status_filter,
        )
    elif state.current == ALERTS:
        rows = alert_rows(snap["alerts"]["alerts"], state.pages[ALERTS].search_text)
    elif state.current == AIRLINES:
        rows = airline_rows(snap["airlines"]["airlines"], state.pages[AIRLINES].search_text)

    tier = layout_tier(width, height)
    if tier == "size_hint":
        return [
            "Terminal too small: {}x{} (min 40x16)".format(width, height),
            "Resize to continue; state is preserved.",
            "Press q to quit, ? for help.",
        ]

    available = max(1, height - 3)

    if state.help_open:
        return _help_block(available, width, tier)

    if state.filter_open and state.current in FLIGHT_PAGES:
        return _filter_block(state, snap, available, width)

    if state.detail_id and tier == "wide":
        return _wide_body(state, snap, rows, width, available, color, detail_scroll)

    if state.detail_id:
        return _detail_overlay(state, snap, rows, width, available, detail_scroll)

    if not rows:
        empty = _empty_lines(state, snap)
        return [truncate(line, width) for line in empty[:max(1, available)]]

    page = state.pages[state.current]
    # Compact rows cost two terminal lines each; cap the slice so the whole
    # body stays inside ``available`` at any size.
    line_cost = 2 if tier == "compact" else 1
    window = _window(rows, page, available, line_cost)

    out = []
    if state.current in FLIGHT_PAGES:
        out.append(_trunc(_flight_header(width) if tier != "compact" else "COMPACT", width))
        out.append(_rule(width))
    elif state.current == ALERTS:
        out.append(_trunc("ACTIVE ALERTS ({})".format(len(rows)), width))
        out.append(_rule(width))
    else:
        out.append(_trunc("AIRLINES ({})".format(len(rows)), width))
        out.append(_rule(width))

    for row in window:
        selected = row["id"] == page.selected_id
        if state.current in FLIGHT_PAGES:
            rec = row["record"]
            out.extend(_flight_row(rec, color, selected, width, compact=(tier == "compact")))
        elif state.current == ALERTS:
            alert = row["record"]
            line = "{}{} {}: {} -> {}".format(
                "> " if selected else "  ",
                alert.get("flight_number", "?"),
                alert.get("field", "?"),
                alert.get("old_value", ""),
                alert.get("new_value", ""),
            )
            out.append(truncate(line, width))
        else:
            line = "{}{}  {}".format("> " if selected else "  ", row["code"], row["name"])
            out.append(truncate(line, width))
    return out


def _empty_lines(state, snap):
    """Empty-state copy; kept verbatim so business meaning does not drift."""
    if state.current == AIRLINES:
        src = snap["airlines"]
        if src.get("error"):
            return ["Airlines error: {} (r refresh)".format(src["error"])]
        if not src.get("loaded"):
            return ["Loading airlines…"]
        return ["No airlines found."]
    if snap["flights"].get("source") == "none" and not snap["flights"].get("records"):
        return ["Cannot load data, no cache available.", "Press r to retry."]
    return ["No matches for current filters.", "Press Esc to clear filters."]


def _help_block(available, width, tier):
    lines = [
        "HELP",
        "1/2/5/6  page        /  search        Enter  detail/apply",
        "Esc      close/clear/back          Tab  focus",
        "up/down/PgUp/PgDn/Home/End  move   f  filter",
        "r refresh   w web   ? help   q quit   Ctrl+Q/Ctrl+C quit",
        "In search, letters/digits/W/Q type text (Ctrl+Q quits).",
    ]
    return _paged(lines, available, width)


def _filter_block(state, snap, available, width):
    page = state.pages[state.current]
    lines = [
        "FILTER — {} / {}".format(PAGE_TITLES[state.current], state.current),
        "Status: {}".format(page.status_filter or "ALL"),
        "Airline: {}".format(page.airline_filter or "ALL (set from Airlines page)"),
        "up/down cycles status, Enter applies, Esc closes.",
    ]
    return _paged(lines, available, width)


def _wide_body(state, snap, rows, width, available, color, scroll=0):
    """List (left) + selected-flight detail (right) for wide terminals."""
    page = state.pages[state.current]
    right_width = min(36, max(20, width - 80))
    left_width = width - right_width
    window = _window(rows, page, available, 1)

    left = []
    left.append(_trunc(_flight_header(left_width), left_width))
    left.append(_rule(left_width, left_width - 1))
    for row in window:
        selected = row["id"] == page.selected_id
        if state.current in FLIGHT_PAGES:
            left.extend(_flight_row(row["record"], color, selected, left_width))
        else:
            left.append(truncate("{}{}".format("> " if selected else "  ", row["code"]),
                                 left_width))

    right = []
    if state.current in FLIGHT_PAGES:
        rec = None
        for row in rows:
            if row["id"] == state.detail_id:
                rec = row["record"]
                break
        if rec is not None:
            right = _detail_block(rec, right_width - 2, color)
    elif state.current == ALERTS:
        right = _alert_detail_lines(snap, state.detail_id, right_width - 2)
    else:
        for row in rows:
            if row["id"] == state.detail_id:
                right = _airline_detail(row, right_width - 2)
                break
    right = _paged(right, available, right_width - 2, scroll)

    lines = []
    max_lines = max(len(left), len(right))
    for i in range(max_lines):
        left_line = left[i] if i < len(left) else ""
        right_line = right[i] if i < len(right) else ""
        lines.append(_pad(left_line, left_width) + "| " + _pad(right_line, right_width - 2))
    return lines


def _detail_overlay(state, snap, rows, width, available, scroll=0):
    """Full-width detail overlay, scrolled by ``scroll`` and bounded by height."""
    if state.current in FLIGHT_PAGES:
        rec = None
        for row in rows:
            if row["id"] == state.detail_id:
                rec = row["record"]
                break
        if rec is None:
            return _paged(["Flight no longer available.", "Press Esc to close."],
                          available, width)
        return _paged(_detail_block(rec, width, False), available, width, scroll)
    if state.current == ALERTS:
        return _paged(_alert_detail_lines(snap, state.detail_id, width),
                      available, width, scroll)
    for row in rows:
        if row["id"] == state.detail_id:
            return _paged(_airline_detail(row, width), available, width, scroll)
    return ["Press Esc to close."]


def search_line(state, snap):
    page = state.pages[state.current]
    if state.current in FLIGHT_PAGES:
        rows = visible_rows(
            snap["flights"], state.current,
            search_text=page.search_text,
            airline=page.airline_filter,
            status=page.status_filter,
        )
        total = len(snap["flights"]["records"])
        matched = len(rows)
        text = "Search: {}".format(page.search_text if page.search_text else "—")
        if page.airline_filter:
            text += "   Airline: {}".format(page.airline_filter)
        if page.status_filter:
            text += "   Status: {}".format(page.status_filter)
        text += "   Matches {} / Total {}".format(matched, total)
        return text
    if state.current == ALERTS:
        rows = alert_rows(snap["alerts"]["alerts"], page.search_text)
        return "Search: {}   Matches {}".format(page.search_text or "—", len(rows))
    rows = airline_rows(snap["airlines"]["airlines"], page.search_text)
    return "Search: {}   Matches {}".format(page.search_text or "—", len(rows))


def footer_line(tier, state):
    if state.focus == "search":
        return " / typing…  Enter submit  Esc cancel  Ctrl+Q quit"
    return "/ Search  Enter Detail  f Filter  r Refresh  w Web  ? Help  q Quit"
