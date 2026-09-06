"""
HKG Flight Data v3 - CLI Module
Command-line interface and entry point.
"""

import argparse
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


def clear_cache(cache, date_str=None, confirm=False):
    """
    Clear cached data safely.
    
    Args:
        cache: CacheSystem instance
        date_str: Specific date to clear, or None to clear all
        confirm: If True, skip confirmation prompt
    """
    cache_dir = cache.cache_dir
    
    # Safety check: only delete if it's the expected cache directory
    basename = os.path.basename(os.path.abspath(cache_dir))
    if basename != ".hkg_flight_cache" and not basename.startswith("hkg_flight"):
        log("Refusing to delete non-cache directory: {}".format(cache_dir))
        print("Error: Refusing to delete non-cache directory: {}".format(cache_dir))
        return
    
    if date_str:
        cache.write_flights(date_str, None)
        print("Cleared cache for {}".format(date_str))
    else:
        # Confirm before deleting all cache
        if not confirm:
            response = input("Delete ALL cache in {}? (yes/no): ".format(cache_dir))
            if response.lower() != "yes":
                print("Cancelled.")
                return
        
        import shutil
        if os.path.exists(cache_dir):
            # Delete files individually instead of rmtree
            for filename in os.listdir(cache_dir):
                filepath = os.path.join(cache_dir, filename)
                try:
                    if os.path.isfile(filepath):
                        os.remove(filepath)
                except Exception as exc:
                    log("Failed to delete {}: {}".format(filepath, exc))
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


def cmd_query(args, api):
    """Handle 'query' command."""
    results = search_flights(api, args.flight, args.date, include_codeshare=args.codeshare)

    if results:
        for i, rec in enumerate(results, 1):
            print_flight_details(rec, i)
    else:
        print("No flights found for '{}'".format(args.flight))
    
    if not args.codeshare:
        print("\nTip: Use --codeshare to include codeshare flights")

    return 0


def cmd_departures(args, api):
    """Handle 'departures' command."""
    date_str = args.date or today_str()
    records = flights_for_date(api, date_str, "departure")
    print_flight_table(records, "Departures {}".format(date_str))
    return 0


def cmd_arrivals(args, api):
    """Handle 'arrivals' command."""
    date_str = args.date or today_str()
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


def cmd_clear_cache(args, cache):
    """Handle 'clear-cache' command."""
    clear_cache(cache, args.date, confirm=args.yes)
    return 0


def cmd_web(args, poller, api, alert_manager):
    """Handle 'web' command - start web server."""
    try:
        from .web import WebServer
    except ImportError:
        print("Web server module not available.")
        return 1

    web_server = WebServer(poller, api, alert_manager, port=args.port)
    if not web_server.start():
        print("Could not start web server on port {}".format(args.port))
        return 1

    print("✈ HKG Flight Data web server")
    print("  http://127.0.0.1:{}".format(args.port))
    print("  Press Ctrl+C to stop")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        web_server.stop()

    return 0


def cmd_tui(args, poller, api, alert_manager, web_server):
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


def create_parser():
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="hkg_flight",
        description="HKG Flight Data v3 - Flight information system for Hong Kong International Airport",
        epilog="Example: python -m hkg_flight query CX759"
    )
    
    # Global options
    parser.add_argument(
        "--cache-dir", 
        default=DEFAULT_CACHE_DIR,
        help="Custom cache directory (default: ~/.hkg_flight_cache)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force refresh (clear cache before fetching)"
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # query command
    query_parser = subparsers.add_parser("query", help="Search for a flight by number")
    query_parser.add_argument("flight", help="Flight number to search for")
    query_parser.add_argument("date", nargs="?", default=None, help="Date in YYYY-MM-DD format (default: D-1, D, D+1)")
    query_parser.add_argument("--codeshare", action="store_true", help="Include codeshare flights")
    
    # departures command
    departures_parser = subparsers.add_parser("departures", help="List departures")
    departures_parser.add_argument("date", nargs="?", default=None, help="Date in YYYY-MM-DD format (default: today)")
    
    # arrivals command
    arrivals_parser = subparsers.add_parser("arrivals", help="List arrivals")
    arrivals_parser.add_argument("date", nargs="?", default=None, help="Date in YYYY-MM-DD format (default: today)")
    
    # alerts command
    subparsers.add_parser("alerts", help="Show active alerts")
    
    # clear-cache command
    clear_parser = subparsers.add_parser("clear-cache", help="Clear cached data")
    clear_parser.add_argument("date", nargs="?", default=None, help="Specific date to clear (default: all)")
    clear_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    
    # web command
    web_parser = subparsers.add_parser("web", help="Start web server")
    web_parser.add_argument("--port", "-p", type=int, default=DEFAULT_WEB_PORT, help="Web server port (default: 8080)")
    
    # tui command (default when no subcommand)
    tui_parser = subparsers.add_parser("tui", help="Start TUI interface")
    tui_parser.add_argument("--no-poll", action="store_true", help="Disable live polling")
    tui_parser.add_argument("--port", "-p", type=int, default=DEFAULT_WEB_PORT, help="Web server port for W key (default: 8080)")
    
    return parser


def main(argv=None):
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)
    
    # Initialize components
    cache = CacheSystem(cache_dir=args.cache_dir)
    api = APIClient(cache=cache)
    alert_manager = AlertManager(cache=cache)
    
    # Force refresh: clear cache first
    if args.force:
        print("Force refresh: clearing cache...")
        clear_cache(cache, confirm=True)
    
    # Handle commands
    if args.command == "query":
        return cmd_query(args, api)
    elif args.command == "departures":
        return cmd_departures(args, api)
    elif args.command == "arrivals":
        return cmd_arrivals(args, api)
    elif args.command == "alerts":
        return cmd_alerts(alert_manager)
    elif args.command == "clear-cache":
        return cmd_clear_cache(args, cache)
    elif args.command == "web":
        # Import poller for web mode
        try:
            from .poller import Poller
            poller = Poller(cache=cache, api=api, alert_manager=alert_manager)
            poller.start()
        except ImportError:
            poller = None
        return cmd_web(args, poller, api, alert_manager)
    elif args.command == "tui":
        # Import poller for TUI mode
        try:
            from .poller import Poller
            poller = Poller(cache=cache, api=api, alert_manager=alert_manager)
            poller.enabled = not args.no_poll
            poller.start()
            # Wait a moment for data to load
            time.sleep(0.5)
        except ImportError:
            poller = None
        
        web_server = None
        try:
            from .web import WebServer
            web_server = WebServer(poller, api, alert_manager, port=args.port)
        except ImportError:
            pass
        
        return cmd_tui(args, poller, api, alert_manager, web_server)
    else:
        # Default: start TUI
        try:
            from .poller import Poller
            poller = Poller(cache=cache, api=api, alert_manager=alert_manager)
            poller.start()
            time.sleep(0.5)
        except ImportError:
            poller = None
        
        web_server = None
        try:
            from .web import WebServer
            web_server = WebServer(poller, api, alert_manager, port=DEFAULT_WEB_PORT)
        except ImportError:
            pass
        
        return cmd_tui(args, poller, api, alert_manager, web_server)


if __name__ == "__main__":
    sys.exit(main())
