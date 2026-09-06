"""
HKG Flight Data v3 - CLI Module
Command-line interface and entry point.
"""

import sys
import os
import time
import threading
from datetime import date, datetime, timedelta

from .cache import CacheSystem, DEFAULT_CACHE_DIR, DEFAULT_MIN_API_INTERVAL, DEFAULT_WEB_PORT
from .api import APIClient, API_BASE
from .alerts import AlertManager
from .utils import (
    today_str,
    normalize_flight_number,
    make_flight_key,
    route_text,
    gate_stand_text,
    format_time,
    log,
    get_status_info,
    status_pair,
    normalize_flights,
    sort_flights,
    filter_records,
)


def search_flights(api, flight_number, date_str=None, include_codeshare=False):
    """
    Search for flights by flight number.
    
    Searches for flights where the primary flight number contains the search term.
    By default, excludes codeshare flights unless include_codeshare is True.
    If no date specified, searches D-1, D, D+1 (3 days).

    Args:
        api: APIClient instance
        flight_number: Flight number to search for
        date_str: Optional date in YYYY-MM-DD format
        include_codeshare: If True, also search codeshare flight numbers

    Returns:
        list: Matching flight records
    """
    search_no = normalize_flight_number(flight_number)
    
    # If date specified, search only that day
    if date_str:
        dates_to_search = [date_str]
    else:
        # Search D-1, D, D+1
        today = date.today()
        dates_to_search = [
            (today - timedelta(days=1)).isoformat(),  # D-1
            today.isoformat(),                         # D
            (today + timedelta(days=1)).isoformat(),  # D+1
        ]
    
    all_results = []
    seen_keys = set()
    
    for d in dates_to_search:
        raw_data = api.fetch_flights(d)
        if raw_data is None:
            continue
        
        records = normalize_flights(raw_data)
        
        for rec in records:
            key = rec.get("key", "")
            if key in seen_keys:
                continue
            
            # Search primary flight number (contains match)
            if search_no in rec.get("flight_number", ""):
                all_results.append(rec)
                seen_keys.add(key)
            # Optionally search codeshare flight numbers
            elif include_codeshare and search_no in rec.get("all_flight_numbers", ""):
                all_results.append(rec)
                seen_keys.add(key)
    
    # Sort by date and time
    all_results.sort(key=lambda r: (r.get("date", ""), r.get("time", "")))
    
    return all_results


def flights_for_date(api, date_str, flight_type="all"):
    """
    Get flights for a specific date.

    Args:
        api: APIClient instance
        date_str: Date in YYYY-MM-DD format
        flight_type: 'arrival', 'departure', or 'all'

    Returns:
        list: Flight records
    """
    raw_data = api.fetch_flights(date_str)
    if raw_data is None:
        return []

    records = normalize_flights(raw_data)
    records = sort_flights(records)

    if flight_type == "arrival":
        records = [r for r in records if r.get("type") == "arrival"]
    elif flight_type == "departure":
        records = [r for r in records if r.get("type") == "departure"]

    return records


def _merge_fvm_data(api, records):
    """Merge FVM registration data into flight records."""
    fvm_data = api.fetch_fvm_registrations()
    if not fvm_data:
        return records

    fvm_lookup = {}
    for item in fvm_data:
        key = normalize_flight_number(item.get("flight_id", ""))
        if key:
            fvm_lookup[key] = item

    for rec in records:
        flight_no = rec.get("flight_number", "")
        if flight_no in fvm_lookup:
            fvm = fvm_lookup[flight_no]
            rec["registration"] = fvm.get("REG", "")
            rec["aircraft_type"] = fvm.get("SUBTYPE", "")

    return records


def load_airlines(api):
    """Load airline metadata."""
    return api.fetch_airlines()


def clear_cache(cache, date_str=None):
    """
    Clear cached data.
    
    Args:
        cache: CacheSystem instance
        date_str: Specific date to clear, or None to clear all
    """
    if date_str:
        cache.write_flights(date_str, None)
        print("Cleared cache for {}".format(date_str))
    else:
        import shutil
        cache_dir = cache.cache_dir
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
            os.makedirs(cache_dir)
            print("Cleared all cache in {}".format(cache_dir))


