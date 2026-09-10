"""
HKG Flight Data v3 - Plain Adapter
Standard-library line-command fallback and non-TTY output.

Reuses the same presenter projection and search rules as the Textual adapter,
but drives the UI one command per line. It never clears the screen, never
reads raw keys and never emits ANSI/color codes, so it is safe for pipes,
scripts, NO_COLOR and terminals without a real UI.
"""

import re
import sys
import time

from .presenter import (
    FLIGHT_PAGES,
    ALERTS,
    AIRLINES,
    DEPARTURES,
    ARRIVALS,
    visible_rows,
    alert_rows,
    airline_rows,
    detail_lines,
)
from .views import freshness, sanitize

DEFAULT_PAGE_SIZE = 20

PAGE_TITLES = {
    DEPARTURES: "Departures",
    ARRIVALS: "Arrivals",
    ALERTS: "Alerts",
    AIRLINES: "Airlines",
}

# Plain output is a pipe / script surface: ANSI escape sequences must never
# reach it, not even their trailing parameters. They are removed before the
# shared sanitiser strips the remaining control codes and markup-like text.
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x9b[0-9;?]*[ -/]*[@-~]"
)


def _clean(text):
    """Return ``text`` safe to write to a pipe: no ANSI, no C0/C1 controls."""
    text = _ANSI_RE.sub("", str(text if text is not None else ""))
    return sanitize(text)


def safe_out(out):
    """Wrap an output callable so every line is cleaned at the boundary."""
    def emit(line=""):
        out(_clean(line))
    return emit


