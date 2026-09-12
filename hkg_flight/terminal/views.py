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
from ..utils import terminal_width

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
# Used by nav_line when the full titles would wrap.
PAGE_SHORT = {
    DEPARTURES: "Dep",
    ARRIVALS: "Arr",
    ALERTS: "Alerts",
    AIRLINES: "Air",
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

# Screen rows the front-end spends on its own bars rather than on the body:
# header, nav, search row and footer (see ``theme.tcss``). ``body_lines`` is
# given the terminal height and must leave these alone, or the body widget
# clips the last row of the list.
CHROME_ROWS = 4

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


# Columns shared by the header and every flight row, so the two stay aligned at
# any width. Each entry is ``(label, weight, minimum)``:
#
# * ``minimum`` is the natural width of the column's content - the longest value
#   the API actually produces. A column is given its minimum first, so a
#   three-cell field such as ``T1`` is never handed twenty cells while the
#   status column is squeezed into a truncated stub.
# * ``weight`` shares out whatever is left over, which is what the flexible
#   columns (route, status) genuinely need.
#
# Measured maxima: time 5, flight number 7 (``CX256D``), gate/stand 5 (``D311``),
# terminal 3 (``T1``), status 26 (``At gate 23:47 (06/09/2026)``).
#
# GATE/STAND and TERM are the exceptions: their data needs 5 and 3 cells but
# their labels need 10 and 4, and a header that shows an ellipsis looks broken.
# The extra cells are slack the flexible columns would only have spent on
# trailing whitespace.
FLIGHT_COLUMNS = (
    ("TIME", 2, 5),
    ("FLIGHT", 3, 7),
    ("ROUTE", 5, 6),
    ("STATUS", 4, 26),
    ("GATE/STAND", 3, 10),
    ("TERM", 1, 4),
)

# Alert rows: when the change was seen, which flight, what moved, current status.
ALERT_COLUMNS = (
    ("CHANGED", 2, 7),
    ("FLIGHT", 3, 7),
    ("CHANGE", 6, 12),
    ("STATUS", 4, 12),
)

# Single source of truth for a column's weight and minimum, so the header and
# the rows can never drift apart.
_FLIGHT_COLUMN = {label: (weight, minimum) for label, weight, minimum in FLIGHT_COLUMNS}
_ALERT_COLUMN = {label: (weight, minimum) for label, weight, minimum in ALERT_COLUMNS}


def _pick(columns, label, value):
    """One column cell, taking its weight and minimum from a shared table."""
    weight, minimum = columns[label]
    return (value, weight, minimum)


def layout(cells, width, gap=1):
    """Lay columns across ``width`` display cells.

    A cell is ``(text, weight)`` or ``(text, weight, minimum)``. Every column is
    given its ``minimum`` first and the remainder is shared out by weight
    (largest remainder). When the minimums cannot all fit - a very narrow
    terminal - they are dropped and the weights alone decide, so the row degrades
    to the old proportional split instead of overflowing.

    Every cell goes through :func:`pad`, so the result is exactly ``width`` cells
    (or shorter when the weights leave nothing to give).
    """
    cells = [(cell[0], max(0.0, float(cell[1])),
              max(0, int(cell[2])) if len(cell) > 2 else 0) for cell in cells]
    count = len(cells)
    if count == 0 or width <= 0:
        return ""
    budget = max(count, width - gap * (count - 1))
    total = sum(weight for _text, weight, _minimum in cells)

    minimums = [minimum for _text, _weight, minimum in cells]
    if sum(minimums) <= budget:
        shares = list(minimums)
        left = budget - sum(shares)
    else:
        shares = [0] * count
        left = budget

    if total <= 0:
        extra = [left // count] * count
    else:
        exact = [left * weight / total for _text, weight, _minimum in cells]
        extra = [int(value) for value in exact]
        order = sorted(range(count), key=lambda i: exact[i] - extra[i], reverse=True)
        for index in order[:left - sum(extra)]:
            extra[index] += 1
    shares = [shares[i] + extra[i] for i in range(count)]

    line = (" " * gap).join(
        pad(text, shares[index]) for index, (text, _weight, _minimum) in enumerate(cells))
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


def _window(rows, page, capacity):
    """Slice of ``rows`` that fits in ``capacity`` display rows.

    ``capacity`` counts *rows*, not lines: the caller works it out with
    :func:`row_capacity`, which owns the header and line-cost rules, so the
    list and the page-step key cannot disagree about where a screen ends.

    The offset is derived for rendering only and never written back to state,
    so the selected row can never scroll out of sight.
    """
    if not rows:
        return []
    capacity = max(1, int(capacity or 1))
    offset = max(0, min(int(getattr(page, "offset", 0) or 0), len(rows) - 1))
    selected = max(0, min(int(getattr(page, "selected_index", 0) or 0), len(rows) - 1))
    if selected < offset:
        offset = selected
    elif selected >= offset + capacity:
        offset = selected - capacity + 1
    offset = max(0, min(offset, max(0, len(rows) - capacity)))
    return rows[offset:offset + capacity]


def row_capacity(state, rows, width, height):
    """Flight rows the body's list area holds - one screen for the page keys.

    This is the single owner of "how many rows fit": :func:`body_lines` renders
    its window with it, and the workbench steps its time anchor by it, so one
    press of the page key lands exactly where the next screen begins.
    """
    tier = layout_tier(width, height)
    if tier == "size_hint":
        return 1
    available = max(1, height - CHROME_ROWS)
    line_cost = 2 if tier == "compact" else 1
    head = _list_head(state, rows, width, tier)
    return max(1, max(1, available - len(head)) // line_cost)


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
    parts = [f"Data date {date_text(flights)}", f"Source {source}"]
    if flights.get("last_error"):
        parts.append(f"error: {flights['last_error']}")
    parts.append(freshness(flights, now=now, poll_interval=poll_interval))
    return " | ".join(parts)


def plain_header_line(snap, width=None):
    """The plain adapter's header: ``HKG | <status summary>``, cut to ``width``.

    The plain adapter prints raw lines and has no second row to spill into, so
    a header that is too long wraps and pushes the table apart. The TUI header
    drops fields one at a time until it fits; here the line is simply cut. The
    error text comes from the API and has no length bound, and around midnight
    the date text grows by ``" +1"``, so the cut is not a corner case.
    """
    width = terminal_width() if width is None else width
    return truncate("HKG | " + status_line(snap), width)


def fit(forms, width, **fields):
    """The first of ``forms`` that fits ``width`` cells; empty when none does.

    Status bars, footers and hints are written as a ladder: the longest form
    that fits wins, and a form that would wrap is never used. A form that
    cannot even be formatted is skipped rather than raising.

    Forms must not contain anything that looks like rich markup. They are
    measured with :func:`text_width`, which strips tags - a literal ``[n]``
    would measure short and be chosen at a width where it does not fit.
    """
    for form in forms:
        try:
            text = form.format(**fields)
        except (KeyError, IndexError, ValueError):
            continue
        if text_width(text) <= width:
            return text
    return ""


def header_line(snap, web, now=None, poll_interval=30, today=None, width=None):
    """Top status bar: data date, freshness and the web server.

    Built longest-first and cut back to ``width``. The source timestamp is the
    first thing to go, then the web indicator, then the wordmark; the freshness
    label and any error are never dropped.
    """
    width = terminal_width() if width is None else width
    flights = snap["flights"]
    _source_label, source_time = _health(snap)
    date = date_text(flights)
    # "previous" means the board carries no data for today at all - a snapshot
    # left over from an earlier run. A window that merely *starts* yesterday is
    # not previous: it is the current board, and says so with "+1".
    board_dates = [d for d in (flights.get("records_dates") or []) if d]
    if not board_dates and flights.get("records_date"):
        board_dates = [flights["records_date"]]
    if today is not None and board_dates and today not in board_dates:
        date = f"{date} (previous)"
    fresh = freshness(flights, now, poll_interval)
    error = "ERR" if flights.get("last_error") else ""

    if web["status"] == "on":
        web_text = f"Web :{web['port']} ON"
    elif web["status"] == "error":
        web_text = f"Web ERROR (port {web['port']})"
    else:
        web_text = ""

    forms = []
    for wordmark, verbose, with_time, with_web in (
            ("HKG FLIGHT", True, True, True),
            ("HKG FLIGHT", True, False, True),
            ("HKG FLIGHT", True, False, False),
            ("HKG", True, False, False),
            ("HKG", False, False, False)):
        pieces = [wordmark, f"Data date {date or '—'}" if verbose else (date or "—"), fresh]
        if error:
            pieces.append(error)
        if with_time and source_time:
            pieces.append(source_time)
        if with_web and web_text:
            pieces.append(web_text)
        forms.append(" " + " | ".join(pieces))

    return fit(forms, width) or truncate(forms[-1], width)


def nav_line(state, alerts_count, poll_enabled, web_status, width=None):
    """Page switcher, shortening its labels before it will wrap."""
    width = terminal_width() if width is None else width
    poll = "Poll ON" if poll_enabled else "Poll OFF"
    web = f"Web {web_status.upper()}"

    forms = []
    for titles, with_state in ((PAGE_TITLES, True), (PAGE_SHORT, True), (PAGE_SHORT, False)):
        parts = []
        for page in (DEPARTURES, ARRIVALS, ALERTS, AIRLINES):
            label = titles[page]
            if page == ALERTS and alerts_count:
                label = f"{label} {alerts_count}"
            marker = "[" if with_state and state.current == page else " "
            close = "]" if with_state and state.current == page else ""
            parts.append(f"{marker}{PAGE_KEYS[page]} {label}{close}")
        body = "  ".join(parts)
        for tail in (f"   {poll}   {web}", ""):
            forms.append(" " + body + tail)
    forms.append(" " + " ".join(f"[{PAGE_KEYS[p]}]" for p in
                                (DEPARTURES, ARRIVALS, ALERTS, AIRLINES)))

    return fit(forms, width) or truncate(forms[-1], width)


def footer_line(tier, state, width=None):
    """Key hints, dropping the least useful keys before the line will wrap."""
    width = terminal_width() if width is None else width
    if state.focus == "search":
        forms = (
            " / typing…  Enter submit  Esc cancel  Ctrl+Q quit",
            " / typing…  Enter submit  Esc cancel",
            " / typing…  Enter  Esc",
        )
    else:
        # These strings are printed raw but measured with ``text_width``, which
        # strips markup. ``[ ]`` is safe (the tag pattern needs a letter after
        # the bracket) - a form like ``[t]`` would measure short and be chosen
        # at a width where it does not fit.
        forms = (
            " / Search  Enter Detail  [ ] Time  t Now  f Filter  r Refresh  w Web  ? Help  q Quit",
            " / Search  Enter Detail  [ ] Time  t Now  f Filter  r Refresh  w Web  ? q",
            " / Search  Enter Detail  [ ] Time  t Now  f r w  ? q",
            " / Search  Enter  [ ] Time  t Now  f r w  ? q",
            " / Search  Enter  f r w  ? q",
            " / ? q",
        )
    return fit(forms, width) or truncate(forms[-1], width)


# -- dates and the time anchor -------------------------------------------

def clock_text(minutes):
    """``18:05`` for minutes since midnight; empty for "no anchor"."""
    if minutes is None:
        return ""
    minutes = int(minutes) % (24 * 60)
    return "{:02d}:{:02d}".format(minutes // 60, minutes % 60)


def short_date(date_str):
    """``2026-09-13`` -> ``09-13``; empty when there is no date."""
    date_str = str(date_str or "")
    return date_str[5:] if len(date_str) == 10 else date_str


def date_text(flights):
    """The board's service date(s): ``2026-09-12``, or ``2026-09-12 +1``.

    Around midnight the board carries two service dates, and naming only one of
    them would claim the other day's flights belong to it. ``+1`` is how many
    further days the window reaches.
    """
    dates = [d for d in (flights.get("records_dates") or []) if d]
    if not dates:
        return flights.get("records_date", "") or "—"
    if len(dates) == 1:
        return dates[0]
    return "{} +{}".format(dates[0], len(dates) - 1)


def anchor_label(page, day=None):
    """How the page's time anchor is set: ``Now 18:05`` / ``Pinned 09-13 01:30``.

    "Now" means the top of the list keeps following the board's clock; the
    first manual move or page step pins it, and the label says which, because
    that is the difference between a list that will jump on the next refresh
    and one that will not.

    The date appears only when the anchor is not on ``day``, the board's own
    clock date: on a board that spans midnight, "Pinned 01:30" does not say
    which night that is.
    """
    if page.anchor_minutes is None:
        return ""
    when = clock_text(page.anchor_minutes)
    anchor_date = getattr(page, "anchor_date", None)
    if anchor_date and day and anchor_date != day:
        when = "{} {}".format(short_date(anchor_date), when)
    return ("Now " if page.anchor_auto else "Pinned ") + when


def search_line(state, snap, width=None):
    """Search/filter state, the time anchor and the match count for the page."""
    width = terminal_width() if width is None else width
    page = state.pages[state.current]
    if state.current in FLIGHT_PAGES:
        rows = visible_rows(
            snap["flights"], state.current,
            search_text=page.search_text,
            airline=page.airline_filter,
            status=page.status_filter,
        )
        filters = []
        if page.airline_filter:
            filters.append(f"Airline: {page.airline_filter}")
        if page.status_filter:
            filters.append(f"Status: {page.status_filter}")
        total = sum(1 for r in snap["flights"].get("records", [])
                    if r.get("type") == ("departure" if state.current == DEPARTURES else "arrival"))
        counts = f"Matches {len(rows)} / Total {total}"
        # With nothing typed and nothing filtered the counts are the whole
        # story, and "Search: —" is a label with no value.
        search = ""
        if page.search_text or filters:
            search = "Search: " + (page.search_text or "—")
            if filters:
                search += "   " + "   ".join(filters)
        anchor = anchor_label(page, day=snap["flights"].get("records_date"))
        # A ladder, not a truncation: the counts are what the user acts on, so
        # the anchor goes first and the search summary second.
        forms = []
        if search:
            forms.append(f"{search}   {anchor}   {counts}" if anchor
                         else f"{search}   {counts}")
        if anchor:
            forms.append(f"{anchor}   {counts}")
        forms.append(counts)
        return fit(forms, width) or truncate(counts, width)
    if state.current == ALERTS:
        rows = alert_rows(snap["alerts"]["alerts"], page.search_text)
    else:
        rows = airline_rows(snap["airlines"]["airlines"], page.search_text)
    text = f"Search: {page.search_text or '—'}   Matches {len(rows)}"
    return truncate(text, width)


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
    """Column header aligned with :func:`flight_row`.

    The label is *not* given a minimum of its own: inflating a column so its
    label fits would shift every column and break the alignment with the rows.
    The minimums in :data:`FLIGHT_COLUMNS` already allow for the labels.
    """
    return truncate(" " * marker_width + layout(list(FLIGHT_COLUMNS), width - marker_width),
                    width)


def _flight_cell(label, value):
    """One flight column cell, taking its weight and minimum from the table."""
    return _pick(_FLIGHT_COLUMN, label, value)


def flight_row(rec, width, color=False, selected=False, compact=False):
    """Render one flight record as one or two lines inside ``width`` cells."""
    marker = "> " if selected else "  "
    route = route_short(rec)
    status = _status_cell(rec, color)
    gate = gate_stand_short(rec)
    term = rec.get("terminal", "") or "-"
    time_cell = rec.get("time", "--:--")
    number = rec.get("flight_number", "")

    if compact:
        # Same column order as the single-line row, so widening a terminal never
        # reorders the fields. Splitting the status onto its own line gives it
        # the whole width it needs instead of fighting time and flight number
        # for it - the single-line row cannot fit "At gate 23:47 (06/09/2026)".
        line1 = truncate(marker + layout([
            _flight_cell("TIME", time_cell),
            _flight_cell("FLIGHT", number),
            _flight_cell("STATUS", status),
        ], width - 2), width)
        line2 = truncate("   " + layout([
            _flight_cell("ROUTE", route),
            _flight_cell("GATE/STAND", gate),
            _flight_cell("TERM", term),
        ], width - 3), width)
        return [line1, line2]

    cells = [
        _flight_cell("TIME", time_cell),
        _flight_cell("FLIGHT", number),
        _flight_cell("ROUTE", route),
        _flight_cell("STATUS", status),
        _flight_cell("GATE/STAND", gate),
        _flight_cell("TERM", term),
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
    return truncate(" " * marker_width + layout(list(ALERT_COLUMNS), width - marker_width),
                    width)


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
        _pick(_ALERT_COLUMN, "CHANGED", _short_time(alert.get("raised_at", ""))),
        _pick(_ALERT_COLUMN, "FLIGHT", escape_markup(alert.get("flight_number", "?"))),
        _pick(_ALERT_COLUMN, "CHANGE", escape_markup(change)),
        _pick(_ALERT_COLUMN, "STATUS", status),
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
        "[ ]  next/prev screen from the clock   t  follow it again",
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


def _list_head(state, rows, width, tier):
    """Title / column header / rule that sit above the rows for a page."""
    if state.current in FLIGHT_PAGES:
        # A compact row splits the columns across two lines, so no single
        # header lines up with it. The CLI drops the header in that case too,
        # rather than printing a placeholder - the row marker and the route
        # arrow carry the meaning.
        head = [] if tier == "compact" else [truncate(flight_header(width), width)]
        return head + [rule(width)]
    if state.current == ALERTS:
        return [
            truncate(f"GATE/STAND CHANGES ({len(rows)})", width),
            truncate(alert_header(width), width),
            rule(width),
        ]
    return [truncate(f"AIRLINES ({len(rows)})", width), rule(width)]


def body_lines(state, snap, width, height, color, detail_scroll=0):
    """Render the body area for the current state (list + overlays).

    ``height`` is the terminal height; :data:`CHROME_ROWS` of it belong to the
    front-end's own bars, so the lines returned here always fit the body widget.
    """
    rows = _rows_for(state, snap)
    tier = layout_tier(width, height)
    if tier == "size_hint":
        return [truncate(line, width) for line in (
            f"Terminal too small: {width}x{height} (min 40x16)",
            "Resize to continue; state is preserved.",
            "Press q to quit, ? for help.",
        )]

    available = max(1, height - CHROME_ROWS)
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
    head = _list_head(state, rows, width, tier)
    window = _window(rows, page, row_capacity(state, rows, width, height))

    out = list(head)
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
    # The left column carries a header and a rule above its rows.
    window = _window(rows, page, max(1, available - 2))

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