def print_flight_details(rec, index=None):
    """Print detailed flight information."""
    if index is not None:
        print("\n--- Flight #{} ---".format(index))
    else:
        print("\n--- Flight Details ---")

    print("Flight: {}".format(rec.get("flight_number", "N/A")))
    print("Date: {}".format(rec.get("date", "N/A")))
    print("Time: {}".format(rec.get("time", "N/A")))
    print("Type: {}".format(rec.get("type", "N/A")))
    print("Status: {}".format(rec.get("status", "N/A")))
    print("Route: {}".format(route_text(rec)))
    print("Gate/Stand: {}".format(gate_stand_text(rec)))
    print("Terminal: {}".format(rec.get("terminal", "N/A")))
    if rec.get("registration"):
        print("Registration: {}".format(rec.get("registration")))
    if rec.get("aircraft_type"):
        print("Aircraft: {}".format(rec.get("aircraft_type")))


def print_flight_table(records, title):
    """Print a table of flights."""
    if not records:
        print("No flights found.")
        return

    print("\n{} — {} flight(s)".format(title, len(records)))
    print()
    print("{:<6} {:<10} {:<6} {:<20} {:<18} {:<12} {:<5}".format(
        "TIME", "FLIGHT", "REG", "ROUTE", "STATUS", "GATE/STAND", "TERM"
    ))
    print("-" * 80)

    for rec in records[:50]:  # Limit to 50 rows
        time_str = rec.get("time", "--:--")
        flight = rec.get("flight_number", "N/A")
        reg = rec.get("registration", "-")
        route = route_text(rec)
        status = rec.get("status", "N/A")
        gs = gate_stand_text(rec)
        term = rec.get("terminal", "-")

        print("{:<6} {:<10} {:<6} {:<20} {:<18} {:<12} {:<5}".format(
            time_str, flight, reg, route, status, gs, term
        ))

    if len(records) > 50:
        print("\n... and {} more flights".format(len(records) - 50))


def cmd_query(api, args):
    """Handle 'query' command."""
    # Parse arguments for --codeshare flag
    include_codeshare = "--codeshare" in args
    args = [a for a in args if a != "--codeshare"]
    
    if not args:
        print("Usage: python -m hkg_flight query <flight_number> [date] [--codeshare]")
        return 1

    flight_number = args[0]
    date_str = args[1] if len(args) > 1 else None

    results = search_flights(api, flight_number, date_str, include_codeshare=include_codeshare)

    if results:
        for i, rec in enumerate(results, 1):
            print_flight_details(rec, i)
    else:
        print("No flights found for '{}'".format(flight_number))
    
    if not include_codeshare:
        print("\nTip: Use --codeshare to include codeshare flights")

    return 0


def cmd_departures(api, args):
    """Handle 'departures' command."""
    date_str = args[0] if args else today_str()
    records = flights_for_date(api, date_str, "departure")
    print_flight_table(records, "Departures {}".format(date_str))
    return 0


def cmd_arrivals(api, args):
    """Handle 'arrivals' command."""
    date_str = args[0] if args else today_str()
    records = flights_for_date(api, date_str, "arrival")
    print_flight_table(records, "Arrivals {}".format(date_str))
    return 0


def cmd_alerts(alert_manager):
    """Handle 'alerts' command."""
    active = alert_manager.get_active()

    if not active:
        print("No active alerts.")
        return 0

    print("Active alerts: {}".format(len(active)))
    for alert in active:
        field = alert.get("field", "UNKNOWN")
        old_val = alert.get("old_value", "")
        new_val = alert.get("new_value", "")
        flight = alert.get("flight_number", "N/A")
        status = alert.get("status", "")
        raised = alert.get("raised_at", "")

        print("⚠ {} {} change: {} → {} | status: {} | raised: {}".format(
            flight, field, old_val, new_val, status, raised
        ))

    return 0


def cmd_clear_cache(cache, args):
    """Handle 'clear-cache' command."""
    date_str = args[0] if args else None
    clear_cache(cache, date_str)
    return 0


def cmd_web(poller, api, alert_manager, port):
    """Handle 'web' command - start web server."""
    try:
        from .web import WebServer
    except ImportError:
        print("Web server module not available. Install with: pip install hkg-flight-data[web]")
        return 1

    web_server = WebServer(poller, api, alert_manager, port=port)
    if not web_server.start():
        print("Could not start web server on port {}".format(port))
        return 1

    print("✈ HKG Flight Data web server")
    print("  http://localhost:{}".format(port))
    print("  Press Ctrl+C to stop")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        web_server.stop()

    return 0


def cmd_tui(poller, api, alert_manager, web_server):
    """Handle 'tui' command - start TUI interface."""
    try:
        from .tui import start_tui, run_simple_tui
    except ImportError:
        print("TUI module not available.")
        return 1

    # Try curses TUI first, fall back to simple TUI
    try:
        import curses
        start_tui(poller, api, alert_manager, web_server)
    except ImportError:
        print("curses not available, using simple TUI")
        run_simple_tui(poller, api, alert_manager, web_server)

    return 0