def clamp_offset(offset, total, page_size=DEFAULT_PAGE_SIZE):
    """Clamp a scroll offset to the start of the last non-empty page."""
    if total <= 0 or page_size <= 0:
        return 0
    last = ((total - 1) // page_size) * page_size
    return max(0, min(int(offset or 0), last))


def _flight_row_lines(rows, offset, page_size, header_extra=""):
    """Render flight rows as fixed-width lines (no color)."""
    lines = []
    header = "{:<7} {:<9} {:<22} {:<18} {:<12} {:<5}".format(
        "TIME", "FLIGHT", "ROUTE", "STATUS", "GATE/STAND", "TERM"
    )
    if header_extra:
        header = header_extra + " | " + header
    lines.append(header)
    lines.append("-" * 78)
    start = clamp_offset(offset, len(rows), page_size)
    window = rows[start:start + page_size]
    for row in window:
        rec = row["record"]
        lines.append("{:<7} {:<9} {:<22} {:<18} {:<12} {:<5}".format(
            rec.get("time", "--:--"),
            rec.get("flight_number", ""),
            _trunc(rec.get("destination", "") if rec.get("type") == "departure" else rec.get("origin", ""), 22),
            _trunc(rec.get("status", ""), 18),
            _trunc(_gate_stand(rec), 12),
            rec.get("terminal", "") or "-",
        ))
    return lines


def _alert_lines(rows, offset, page_size):
    lines = ["ACTIVE ALERTS ({})".format(len(rows)), "-" * 78]
    start = clamp_offset(offset, len(rows), page_size)
    for row in rows[start:start + page_size]:
        alert = row["record"]
        lines.append("{} {} {}: {} -> {} | {}".format(
            alert.get("flight_number", "?"),
            alert.get("field", "?"),
            alert.get("old_value", ""),
            alert.get("new_value", ""),
            alert.get("status", ""),
            alert.get("raised_at", ""),
        ))
    return lines


def _airline_lines(rows, offset, page_size):
    lines = ["AIRLINES ({})".format(len(rows)), "-" * 78]
    start = clamp_offset(offset, len(rows), page_size)
    for row in rows[start:start + page_size]:
        lines.append("{}  {}".format(row["code"], row["name"]))
    return lines


def _gate_stand(rec):
    if rec.get("type") == "departure":
        return "Gate {}".format(rec.get("gate")) if rec.get("gate") else "--"
    return "Stand {}".format(rec.get("stand")) if rec.get("stand") else "--"


def _trunc(text, width):
    text = str(text or "")
    return text if len(text) <= width else text[:width - 1] + "…"


def _status_line(snap, now=None, poll_interval=30):
    flights = snap["flights"]
    source = flights.get("source", "none").upper()
    date = flights.get("records_date", "")
    age = _age_text(flights)
    parts = ["Data date {}".format(date or "—"), "Source {}".format(source)]
    if age:
        parts.append(age)
    # Same vocabulary as the TUI header, so STALE / MANUAL / CACHE / ERROR and
    # a plain API OK stay distinguishable on a colourless pipe.
    parts.append(freshness(flights, now=now, poll_interval=poll_interval))
    return " | ".join(parts)


def result_for(snap):
    """Return ``(exit_code, label)`` for the delivered dataset.

    An API result of ``[]`` is a *successful* empty result, not a failure, so
    it exits 0. Only a real failure exits non-zero: an error was recorded, or
    nothing but stale in-memory data / no data at all is available.
    """
    flights = snap["flights"]
    source = flights.get("source", "none")
    error = flights.get("last_error")
    records = flights.get("records") or []
    if source == "api" and not error:
        return 0, "OK (api)" if records else "OK (api returned no flights)"
    if source == "cache" and records:
        note = "; api error: {}".format(error) if error else ""
        return 0, "OK (cache fallback{})".format(note)
    if error:
        return 1, "ERROR ({})".format(error)
    if source == "memory":
        return 1, "ERROR (stale in-memory data, no fresh source)"
    return 1, "ERROR (no data available)"


def _age_text(flights):
    source = flights.get("source", "none")
    if source == "api" and flights.get("last_api_success_at"):
        return "API OK {}".format(flights["last_api_success_at"])
    if source == "cache":
        saved = flights.get("cache_saved_at")
        if saved is None:
            return "CACHE (age UNKNOWN)"
        return "CACHE saved {}".format(saved)
    if source == "memory":
        return "MEMORY / ERROR"
    return ""


def render_block(session, page_name, search, offset, page_size=DEFAULT_PAGE_SIZE):
    """Render one page block as plain-text lines (no color, no cursor codes)."""
    snap = session.snapshot()
    lines = ["HKG | {}".format(_status_line(snap))]
    if page_name in FLIGHT_PAGES:
        page = session.state.pages[page_name]
        rows = visible_rows(
            snap["flights"], page_name,
            search_text=search,
            airline=page.airline_filter,
            status=page.status_filter,
        )
        header_extra = "Search: {}{}{}".format(
            search or "—",
            " Airline: {}".format(page.airline_filter) if page.airline_filter else "",
            " Status: {}".format(page.status_filter) if page.status_filter else "",
        )
        lines.append("{} | Matches {} / Total {}".format(
            PAGE_TITLES[page_name], len(rows),
            sum(1 for r in snap["flights"]["records"] if r.get("type") == ("departure" if page_name == DEPARTURES else "arrival")),
        ))
        lines.extend(_flight_row_lines(rows, offset, page_size, header_extra=header_extra))
    elif page_name == ALERTS:
        rows = alert_rows(snap["alerts"]["alerts"], search)
        lines.extend(_alert_lines(rows, offset, page_size))
    elif page_name == AIRLINES:
        rows = airline_rows(snap["airlines"]["airlines"], search)
        lines.extend(_airline_lines(rows, offset, page_size))
    return lines


def rows_for(session, page_name, search):
    """Visible rows for a page (shared by paging and detail bounds)."""
    snap = session.snapshot()
    if page_name in FLIGHT_PAGES:
        page = session.state.pages[page_name]
        return visible_rows(
            snap["flights"], page_name,
            search_text=search,
            airline=page.airline_filter,
            status=page.status_filter,
        )
    if page_name == ALERTS:
        return alert_rows(snap["alerts"]["alerts"], search)
    if page_name == AIRLINES:
        return airline_rows(snap["airlines"]["airlines"], search)
    return []


def print_block(session, page_name, search, offset, out, page_size=DEFAULT_PAGE_SIZE):
    for line in render_block(session, page_name, search, offset, page_size=page_size):
        out(line)


def run_plain(session, page_size=DEFAULT_PAGE_SIZE,
              input_func=input, out=print, tty=True):
    """
    Run the line-command fallback. Returns a process exit code.

    TTY: one command per line until q/EOF. Non-TTY: print a bounded snapshot
    of the default page and exit. The exit code follows the delivery result,
    not the row count: an API result of ``[]`` is a successful empty result
    and exits 0; only a real failure exits 1.
    """
    emit = safe_out(out)
    if not tty:
        # Bounded wait for the first background refresh so a non-TTY caller
        # prints real data when it is available, then exits.
        deadline = time.time() + 5.0
        while session.poller.snapshot()["revision"] == 0 and time.time() < deadline:
            time.sleep(0.05)
        snap = session.snapshot()
        code, label = result_for(snap)
        for line in render_block(session, DEPARTURES, "", 0, page_size=page_size)[:page_size + 3]:
            emit(line)
        emit("Result: {}".format(label))
        emit("Commands: 1 Departures  2 Arrivals  5 Alerts  6 Airlines  r Refresh  w Web  q Quit")
        return code

    page = DEPARTURES
    search = ""
    offset = 0
    emit("HKG Flight Data — plain mode (enter a command or 'help')")
    try:
        while True:
            print_block(session, page, search, offset, emit, page_size=page_size)
            try:
                raw = input_func("> ")
            except (EOFError, KeyboardInterrupt, StopIteration):
                # End of input is a clean exit, never an unbounded hang.
                emit("")
                break
            if raw is None:
                emit("")
                break
            raw = str(raw).strip()
            if raw == "":
                continue
            lower = raw.lower()
            if lower in ("q", "quit", "exit"):
                break
            if lower in ("1", "2", "5", "6"):
                page = {"1": DEPARTURES, "2": ARRIVALS, "5": ALERTS, "6": AIRLINES}[lower]
                search = ""
                offset = 0
                session.state.current = page
            elif lower in ("n", "next"):
                offset = clamp_offset(
                    offset + page_size, len(rows_for(session, page, search)), page_size)
            elif lower in ("p", "prev", "previous"):
                offset = clamp_offset(
                    offset - page_size, len(rows_for(session, page, search)), page_size)
            elif lower in ("r", "refresh"):
                session.request_refresh()
            elif lower in ("w", "web"):
                session.toggle_web()
            elif lower in ("help", "?"):
                for line in _help_lines():
                    emit(line)
            elif raw.startswith("/"):
                search = raw[1:].strip()
                offset = 0
            elif lower.startswith("detail"):
                part = raw[6:].strip() if lower.startswith("detail ") else ""
                try:
                    number = int(part)
                except (TypeError, ValueError):
                    number = 0
                _print_detail(session, page, search, offset, number, emit, page_size)
            else:
                emit("Unknown command (help for list)")
    finally:
        session.close()
    return 0


def _help_lines():
    return [
        "1 departures  2 arrivals  5 alerts  6 airlines",
        "n / p          next / previous page (clamped to the last page)",
        "/ <terms>      search current page",
        "detail <N>     show detail of row N on the current page",
        "r refresh   w web toggle   help   q quit",
    ]


def _print_detail(session, page, search, offset, number, out, page_size=DEFAULT_PAGE_SIZE):
    """Print detail for 1-based row ``number`` **relative to the page offset**."""
    rows = rows_for(session, page, search)
    start = clamp_offset(offset, len(rows), page_size)
    index = start + number - 1
    if number < 1 or index < 0 or index >= len(rows):
        shown = len(rows[start:start + page_size])
        out("No such row (this page shows rows {}-{})".format(
            start + 1, start + max(0, shown)))
        return
    if page in FLIGHT_PAGES:
        for label, value in detail_lines(rows[index]["record"]):
            out("{}: {}".format(label, value))
    elif page == ALERTS:
        alert = rows[index]["record"]
        out("{} {}: {} -> {} | {}".format(
            alert.get("flight_number", "?"), alert.get("field", "?"),
            alert.get("old_value", ""), alert.get("new_value", ""),
            alert.get("status", "")))
    else:
        out("Detail is available for flight and alert pages")


def is_tty(stream=None):
    """Best-effort TTY detection for stdin (NO_COLOR-safe, no raw mode)."""
    stream = stream if stream is not None else sys.stdin
    return bool(getattr(stream, "isatty", lambda: False)())


def main_plain(session, page_size=DEFAULT_PAGE_SIZE):
    """Entry point used by the CLI selector."""
    tty = is_tty()
    # NO_COLOR is honoured by construction: plain never emits colour or cursor
    # codes, and every line goes through ``safe_out`` before it is written, so
    # NO_COLOR output carries the same information, only without escapes.
    return run_plain(session, page_size=page_size, tty=tty)
