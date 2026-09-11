"""HKG Flight Data v3 - Alert maintenance utility.

Inspect or clear the alert cache. Alerts now prune themselves: the manager caps
the list at 500, drops anything from another date on every refresh, and removes
an alert as soon as its flight departs or returns to its original assignment.
This script is therefore only useful for looking at the file or wiping it by
hand; ``--days`` filters by the alert's flight date for that purpose.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hkg_flight import CacheSystem, DEFAULT_CACHE_DIR


def _select(alerts, cutoff):
    """Split alerts into ``(keep, drop)`` by flight date against ``cutoff``."""
    keep = [a for a in alerts if str(a.get("date", "")) >= cutoff]
    return keep, [a for a in alerts if str(a.get("date", "")) < cutoff]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect or clear the alert cache")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help="Cache directory path")
    parser.add_argument("--days", type=int, default=7,
                        help="Treat alerts older than N days as removable")
    parser.add_argument("--clear-all", action="store_true", help="Remove every alert")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry run)")
    args = parser.parse_args(argv)

    cache = CacheSystem(cache_dir=args.cache_dir)
    alerts = cache.read_alerts()

    if args.clear_all:
        keep, drop = [], alerts
    else:
        cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
        keep, drop = _select(alerts, cutoff)

    print(f"Alerts: {len(alerts)}   keep: {len(keep)}   remove: {len(drop)}")
    for alert in drop[:10]:
        print("  - {} {} {}".format(
            alert.get("flight_number", "?"), alert.get("field", "?"),
            alert.get("date", "")))
    if len(drop) > 10:
        print(f"  ... and {len(drop) - 10} more")

    if not args.apply:
        print("Dry run - pass --apply to write the change.")
        return 0
    if drop:
        cache.write_alerts(keep)
        print(f"Wrote {len(keep)} alert(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