def print_usage():
    """Print usage information."""
    print("HKG Flight Data v3")
    print()
    print("Usage:")
    print("  python -m hkg_flight                     # Start TUI (default)")
    print("  python -m hkg_flight --web [--port N]    # Start web server")
    print("  python -m hkg_flight --no-poll           # TUI without live polling")
    print("  python -m hkg_flight --force             # Force refresh (ignore cache)")
    print()
    print("Commands:")
    print("  python -m hkg_flight query <flight> [date] [--codeshare]")
    print("  python -m hkg_flight departures [date]")
    print("  python -m hkg_flight arrivals [date]")
    print("  python -m hkg_flight alerts")
    print("  python -m hkg_flight clear-cache [date]")
    print()
    print("Options:")
    print("  --web           Start web server mode")
    print("  --port N        Web server port (default: 8080)")
    print("  --no-poll       Disable live polling")
    print("  --force         Force refresh (clear cache before fetching)")
    print("  --codeshare     Include codeshare flights in search results")
    print("  --cache-dir DIR Custom cache directory")


def main(argv=None):
    """Main entry point."""
    if argv is None:
        argv = sys.argv[1:]

    # Parse arguments
    web_only = "--web" in argv
    no_poll = "--no-poll" in argv
    force_refresh = "--force" in argv
    port = DEFAULT_WEB_PORT
    cache_dir = DEFAULT_CACHE_DIR

    # Extract port if specified
    if "--port" in argv:
        try:
            port_idx = argv.index("--port")
            port = int(argv[port_idx + 1])
        except (IndexError, ValueError):
            print("Invalid port number")
            return 1

    # Extract cache dir if specified
    if "--cache-dir" in argv:
        try:
            cache_idx = argv.index("--cache-dir")
            cache_dir = argv[cache_idx + 1]
        except (IndexError, ValueError):
            print("Invalid cache directory")
            return 1

    # Remove processed args
    args = [a for a in argv if a not in ("--web", "--no-poll", "--force", "--port", "--cache-dir")]

    # Initialize components
    cache = CacheSystem(cache_dir=cache_dir)
    api = APIClient(cache=cache)
    alert_manager = AlertManager(cache=cache)

    # Force refresh: clear cache first
    if force_refresh:
        print("Force refresh: clearing cache...")
        clear_cache(cache)

    # Handle CLI commands
    if args:
        cmd = args[0]
        if cmd == "query":
            return cmd_query(api, args[1:])
        elif cmd == "departures":
            return cmd_departures(api, args[1:])
        elif cmd == "arrivals":
            return cmd_arrivals(api, args[1:])
        elif cmd == "alerts":
            return cmd_alerts(alert_manager)
        elif cmd == "clear-cache":
            return cmd_clear_cache(cache, args[1:])
        else:
            print_usage()
            return 1

    # Try to import poller for TUI/Web modes
    try:
        from .poller import Poller
        poller = Poller(cache=cache, api=api, alert_manager=alert_manager)
        poller.enabled = not no_poll
    except ImportError:
        poller = None

    # Web server mode
    if web_only:
        if poller:
            poller.start()
        return cmd_web(poller, api, alert_manager, port)

    # TUI mode (default)
    print("Starting TUI mode...")
    print("Use --web for web server, or query/departures/arrivals/alerts for CLI commands")
    print()
    
    # Start poller if available - this will do an initial data fetch
    if poller:
        poller.start()
        # Wait a moment for data to load
        time.sleep(0.5)
    
    # Try to start TUI
    try:
        from .tui import start_tui, run_simple_tui
        web_server = None
        try:
            from .web import WebServer
            web_server = WebServer(poller, api, alert_manager, port=DEFAULT_WEB_PORT)
        except ImportError:
            pass
        
        # Try curses TUI first, fall back to simple TUI
        try:
            import curses
            start_tui(poller, api, alert_manager, web_server)
        except Exception as e:
            print("curses TUI error: {}".format(e))
            print("Falling back to simple TUI...")
            run_simple_tui(poller, api, alert_manager, web_server)
    except ImportError as e:
        print("TUI not available: {}".format(e))
        print("Use --web for web server or CLI commands.")
        print()
        print("Example commands:")
        print("  python -m hkg_flight query CX759")
        print("  python -m hkg_flight departures")
        print("  python -m hkg_flight --web")

    return 0


if __name__ == "__main__":
    sys.exit(main())
