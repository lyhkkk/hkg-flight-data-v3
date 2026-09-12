"""
HKG Flight Data v3 - Plain Adapter.

Standard-library line-command fallback for pipes, scripts, ``NO_COLOR`` and
terminals without the enhanced UI. It drives the same presenter and views as
the Textual adapter, one command per line.

It never clears the screen, never reads raw keys and never emits ANSI codes,
so its output is identical with or without a colour-capable terminal.
"""

import sys
import time

from ..utils import terminal_width
from .presenter import (
    FLIGHT_PAGES,
    ALERTS,
    AIRLINES,
    DEPARTURES,
    ARRIVALS,
    alert_change_text,
    detail_lines,
)
from . import views

DEFAULT_PAGE_SIZE = 20


def clamp_offset(offset, total, page_size=DEFAULT_PAGE_SIZE):
    """Clamp a scroll offset to the start of the last non-empty page."""
    if total <= 0 or page_size <= 0:
        return 0
    last = ((total - 1) // page_size) * page_size
    return max(0, min(int(offset or 0), last))


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
        note = f"; api error: {error}" if error else ""
        return 0, f"OK (cache fallback{note})"
    if error:
        return 1, f"ERROR ({error})"
    if source == "memory":
        return 1, "ERROR (stale in-memory data, no fresh source)"
    return 1, "ERROR (no data available)"


def _rows(session, page_name, search):
    """Visible rows for a page; the plain search term drives the shared state."""
    session.state.pages[page_name].search_text = search
    return session.rows_for(page_name)


def _title(session, page_name, search, count, width, total=None):
    """Page title plus the active search/filter; cut to ``width``.

    The search term is the user's own text and the title grows with the filter
    state, so this line is clamped like every other rendered line.
    """
    page = session.state.pages[page_name]
    text = views.PAGE_TITLES[page_name]
    if search:
        text += f" | Search: {search}"
    if page.airline_filter:
        text += f" | Airline: {page.airline_filter}"
    if page.status_filter:
        text += f" | Status: {page.status_filter}"
    if total is None:
        return views.truncate(f"{text} ({count})", width)
    return views.truncate(f"{text} | Matches {count} / Total {total}", width)


def render_block(session, page_name, search, offset, page_size=DEFAULT_PAGE_SIZE,
                 width=None):
    """Render one page block as plain-text lines.

    ``width`` defaults to the real terminal, so a narrow window (a phone
    terminal) gets the two-line compact row instead of lines that wrap.
    """
    width = width or terminal_width()
    compact = views.is_compact(width)
    snap = session.snapshot()
    lines = [views.plain_header_line(snap, width)]
    rows = _rows(session, page_name, search)
    start = clamp_offset(offset, len(rows), page_size)
    window = rows[start:start + page_size]

    if page_name in FLIGHT_PAGES:
        total = sum(
            1 for r in snap["flights"].get("records", [])
            if r.get("type") == ("departure" if page_name == DEPARTURES else "arrival"))
        lines.append(_title(session, page_name, search, len(rows), width, total))
        if not compact:
            lines.append(views.flight_header(width))
        lines.append(views.rule(width))
        for row in window:
            lines.extend(views.flight_row(row["record"], width, compact=compact))
    elif page_name == ALERTS:
        lines.append(_title(session, page_name, search, len(rows), width))
        lines.append(views.alert_header(width))
        lines.append(views.rule(width))
        for row in window:
            lines.append(views.alert_line(row["record"], width))
    else:
        lines.append(_title(session, page_name, search, len(rows), width))
        lines.append(views.rule(width))
        for row in window:
            lines.append(views.airline_line(row, width))
    return lines


def print_block(session, page_name, search, offset, out, page_size=DEFAULT_PAGE_SIZE):
    for line in render_block(session, page_name, search, offset, page_size=page_size):
        out(line)


def run_plain(session, page_size=DEFAULT_PAGE_SIZE,
              input_func=input, out=print, tty=True):
    """Run the line-command fallback; returns a process exit code.

    TTY: one command per line until q/EOF. Non-TTY: print a bounded snapshot of
    the default page and exit. The exit code follows the delivery result, not
    the row count.
    """
    if not tty:
        # Bounded wait for the first background refresh so a non-TTY caller
        # prints real data when it is available, then exits.
        deadline = time.time() + 5.0
        while session.poller.revision() == 0 and time.time() < deadline:
            time.sleep(0.05)
        snap = session.snapshot()
        code, label = result_for(snap)
        for line in render_block(session, DEPARTURES, "", 0, page_size=page_size)[:page_size + 3]:
            out(line)
        out(f"Result: {label}")
        out("Commands: 1 Departures  2 Arrivals  5 Alerts  6 Airlines  r Refresh  w Web  q Quit")
        return code

    page = DEPARTURES
    search = ""
    offset = 0
    out("HKG Flight Data — plain mode (enter a command or 'help')")
    try:
        while True:
            print_block(session, page, search, offset, out, page_size=page_size)
            try:
                raw = input_func("> ")
            except (EOFError, KeyboardInterrupt, StopIteration):
                out("")
                break
            if raw is None:
                out("")
                break
            raw = str(raw).strip()
            if raw == "":
                continue
            lower = raw.lower()

            if lower in ("q", "quit", "exit"):
                break
            if lower in ("1", "2", "5", "6"):
                page = {"1": DEPARTURES, "2": ARRIVALS, "5": ALERTS, "6": AIRLINES}[lower]
                search, offset = "", 0
                session.state.current = page
            elif lower in ("n", "next"):
                offset = clamp_offset(
                    offset + page_size, len(_rows(session, page, search)), page_size)
            elif lower in ("p", "prev", "previous"):
                offset = clamp_offset(
                    offset - page_size, len(_rows(session, page, search)), page_size)
            elif lower in ("r", "refresh"):
                session.request_refresh()
            elif lower in ("w", "web"):
                session.toggle_web()
            elif lower in ("help", "?"):
                for line in _help_lines():
                    out(line)
            elif raw.startswith("/"):
                search, offset = raw[1:].strip(), 0
            elif lower.startswith("detail"):
                part = raw[6:].strip() if lower.startswith("detail ") else ""
                try:
                    number = int(part)
                except (TypeError, ValueError):
                    number = 0
                _print_detail(session, page, search, offset, number, out, page_size)
            else:
                out("Unknown command (help for list)")
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
    """Print detail for 1-based row ``number`` relative to the page offset."""
    rows = _rows(session, page, search)
    start = clamp_offset(offset, len(rows), page_size)
    index = start + number - 1
    if number < 1 or index < 0 or index >= len(rows):
        shown = len(rows[start:start + page_size])
        out(f"No such row (this page shows rows {start + 1}-{start + max(0, shown)})")
        return
    if page in FLIGHT_PAGES:
        for label, value in detail_lines(rows[index]["record"]):
            out(f"{label}: {value}")
    elif page == ALERTS:
        alert = rows[index]["record"]
        out("{} {} {} | {}".format(
            alert.get("flight_number", "?"), alert.get("field", "?"),
            alert_change_text(alert), alert.get("status", "")))
    else:
        out("Detail is available for flight and alert pages")


def is_tty(stream=None):
    """Best-effort TTY detection for stdin (NO_COLOR-safe, no raw mode)."""
    stream = stream if stream is not None else sys.stdin
    return bool(getattr(stream, "isatty", lambda: False)())


def main_plain(session, page_size=DEFAULT_PAGE_SIZE):
    """Entry point used by the CLI selector."""
    return run_plain(session, page_size=page_size, tty=is_tty())
