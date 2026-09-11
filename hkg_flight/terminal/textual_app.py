"""
HKG Flight Data v3 - Textual Adapter
Optional enhanced interface (requires Textual, Python >= 3.9).

The app is a thin event mapper: every key reduces through the shared
``Session`` state machine and re-renders the pure ``views`` strings. It never
touches the network, threads or the API directly.
"""

import os
import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Input, Static

from . import views
from .presenter import DEPARTURES, ARRIVALS, ALERTS, AIRLINES, FLIGHT_PAGES
from .state import dispatch
from ..utils import today_str


class FlightBoardApp(App):
    """Textual front-end for the flight workbench session."""

    CSS_PATH = "theme.tcss"

    BINDINGS = [
        Binding("1", "page_departures", "Departures", show=False),
        Binding("2", "page_arrivals", "Arrivals", show=False),
        Binding("5", "page_alerts", "Alerts", show=False),
        Binding("6", "page_airlines", "Airlines", show=False),
        Binding("slash", "search", "Search", show=False),
        Binding("enter", "enter", "Detail", show=False),
        Binding("escape", "escape", "Close", show=False),
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("pageup", "page_up", show=False),
        Binding("pagedown", "page_down", show=False),
        Binding("home", "go_home", show=False),
        Binding("end", "go_end", show=False),
        Binding("tab", "tab_next", show=False),
        Binding("shift+tab", "tab_prev", show=False),
        Binding("left", "page_prev", "Prev", show=False),
        Binding("right", "page_next", "Next", show=False),
        Binding("f", "toggle_filter", "Filter", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("w", "toggle_web", "Web", show=False),
        Binding("question_mark", "toggle_help", "Help", show=False),
        Binding("q", "quit_app", "Quit", show=False),
        Binding("ctrl+q", "quit_app", "Quit", show=False),
        Binding("ctrl+c", "quit_app", "Quit", show=False),
    ]

    revision = reactive(0)

    def __init__(self, session, color=None):
        super().__init__()
        self.session = session
        self._color = color if color is not None else ("NO_COLOR" not in os.environ)
        self._last_revision = None
        self._snap = session.snapshot()

    # -- composition ------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Static(id="header")
        yield Static(id="nav")
        yield Horizontal(Static(id="search_label"), id="search_row")
        yield Static(id="body")
        yield Static(id="footer")

    def on_mount(self):
        self._mounted = True
        self.set_interval(1.0, self._clock_tick)
        self.set_interval(0.2, self._poll)
        self._refresh_view()

    # -- data flow --------------------------------------------------------
    def _poll(self):
        latest = self.session.latest_revision()
        if latest != self._last_revision:
            self._last_revision = latest
            self.revision += 1

    def _clock_tick(self):
        self._refresh_header()

    def watch_revision(self, _old, _new):
        if getattr(self, "_mounted", False):
            self._refresh_view()

    def on_resize(self, _event=None):
        if getattr(self, "_mounted", False):
            self._refresh_view()

    def _refresh_header(self):
        if not getattr(self, "_mounted", False):
            return
        self._snap = self.session.snapshot()
        flights = self._snap["flights"]
        web = self._snap["web"]
        header = self.query_one("#header", Static)
        nav = self.query_one("#nav", Static)
        # The widgets run edge to edge (theme.tcss sets no horizontal padding),
        # so the terminal width is exactly the width available to the text.
        width = self.size.width
        header.update(views.header_line(self._snap, web, now=time.time(),
                                        today=today_str(), width=width))
        nav.update(views.nav_line(
            self.session.state,
            len(self._snap["alerts"]["alerts"]),
            flights.get("polling_enabled", True),
            web["status"],
            width=width,
        ))

    def _refresh_view(self):
        self._refresh_header()
        state = self.session.state
        body = self.query_one("#body", Static)
        footer = self.query_one("#footer", Static)
        search_label = self.query_one("#search_label", Static)

        size = self.size
        tier = views.layout_tier(size.width, size.height)
        lines = views.body_lines(state, self._snap, size.width, size.height, self._color)
        body.update("\n".join(lines))
        footer.update(views.footer_line(tier, state, width=size.width))

        if state.focus == "search":
            self._ensure_search_input()
            search_label.display = False
            self.query_one("#search_input", Input).display = True
        else:
            self._remove_search_input()
            search_label.display = True
            search_label.update(views.search_line(state, self._snap, width=size.width))

    # -- focus helper -----------------------------------------------------
    def _ensure_search_input(self):
        existing = self.query("#search_input")
        if existing:
            return existing.first()
        inp = Input(id="search_input", placeholder="search…")
        self.query_one("#search_row").mount(inp)
        return inp

    def _remove_search_input(self):
        existing = self.query("#search_input")
        if existing:
            existing.first().remove()

    def _enter_search(self):
        self.session.handle({"type": "slash"})
        self._refresh_view()
        inp = self._ensure_search_input()
        inp.value = self.session.state.pages[self.session.state.current].search_text
        inp.focus()

    def _body_height(self):
        """Rows a page-up/page-down jump moves by: the terminal minus the chrome."""
        return max(1, self.size.height - views.CHROME_ROWS)

    # -- actions ----------------------------------------------------------
    def action_page_departures(self):
        self._page(DEPARTURES)

    def action_page_arrivals(self):
        self._page(ARRIVALS)

    def action_page_alerts(self):
        self._page(ALERTS)

    def action_page_airlines(self):
        self._page(AIRLINES)

    def _page(self, name):
        rows = self.session.rows_for(name)
        self.session.state, _ = dispatch(
            self.session.state, rows, {"type": "page", "page": name})
        self._refresh_view()

    def action_search(self):
        if self.session.state.current in FLIGHT_PAGES or self.session.state.current == ALERTS:
            self._enter_search()

    def action_enter(self):
        self._act({"type": "enter"})

    def action_escape(self):
        self._act({"type": "escape"})

    def action_cursor_up(self):
        self._move("up")

    def action_cursor_down(self):
        self._move("down")

    def action_page_up(self):
        self._move("pgup")

    def action_page_down(self):
        self._move("pgdn")

    def action_go_home(self):
        self._move("home")

    def action_go_end(self):
        self._move("end")

    def action_page_prev(self):
        self._move("pgup")

    def action_page_next(self):
        self._move("pgdn")

    def action_tab_next(self):
        self._act({"type": "tab"})

    def action_tab_prev(self):
        self._act({"type": "tab", "backward": True})

    def action_toggle_filter(self):
        self._act({"type": "toggle_filter"})

    def action_refresh(self):
        self._act({"type": "refresh"})

    def action_toggle_web(self):
        self._act({"type": "web"})

    def action_toggle_help(self):
        self._act({"type": "help"})

    def action_quit_app(self):
        self._act({"type": "quit"})
        self.exit()

    def _move(self, direction):
        self._act({"type": "move", "direction": direction, "height": self._body_height()})

    def _act(self, action):
        commands = self.session.handle(action)
        self._refresh_view()
        return commands

    # -- search input events ----------------------------------------------
    def on_input_changed(self, event):
        state = self.session.state
        page = state.pages[state.current]
        page.search_text = event.value
        self.session.reconcile()
        self._refresh_header()
        self._refresh_body_only()

    def on_input_submitted(self, _event):
        self._act({"type": "search_submit"})

    def _refresh_body_only(self):
        body = self.query_one("#body", Static)
        size = self.size
        body.update("\n".join(
            views.body_lines(self.session.state, self._snap, size.width, size.height,
                             self._color)))


def run_textual(session, color=None):
    """Run the enhanced interface; always closes the session it was given."""
    app = FlightBoardApp(session, color=color)
    try:
        app.run()
    finally:
        session.close()
    return app
