# HKG Flight Data v3 - Alert Cleanup Script
# Removes old and invalid alerts from the cache

import os
import sys
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hkg_flight import CacheSystem, DEFAULT_CACHE_DIR


def cleanup_alerts(cache_dir=DEFAULT_CACHE_DIR, days_old=7, dry_run=True):
    """
    Clean up old alerts from the cache.
    
    Args:
        cache_dir: Path to cache directory
        days_old: Remove alerts older than this many days
        dry_run: If True, only show what would be removed
    """
    cache = CacheSystem(cache_dir=cache_dir)
    alerts_data = cache.read_alerts()

    if not alerts_data.get("active") and not alerts_data.get("history"):
        print("No alerts data found.")
        return

    active = alerts_data.get("active", [])
    history = alerts_data.get("history", [])

    # Calculate cutoff date
    cutoff_date = datetime.now() - timedelta(days=days_old)
    cutoff_str = cutoff_date.strftime("%Y-%m-%d")
    
    print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Cutoff date: {cutoff_str} (alerts older than {days_old} days)")
    print(f"Dry run: {dry_run}")
    print()
    
    # Find alerts to remove
    active_to_keep = []
    active_to_remove = []
    
    for alert in active:
        alert_date = alert.get("date", "")
        
        # Remove if:
        # 1. Alert date is older than cutoff
        # 2. Alert has same old/new value (no actual change)
        # 3. Alert has invalid date format
        
        should_remove = False
        reason = ""
        
        # Check date
        if alert_date < cutoff_str:
            should_remove = True
            reason = f"Old date: {alert_date}"
        
        # Check for no actual change
        if alert.get("old_value") == alert.get("new_value"):
            should_remove = True
            reason = f"No change: {alert.get('old_value')} -> {alert.get('new_value')}"
        
        # Check for empty values
        if not alert.get("old_value") and not alert.get("new_value"):
            should_remove = True
            reason = "Empty values"
        
        if should_remove:
            active_to_remove.append((alert, reason))
        else:
            active_to_keep.append(alert)
    
    # Find history to remove
    history_to_keep = []
    history_to_remove = []
    
    for alert in history:
        alert_date = alert.get("date", "")
        if alert_date < cutoff_str:
            history_to_remove.append(alert)
        else:
            history_to_keep.append(alert)
    
    # Print summary
    print(f"Active alerts: {len(active)}")
    print(f"  - Keep: {len(active_to_keep)}")
    print(f"  - Remove: {len(active_to_remove)}")
    print()
    print(f"History alerts: {len(history)}")
    print(f"  - Keep: {len(history_to_keep)}")
    print(f"  - Remove: {len(history_to_remove)}")
    print()
    
    if active_to_remove:
        print("Active alerts to remove:")
        for alert, reason in active_to_remove[:10]:  # Show first 10
            print(f"  - {alert.get('flight_number')} ({alert.get('date')}): {reason}")
        if len(active_to_remove) > 10:
            print(f"  ... and {len(active_to_remove) - 10} more")
        print()
    
    if not dry_run:
        # Update alerts data
        alerts_data["active"] = active_to_keep
        alerts_data["history"] = history_to_keep
        alerts_data["new_flag"] = False
        
        cache.write_alerts(alerts_data)
        print("Alerts cleaned successfully!")
        print(f"Remaining active alerts: {len(active_to_keep)}")
        print(f"Remaining history alerts: {len(history_to_keep)}")
    else:
        print("Dry run - no changes made.")
        print("Run with dry_run=False to apply changes.")


def clear_all_alerts(cache_dir=DEFAULT_CACHE_DIR, dry_run=True):
    """
    Clear all alerts from the cache.
    
    Args:
        cache_dir: Path to cache directory
        dry_run: If True, only show what would be removed
    """
    cache = CacheSystem(cache_dir=cache_dir)
    alerts_data = cache.read_alerts()

    if not alerts_data.get("active") and not alerts_data.get("history"):
        print("No alerts data found.")
        return

    active = alerts_data.get("active", [])
    history = alerts_data.get("history", [])

    print(f"Active alerts: {len(active)}")
    print(f"History alerts: {len(history)}")
    print(f"Dry run: {dry_run}")
    print()

    if not dry_run:
        alerts_data["active"] = []
        alerts_data["history"] = []

        cache.write_alerts(alerts_data)
        print("All alerts cleared!")
    else:
        print("Dry run - no changes made.")
        print("Run with dry_run=False to apply changes.")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Clean up flight alerts cache")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help="Cache directory path")
    parser.add_argument("--days", type=int, default=7, help="Remove alerts older than N days")
    parser.add_argument("--clear-all", action="store_true", help="Clear all alerts")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry run)")
    
    args = parser.parse_args()
    
    dry_run = not args.apply
    
    if args.clear_all:
        clear_all_alerts(cache_dir=args.cache_dir, dry_run=dry_run)
    else:
        cleanup_alerts(cache_dir=args.cache_dir, days_old=args.days, dry_run=dry_run)
