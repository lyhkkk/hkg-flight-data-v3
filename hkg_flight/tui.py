"""
HKG Flight Data v3 - TUI Module
Terminal User Interface using curses.
"""

import sys
import os

from .utils import gate_stand_text, route_text, status_pair, today_str


def _enable_ansi_windows():
    """Enable ANSI escape codes on Windows."""
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


def _colors_enabled(stream=None):
    """Return whether ANSI color output is appropriate for the stream."""
    if "NO_COLOR" in os.environ:
        return False
    stream = stream or sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)())


def _colored(text, ansi_code, enabled=None):
    """Add ANSI color codes when output is an interactive terminal."""
    if enabled is None:
        enabled = _colors_enabled()
    if not enabled:
        return str(text)
    return "\033[{}m{}\033[0m".format(ansi_code, text)


def _getch():
    """Cross-platform getch."""
    try:
        import msvcrt
        return msvcrt.getch().decode("utf-8", errors="ignore")
    except ImportError:
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return ch


def run_simple_tui(poller, api, alert_manager, web_server):
    """
    Simple TUI that works without curses.
    """
    _enable_ansi_windows()
    colors_enabled = _colors_enabled()

    mode = "departures"
    page = 0
    filter_text = ""

    def clear():
        """Clear screen."""
        os.system("cls" if os.name == "nt" else "clear")

    def get_flights():
        """Get flights based on current mode."""
        if poller and poller.today_records:
            records = poller.today_records
        else:
            raw_data = api.fetch_flights(today_str())
            from .utils import normalize_flights, sort_flights
            records = normalize_flights(raw_data) if raw_data else []
            records = sort_flights(records)

        if mode == "departures":
            records = [r for r in records if r.get("type") == "departure"]
        elif mode == "arrivals":
            records = [r for r in records if r.get("type") == "arrival"]

        if filter_text:
            records = [r for r in records if filter_text.lower() in str(r).lower()]

        return records

    def render():
        """Render the TUI."""
        nonlocal page
        clear()

        # Header
        print(_colored("=" * 80, "1;33", colors_enabled))
        print(_colored("  HKG Flight Data - {}".format(today_str()), "1;33", colors_enabled))
        print(_colored("=" * 80, "1;33", colors_enabled))
        print()

        if mode == "alerts":
            # Show alerts
            active = alert_manager.get_active() if alert_manager else []
            print(_colored("  Active Alerts: {}".format(len(active)), "1;31", colors_enabled))
            print()
            for alert in active[:20]:
                field = alert.get("field", "?")
                old_v = alert.get("old_value", "")
                new_v = alert.get("new_value", "")
                flight = alert.get("flight_number", "?")
                status = alert.get("status", "")
                print("  ⚠ {} {}: {} → {} | {}".format(flight, field, old_v, new_v, status))
            print()
            print("  Press any key to return...")
            return  # Exit after rendering alerts

        elif mode == "airlines":
            # Show airlines
            airlines = api.fetch_airlines()
            print(_colored("  Airlines: {}".format(len(airlines)), "1;36", colors_enabled))
            print()
            for airline in airlines[:20]:
                code = airline.get("code", "?")
                name = airline.get("name", "?")
                print("  {} - {}".format(code, name))
            if len(airlines) > 20:
                print("  ... and {} more".format(len(airlines) - 20))
            print()
            print("  Press any key to return...")
            return  # Exit after rendering airlines

        else:
            # Show flights - ensure data is loaded
            flights = get_flights()
            if not flights:
                # Try to load data
                if poller:
                    poller.refresh_today()
                    flights = poller.today_records
            pages = max(1, (len(flights) + 19) // 20)
            page = max(0, min(page, pages - 1))

            start_idx = page * 20
            end_idx = min(start_idx + 20, len(flights))
            page_flights = flights[start_idx:end_idx]

            mode_title = "Departures" if mode == "departures" else "Arrivals"
            print("  {} — {} flights | Page {}/{}".format(mode_title, len(flights), page + 1, pages))
            if filter_text:
                print("  Filter: '{}'".format(filter_text))
            print()
            print("  {:<6} {:<10} {:<20} {:<20} {:<12} {:<5}".format(
                "TIME", "FLIGHT", "ROUTE", "STATUS", "GATE/STAND", "TERM"
            ))
            print("  " + "-" * 75)

            for rec in page_flights[:20]:  # Limit to 20 rows
                time_str = rec.get("time", "--:--")
                flight = rec.get("flight_number", "N/A")
                route = route_text(rec)
                status = rec.get("status", "N/A")
                gs = gate_stand_text(rec)
                term = rec.get("terminal", "-")

                # Color by status
                status_cat = rec.get("status_category", "scheduled")
                if status_cat == "boarding":
                    status_str = _colored(status, "32", colors_enabled)  # Green
                elif status_cat == "departed":
                    status_str = _colored(status, "32;2", colors_enabled)  # Dim green
                elif status_cat == "cancelled":
                    status_str = _colored(status, "31", colors_enabled)  # Red
                elif status_cat == "delayed":
                    status_str = _colored(status, "33", colors_enabled)  # Yellow
                else:
                    status_str = status

                print("  {:<6} {:<10} {:<20} {:<20} {:<12} {:<5}".format(
                    time_str, flight, route, status_str, gs, term
                ))

            print()
            print("  [N]ext [P]revious [1]Departures [2]Arrivals [5]Alerts [6]Airlines [Q]uit")

    while True:
        render()
        key = _getch()

        if key.upper() == "Q":
            break
        elif key == "1":
            mode = "departures"
            page = 0
        elif key == "2":
            mode = "arrivals"
            page = 0
        elif key == "5":
            mode = "alerts"
            render()
            _getch()
            mode = "departures"
        elif key == "6":
            mode = "airlines"
            render()
            _getch()
            mode = "departures"
        elif key.upper() == "N" and mode in ("departures", "arrivals"):
            # Recalculate pages for current mode
            flights = get_flights()
            pages = max(1, (len(flights) + 19) // 20)
            if page < pages - 1:
                page += 1
        elif key.upper() == "P" and mode in ("departures", "arrivals"):
            if page > 0:
                page -= 1
        elif key == "\x08" or key == "\x7f":  # Backspace
            filter_text = filter_text[:-1]
        elif len(key) == 1 and key.isprintable():
            filter_text += key


def _setup_curses_colors(stdscr):
    """Setup curses color pairs."""
    try:
        import curses
        curses.start_color()
        curses.use_default_colors()

        # Define color pairs
        curses.init_pair(1, curses.COLOR_YELLOW, -1)   # Header
        curses.init_pair(2, curses.COLOR_GREEN, -1)    # Boarding/Departed
        curses.init_pair(3, curses.COLOR_RED, -1)      # Cancelled/Delayed
        curses.init_pair(4, curses.COLOR_CYAN, -1)     # Info
        curses.init_pair(5, curses.COLOR_WHITE, -1)    # Normal
    except Exception:
        pass


class CursesTUI(object):
    """Full curses-based TUI."""

    def __init__(self, stdscr, poller, api, alert_manager, web_server):
        self.stdscr = stdscr
        self.poller = poller
        self.api = api
        self.alert_manager = alert_manager
        self.web_server = web_server
        self.mode = "departures"
        self.page = 0
        self.filter_text = ""
        self.today_records = []

        _setup_curses_colors(stdscr)
        stdscr.timeout(1000)  # 1 second timeout for polling

    def start(self):
        """Initialize view."""
        self.load_view()

    def load_view(self):
        """Load current view data."""
        if self.poller and self.poller.today_records:
            # Use poller data if available
            self.today_records = self.poller.today_records
        else:
            # Fetch directly from API
            raw_data = self.api.fetch_flights(today_str())
            from .utils import normalize_flights, sort_flights
            self.today_records = normalize_flights(raw_data) if raw_data else []
            self.today_records = sort_flights(self.today_records)
            # Also update poller if available
            if self.poller:
                self.poller.today_records = self.today_records

    def visible_flights(self):
        """Get flights for current view."""
        # Ensure data is loaded
        if not self.today_records:
            self.load_view()
        
        if self.mode == "departures":
            records = [r for r in self.today_records if r.get("type") == "departure"]
        elif self.mode == "arrivals":
            records = [r for r in self.today_records if r.get("type") == "arrival"]
        else:
            records = []

        if self.filter_text:
            records = [r for r in records if self.filter_text.lower() in str(r).lower()]

        return records

    def page_count(self):
        """Get total pages."""
        flights = self.visible_flights()
        return max(1, (len(flights) + 19) // 20)

    def clamp_page(self):
        """Ensure page is within bounds."""
        self.page = max(0, min(self.page, self.page_count() - 1))

    def render(self):
        """Render the TUI."""
        import curses

        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()

        # Check minimum terminal size
        if h < 10 or w < 40:
            try:
                self.stdscr.addstr(0, 0, "Terminal too small!", curses.color_pair(3))
                self.stdscr.refresh()
            except Exception:
                pass
            return

        # Header
        header = " HKG Flight Data — {} ".format(today_str())
        try:
            self.stdscr.addstr(0, 0, header.ljust(w - 1)[:w - 1], curses.color_pair(1) | curses.A_BOLD)
        except Exception:
            pass

        # Mode and stats
        mode_text = " {} | {} flights ".format(self.mode.capitalize(), len(self.visible_flights()))
        try:
            self.stdscr.addstr(1, 0, mode_text[:w - 1])
        except Exception:
            pass

        # Alert count
        if self.alert_manager:
            alert_count = self.alert_manager.active_count()
            if alert_count > 0:
                alert_text = " ⚠ {} alerts ".format(alert_count)
                try:
                    x_pos = max(0, w - len(alert_text))
                    self.stdscr.addstr(1, x_pos, alert_text[:w - x_pos], curses.color_pair(3))
                except Exception:
                    pass

        # Render based on mode
        if self.mode == "alerts":
            self._render_alerts(3, max(0, h - 4), w)
        elif self.mode == "airlines":
            self._render_airlines(3, max(0, h - 4), w)
        else:
            self._render_flights(3, max(0, h - 4), w)

        # Footer
        footer = " [1]Dept [2]Arr [5]Alerts [6]Airlines [W]Web [Q]uit "
        try:
            self.stdscr.addstr(h - 1, 0, footer.ljust(w - 1)[:w - 1], curses.color_pair(4))
        except Exception:
            pass

        self.stdscr.refresh()

    def _add(self, y, x, text, attr=None):
        """Add string to screen with bounds checking."""
        try:
            h, w = self.stdscr.getmaxyx()
            # Check bounds
            if y < 0 or y >= h or x < 0 or x >= w:
                return
            # Truncate text to fit
            max_len = w - x
            if max_len <= 0:
                return
            text = text[:max_len]
            if attr:
                self.stdscr.addstr(y, x, text, attr)
            else:
                self.stdscr.addstr(y, x, text)
        except Exception:
            pass

    def _render_flights(self, y, h, w):
        """Render flight table."""
        import curses

        flights = self.visible_flights()
        pages = self.page_count()
        self.clamp_page()

        page_start = self.page * 20
        page_end = min(page_start + 20, len(flights))
        page_flights = flights[page_start:page_end]

        if not page_flights:
            self._add(y, 2, "No flights found.")
            return

        # Header row
        header = "{:<6} {:<10} {:<6} {:<20} {:<18} {:<12} {:<5}".format(
            "TIME", "FLIGHT", "REG", "ROUTE", "STATUS", "GATE/STAND", "TERM"
        )
        self._add(y, 0, header, curses.A_BOLD)

        # Calculate available rows (leave room for footer)
        max_rows = min(h - 2, 20)

        for i, rec in enumerate(page_flights[:max_rows]):
            row_y = y + 1 + i
            if row_y >= y + h - 1:  # Leave room for footer
                break

            time_str = rec.get("time", "--:--")
            flight = rec.get("flight_number", "N/A")
            reg = rec.get("registration", "-")
            route = route_text(rec)
            status = rec.get("status", "N/A")
            gs = gate_stand_text(rec)
            term = rec.get("terminal", "-")

            # Color by status. Keep the category-to-pair mapping in utils.py.
            status_cat = rec.get("status_category", "scheduled")
            pair_id = status_pair(status_cat)
            if pair_id == 0:
                pair_id = 5
            attr = curses.color_pair(pair_id)
            if status_cat in ("departed", "landed"):
                attr |= curses.A_DIM

            line = "{:<6} {:<10} {:<6} {:<20} {:<18} {:<12} {:<5}".format(
                time_str, flight, reg, route, status, gs, term
            )

            self._add(row_y, 0, line, attr)

        # Page indicator
        if pages > 1:
            page_text = " Page {}/{} [←/→ to navigate] ".format(self.page + 1, pages)
            page_y = max(y, y + h - 2)  # Ensure we don't overlap with footer
            if page_y < y + h:
                self._add(page_y, 0, page_text, curses.color_pair(4))

    def _render_alerts(self, y, h, w):
        """Render alerts view."""
        active = self.alert_manager.get_active() if self.alert_manager else []

        self._add(y, 0, " Active Alerts ({}) ".format(len(active)), 0)

        for i, alert in enumerate(active[:h - 2]):
            field = alert.get("field", "?")
            old_v = alert.get("old_value", "")
            new_v = alert.get("new_value", "")
            flight = alert.get("flight_number", "?")
            status = alert.get("status", "")

            line = "  ⚠ {} {}: {} → {} | {}".format(flight, field, old_v, new_v, status)
            self._add(y + 1 + i, 0, line[:w - 1])

    def _render_airlines(self, y, h, w):
        """Render airlines view."""
        airlines = self.api.fetch_airlines()

        self._add(y, 0, " Airlines ({}) ".format(len(airlines)), 0)

        for i, airline in enumerate(airlines[:h - 2]):
            code = airline.get("code", "?")
            name = airline.get("name", "?")

            line = "  {} - {}".format(code, name)
            self._add(y + 1 + i, 0, line[:w - 1])

    def prompt(self, label):
        """Show input prompt."""
        import curses

        h, w = self.stdscr.getmaxyx()
        self.stdscr.addstr(h - 1, 0, label.ljust(w))
        self.stdscr.refresh()

        curses.echo()
        curses.cbreak()
        self.stdscr.timeout(-1)

        try:
            text = self.stdscr.getstr(h - 1, len(label), 50).decode("utf-8")
        except Exception:
            text = ""

        curses.noecho()
        self.stdscr.timeout(1000)

        return text.strip()

    def cmd_search(self):
        """Search for a flight."""
        text = self.prompt("Flight number: ")
        if text:
            self.filter_text = text
        self.load_view()

    def cmd_alerts(self):
        """Show alerts view."""
        self.mode = "alerts"
        self.render()
        self.stdscr.getch()
        self.mode = "departures"

    def cmd_airlines(self):
        """Show airlines view."""
        self.mode = "airlines"
        self.render()
        self.stdscr.getch()
        self.mode = "departures"

    def cmd_web(self):
        """Toggle web server."""
        if self.web_server and self.web_server.running():
            self.web_server.stop()
        elif self.web_server:
            self.web_server.start()

    def set_mode(self, mode):
        """Set current view mode."""
        self.mode = mode
        self.page = 0

    def handle_key(self, ch):
        """Handle key press."""
        import curses

        if ch == -1:
            return

        if ch == curses.KEY_RESIZE:
            self.render()

        elif ch == ord("1"):
            self.set_mode("departures")
        elif ch == ord("2"):
            self.set_mode("arrivals")
        elif ch == ord("5"):
            self.cmd_alerts()
        elif ch == ord("6"):
            self.cmd_airlines()
        elif ch in (ord("w"), ord("W")):
            self.cmd_web()

        elif ch == 27:  # Escape clears the filter
            self.filter_text = ""

        elif ch == curses.KEY_LEFT:
            if self.page > 0:
                self.page -= 1
        elif ch == curses.KEY_RIGHT:
            if self.page < self.page_count() - 1:
                self.page += 1
        elif ch == curses.KEY_HOME:
            self.page = 0
        elif ch == curses.KEY_END:
            self.page = self.page_count() - 1

        elif ch == curses.KEY_BACKSPACE or ch == 127 or ch == 8:
            self.filter_text = self.filter_text[:-1]
        elif 32 <= ch < 127:  # Printable characters append to filter
            self.filter_text += chr(ch)

        self.render()

    def run(self):
        """Main TUI loop."""
        self.render()

        while True:
            ch = self.stdscr.getch()

            if ch == ord("q") or ch == ord("Q"):
                break

            self.handle_key(ch)


def start_tui(poller, api, alert_manager, web_server):
    """Start the curses TUI."""
    import curses

    def _main(stdscr):
        stdscr.keypad(True)
        stdscr.timeout(1000)

        tui = CursesTUI(stdscr, poller, api, alert_manager, web_server)
        tui.start()
        tui.run()

    curses.wrapper(_main)
