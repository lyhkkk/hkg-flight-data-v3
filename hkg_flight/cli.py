"""
HKG Flight Data v3 - CLI.

Argument parsing, one-shot query commands, and the entry point that selects
between the Textual workbench and the plain fallback. Table output reuses the
terminal views, so the CLI and the workbench render rows the same way.
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from .cache import CacheSystem, DEFAULT_CACHE_DIR, DEFAULT_WEB_PORT
from .api import APIClient
from .alerts import AlertManager
from .utils import (
    today_str,
    normalize_flight_number,
    log,
    normalize_flights,
    sort_flights,
    terminal_width,
)
from .terminal import views
from .terminal.presenter import detail_lines, sort_alerts

DEFAULT_PAGE_SIZE = 10

_HKT = timezone(timedelta(hours=8))

# A stand is one of the HKIA prefixes followed by 1-3 digits. "G" is excluded
# so gate queries (G28) stay distinct, and the digit requirement keeps short
# flight numbers such as BA15 or SQ2 out of stand matching.
_STAND_RE = re.compile(r"[WNRSEDX]\d{1,3}")
_GATE_RE = re.compile(r"G\d+")
_AIRLINE_RE = re.compile(r"[A-Z]{2}")


# -- query ---------------------------------------------------------------

def _is_stand(term):
    return bool(_STAND_RE.fullmatch(term))


def _is_gate(term):
    return bool(_GATE_RE.fullmatch(term))


def _is_airline_code(term):
    return bool(_AIRLINE_RE.fullmatch(term))


def _search_dates(date_str, now=None):
    """Dates to search when the caller did not pin one (HKT-aware).

    22:00-01:59 spans midnight, so late-night and early-morning queries look at
    the neighbouring day as well; 02:00-21:59 searches today only. ``now`` is
    injectable so the rule can be tested without waiting for the clock.
    """
    if date_str:
        return [date_str]
    now = now or datetime.now(_HKT)
    today = now.date()
    if now.hour >= 22:
        return [today.isoformat(), (today + timedelta(days=1)).isoformat()]
    if now.hour < 2:
        return [(today - timedelta(days=1)).isoformat(), today.isoformat()]
    return [today.isoformat()]


def _matches(records, term, include_codeshare):
    """Match ``term`` against one dataset using the specialized search modes."""
    if _is_gate(term):
        gate = term[1:].upper()
        return [r for r in records if r.get("gate", "").upper() == gate]
    if _is_stand(term):
        return [r for r in records if r.get("stand", "").upper() == term]
    if _is_airline_code(term):
        hits = []
        for rec in records:
            if rec.get("airline_code", "").upper() == term:
                hits.append(rec)
            elif rec.get("flight_number", "").startswith(term):
                hits.append(rec)
            elif include_codeshare and any(
                    no.startswith(term)
                    for no in rec.get("all_flight_numbers", "").split("|") if no):
                hits.append(rec)
        return hits
    return _matches_flight_number(records, term, include_codeshare)


def _matches_flight_number(records, term, include_codeshare):
    return [
        r for r in records
        if term in r.get("flight_number", "")
        or (include_codeshare and term in r.get("all_flight_numbers", ""))
    ]


def search_flights(api, flight_number, date_str=None, include_codeshare=False):
    """Search flights by flight number, airline code, gate or stand.

    Stand/gate searches fall back to a flight-number match when they find
    nothing, so an input such as ``D7`` never silently hides a flight.
    """
    term = normalize_flight_number(flight_number)

    records = []
    for d in _search_dates(date_str):
        raw = api.fetch_flights(d)
        if raw is not None:
            records.extend(normalize_flights(raw))

    # De-duplicate by cache key, preserving first-seen order.
    unique, seen = [], set()
    for rec in records:
        key = rec.get("key", "")
        if key not in seen:
            seen.add(key)
            unique.append(rec)

    results = _matches(unique, term, include_codeshare)
    if not results and (_is_stand(term) or _is_gate(term)):
        results = _matches_flight_number(unique, term, include_codeshare)

    results.sort(key=lambda r: (r.get("date", ""), r.get("time", "")))
    return results


def flights_for_date(api, date_str, flight_type="all"):
    """Normalized + sorted records for one date, optionally one direction."""
    raw = api.fetch_flights(date_str)
    if raw is None:
        return []
    records = sort_flights(normalize_flights(raw))
    if flight_type in ("arrival", "departure"):
        records = [r for r in records if r.get("type") == flight_type]
    return records


def load_airlines(api):
    """Load airline metadata as a plain list."""
    return api.fetch_airlines()


# -- cache maintenance ---------------------------------------------------

def clear_cache(cache, date_str=None, confirm=False):
    """Delete cached flight/airline/alert files.

    Only files this project owns are ever removed, so a mistyped
    ``--cache-dir`` cannot take unrelated files with it.
    """
    cache_dir = cache.cache_dir

    if date_str:
        cache.clear_flights(date_str)
        print(f"Cleared cache for {date_str}")
        return

    if not confirm:
        if input(f"Delete ALL cache in {cache_dir}? (yes/no): ").lower() != "yes":
            print("Cancelled.")
            return

    removed = 0
    for filename in sorted(os.listdir(cache_dir)) if os.path.isdir(cache_dir) else []:
        owned = (filename.startswith("flights_") and filename.endswith(".json")) \
            or filename in ("airlines.json", "alerts.json")
        if not owned:
            continue
        try:
            os.remove(os.path.join(cache_dir, filename))
            removed += 1
        except OSError as exc:
            log(f"Failed to delete {filename}: {exc}")
    print(f"Cleared {removed} cache file(s) in {cache_dir}")


# -- rendering -----------------------------------------------------------

def print_flight_details(rec, index=None, width=None):
    """Print the labeled detail view for one flight."""
    width = width or terminal_width()
    header = f"--- Flight #{index} ---" if index is not None else "--- Flight Details ---"
    print("\n" + views.truncate(header, width))
    for label, value in detail_lines(rec):
        print(views.truncate(f"{label}: {value}", width))


def _spans_dates(records):
    """True when a result set covers more than one calendar day."""
    return len({r.get("date", "") for r in records}) > 1


def _print_flight_rows(records, width=None, spanning=None):
    """Rule, then the rows - one line each, or two when the terminal is narrow.

    Nothing printed here is ever wider than ``width``, so the shell cannot wrap
    a row in the middle of a value. A narrow terminal gets the same two-line
    compact row the workbench uses, which keeps every column readable instead of
    squeezing all six onto one line.

    When the set spans several days (``query`` looks at two dates across
    midnight) each day gets a dated divider, so the same scheduled time on
    consecutive days cannot read as a duplicated row.
    """
    width = width or terminal_width()
    if spanning is None:
        spanning = _spans_dates(records)
    compact = views.is_compact(width)
    if not compact:
        print(views.flight_header(width))
    print(views.rule(width))
    current = None
    for rec in records:
        if spanning and rec.get("date") != current:
            current = rec.get("date")
            print(views.date_separator(current, width))
        for line in views.flight_row(rec, width, compact=compact):
            print(line)


def _print_table(records, title, width=None):
    """One compact row per flight, using the shared row renderer."""
    if not records:
        print("No flights found.")
        return
    width = width or terminal_width()
    print("\n" + views.truncate(f"{title} — {len(records)} flight(s)", width) + "\n")
    _print_flight_rows(records, width)


def print_flight_table(records, title):
    """Print flights as a compact table (CLI list commands)."""
    _print_table(records, title)


# Footers and hints are written as a ladder: the longest form that fits the
# terminal wins, and a form that would wrap is never used.
#
# These strings are printed raw, but measured with ``views.text_width``, which
# strips rich markup - so a form written with bracket notation such as ``[n]``
# measures short and would be picked at a width where it does not actually fit.
# Keep the ladder free of anything that looks like a markup tag.
_PAGER_FORMS = (
    "Page {page}/{total} — Enter/N next, P prev, Q quit, or type a page number",
    "{page}/{total} — n next, p prev, q quit",
    "{page}/{total}  n/p/q",
)

_CODESHARE_FORMS = (
    "Tip: Use --codeshare to include codeshare flights",
    "--codeshare adds codeshares",
)


def _fits(forms, width, **fields):
    """The first form that fits ``width``; empty when none does."""
    for form in forms:
        text = form.format(**fields)
        if views.text_width(text) <= width:
            return text
    return ""


def pager_prompt(page, total_pages, width):
    """Pager footer for ``width``, or empty when even the shortest will not fit."""
    return _fits(_PAGER_FORMS, width, page=page, total=total_pages)


def paginate_records(records, title, page_size=DEFAULT_PAGE_SIZE,
                     input_func=input, width=None):
    """Display records in an interactive pager, ``page_size`` rows per page.

    Navigation: Enter/``n`` next, ``p`` previous, a number to jump, ``q`` quit.
    """
    total = len(records)
    if total == 0:
        print("No flights found.")
        return 0

    width = width or terminal_width()
    total_pages = (total + page_size - 1) // page_size
    spanning = _spans_dates(records)
    page = 1
    while True:
        start = (page - 1) * page_size
        end = min(start + page_size, total)
        print("\n" + views.truncate(
            f"{title} — {total} flight(s), showing {start + 1}-{end}", width) + "\n")
        _print_flight_rows(records[start:end], width, spanning=spanning)
        prompt = pager_prompt(page, total_pages, width)
        print(f"\n{prompt}" if prompt else "")

        try:
            choice = input_func("> ").strip().lower()
        except (EOFError, KeyboardInterrupt, StopIteration):
            print()
            break

        if choice in ("q", "quit", "exit"):
            break
        if choice in ("n", ""):
            page = min(page + 1, total_pages)
        elif choice in ("p", "prev", "previous"):
            page = max(page - 1, 1)
        elif choice.isdigit() and 1 <= int(choice) <= total_pages:
            page = int(choice)

    return page


# -- commands ------------------------------------------------------------

def cmd_query(args, api):
    width = terminal_width()
    results = search_flights(api, args.flight, args.date, include_codeshare=args.codeshare)
    title = f"Query '{args.flight.upper()}'"
    if args.date:
        title += f" on {args.date}"

    if not results:
        print(views.truncate(f"No flights found for '{args.flight}'", width))
    elif args.details:
        for i, rec in enumerate(results, 1):
            print_flight_details(rec, i, width)
    elif _is_airline_code(normalize_flight_number(args.flight)) or len(results) > DEFAULT_PAGE_SIZE:
        paginate_records(results, title, page_size=DEFAULT_PAGE_SIZE, width=width)
    else:
        _print_table(results, title, width)

    if not args.codeshare:
        tip = _fits(_CODESHARE_FORMS, width)
        if tip:
            print(f"\n{tip}")
    return 0


def cmd_departures(args, api):
    date_str = args.date or today_str()
    print_flight_table(flights_for_date(api, date_str, "departure"), f"Departures {date_str}")
    return 0


def cmd_arrivals(args, api):
    date_str = args.date or today_str()
    print_flight_table(flights_for_date(api, date_str, "arrival"), f"Arrivals {date_str}")
    return 0


def cmd_alerts(alert_manager, width=None):
    """Print gate/stand divergences, using the shared workbench renderer."""
    active = sort_alerts(alert_manager.get_active())
    if not active:
        print("No gate/stand changes.")
        return 0
    width = width or terminal_width()
    print("\n" + views.truncate(f"Gate/stand changes — {len(active)}", width) + "\n")
    print(views.alert_header(width))
    print(views.rule(width))
    for alert in active:
        print(views.alert_line(alert, width))
    return 0


def cmd_clear_cache(args, cache):
    clear_cache(cache, args.date, confirm=args.yes)
    return 0


def cmd_web(args, poller, api, alert_manager):
    """Start the web server in the foreground until Ctrl+C."""
    from .web import WebServer

    server = WebServer(poller, api, alert_manager, port=args.port)
    if not server.start():
        print(f"Could not start web server on port {args.port}")
        return 1

    print("✈ HKG Flight Data web server")
    print(f"  http://127.0.0.1:{args.port}")
    print("  Press Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server.stop()
    return 0


def _run_terminal_ui(cache, api, alert_manager, port, no_poll, ui="auto"):
    """Run the terminal workbench through one Session lifecycle.

    The session owns the poller, the web server and the airline loader; every
    exit path goes through ``finally`` so owned resources are always released.
    """
    import importlib.util

    from .terminal.session import Session

    ui = ui or "auto"
    textual_available = importlib.util.find_spec("textual") is not None
    interactive = sys.stdin.isatty() and sys.stdout.isatty()

    if ui == "textual" and not (textual_available and interactive):
        reason = "Textual is not installed" if not textual_available \
            else "not an interactive terminal"
        print(f"Error: --ui textual requires the enhanced UI, but {reason}.", file=sys.stderr)
        print("Install with: pip install 'hkg-flight-data[tui]'", file=sys.stderr)
        return 1

    if ui == "auto":
        if textual_available and interactive:
            backend = "textual"
        else:
            backend = "plain"
            if not textual_available:
                print("Textual not installed; using plain mode. "
                      "Install 'hkg-flight-data[tui]' for the full workbench.", file=sys.stderr)
            else:
                print("Not an interactive terminal; using plain mode.", file=sys.stderr)
    else:
        backend = ui

    session = Session(
        cache=cache, api=api, alert_manager=alert_manager,
        port=port, no_poll=no_poll,
    )
    try:
        session.start()
        if backend == "textual":
            from .terminal.textual_app import run_textual
            run_textual(session)
            return 0
        from .terminal.plain import run_plain
        return run_plain(session, tty=interactive)
    finally:
        session.close()


# -- entry point ---------------------------------------------------------

def create_parser():
    parser = argparse.ArgumentParser(
        prog="hkg_flight",
        description="HKG Flight Data v3 - flight information for Hong Kong International Airport",
        epilog="Example: python -m hkg_flight query CX759",
    )
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR,
                        help="Custom cache directory (default: ~/.hkg_flight_cache)")
    parser.add_argument("--force", action="store_true",
                        help="Bypass cached airline data for this run")

    sub = parser.add_subparsers(dest="command")

    q = sub.add_parser("query", help="Search for a flight by number")
    q.add_argument("flight", help="Flight number (CX759), airline code (CX), gate (G28) or stand (W63)")
    q.add_argument("date", nargs="?", default=None, help="Date YYYY-MM-DD (default: today, or the neighbouring day across midnight)")
    q.add_argument("--codeshare", action="store_true", help="Include codeshare flights")
    q.add_argument("--details", "-d", action="store_true", help="Show full flight details")

    d = sub.add_parser("departures", help="List departures")
    d.add_argument("date", nargs="?", default=None, help="Date YYYY-MM-DD (default: today)")

    a = sub.add_parser("arrivals", help="List arrivals")
    a.add_argument("date", nargs="?", default=None, help="Date YYYY-MM-DD (default: today)")

    sub.add_parser("alerts", help="Show gate/stand changes away from the original assignment")

    c = sub.add_parser("clear-cache", help="Clear cached data")
    c.add_argument("date", nargs="?", default=None, help="Specific date to clear (default: all)")
    c.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")

    w = sub.add_parser("web", help="Start web server")
    w.add_argument("--port", "-p", type=int, default=DEFAULT_WEB_PORT, help="Port (default: 8080)")

    t = sub.add_parser("tui", help="Start the terminal workbench")
    t.add_argument("--no-poll", action="store_true", help="Disable timed polling")
    t.add_argument("--port", "-p", type=int, default=DEFAULT_WEB_PORT, help="Port for the W key (default: 8080)")
    t.add_argument("--ui", choices=["auto", "textual", "plain"], default="auto",
                   help="Backend: auto (detect), textual (require enhanced UI), plain (stdlib fallback)")

    return parser


def main(argv=None):
    args = create_parser().parse_args(argv)

    cache = CacheSystem(cache_dir=args.cache_dir)
    api = APIClient(cache=cache)
    alert_manager = AlertManager(cache=cache)

    if args.force:
        api.bypass_cache = True
        print("Force mode: bypassing cached airline data for this run")

    if args.command == "query":
        return cmd_query(args, api)
    if args.command == "departures":
        return cmd_departures(args, api)
    if args.command == "arrivals":
        return cmd_arrivals(args, api)
    if args.command == "alerts":
        return cmd_alerts(alert_manager)
    if args.command == "clear-cache":
        return cmd_clear_cache(args, cache)
    if args.command == "web":
        from .poller import Poller
        poller = Poller(cache=cache, api=api, alert_manager=alert_manager)
        poller.start(blocking=True)
        return cmd_web(args, poller, api, alert_manager)
    if args.command == "tui":
        return _run_terminal_ui(cache, api, alert_manager,
                                port=args.port, no_poll=args.no_poll, ui=args.ui)
    return _run_terminal_ui(cache, api, alert_manager,
                            port=DEFAULT_WEB_PORT, no_poll=False, ui="auto")


if __name__ == "__main__":
    sys.exit(main())
