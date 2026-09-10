"""
HKG Flight Data v3 - Terminal State
Session-internal UI state and pure transitions.

The state model has no terminal, network or framework dependency. A reducer
``dispatch(state, rows, action)`` turns the current state and the current
page's visible rows into a new state plus a list of side-effect commands that
the session layer (and only the session layer) executes.
"""

from .presenter import (
    ALL_PAGES,
    AUX_PAGES,
    FLIGHT_PAGES,
    ALERTS,
    AIRLINES,
    DEPARTURES,
    STATUS_FILTERS,
)

# Set on ``state.message`` when reconcile cannot find the previously selected
# entity any more (record really deleted, not merely re-sorted or updated).
SELECTION_LOST_MESSAGE = "Selected flight is no longer available"


class PageState(object):
    """Per-page session state (search, filters, selection, scroll)."""

    def __init__(self):
        self.search_text = ""
        self.search_pre_edit = ""
        self.airline_filter = ""
        self.status_filter = ""
        self.selected_id = None
        self.selected_index = 0
        self.offset = 0


class AppState(object):
    """Full session-internal UI state (survives refresh, dies with session)."""

    def __init__(self):
        self.pages = {name: PageState() for name in ALL_PAGES}
        self.current = DEPARTURES
        self.focus = "list"
        self.detail_id = None
        self.detail_page = None
        self.filter_open = False
        self.help_open = False
        self.return_page = DEPARTURES
        self.message = ""


def _page(state, name=None):
    return state.pages[name or state.current]


def _has_overlay(state):
    return bool(state.detail_id or state.filter_open or state.help_open)


def _has_filter(page):
    return bool(page.search_text or page.airline_filter or page.status_filter)


def _select_index(state, rows, index, height=None):
    """Set the selection to ``index`` and keep it inside the scroll window."""
    page = _page(state)
    n = len(rows)
    if n == 0:
        page.selected_id = None
        page.selected_index = 0
        page.offset = 0
        return
    index = max(0, min(index, n - 1))
    page.selected_index = index
    page.selected_id = rows[index]["id"]
    if height and height > 0:
        if index < page.offset:
            page.offset = index
        elif index >= page.offset + height:
            page.offset = index - height + 1


def reconcile(state, rows):
    """Re-clamp selection/offset after rows changed (page switch, search, refresh).

    Selection is matched by **stable entity id**, never by position alone, so a
    gate/status update or a re-sort keeps the same flight selected instead of
    silently sliding onto whatever now occupies that row.

    When the selected entity is genuinely gone the selection degrades
    *visibly*: the cursor stays at the nearest surviving row, the message says
    the flight is no longer available, and the lost id is recorded in
    ``state.lost_selection_id``. Another flight's id is never reused to paper
    over the disappearance.
    """
    page = _page(state)
    n = len(rows)
    if n == 0:
        page.selected_id = None
        page.selected_index = 0
        page.offset = 0
        return

    if page.selected_id is None:
        page.selected_id = rows[0]["id"]
        page.selected_index = 0
        page.offset = max(0, min(page.offset, max(0, n - 1)))
        return

    index = None
    for i, row in enumerate(rows):
        if row["id"] == page.selected_id:
            index = i
            break

    if index is not None:
        page.selected_index = index
        page.offset = max(0, min(page.offset, max(0, n - 1)))
        return

    # The entity we were on is gone. Keep the cursor near where it was, adopt
    # that row's own id (a different id -- never the lost one) and say so.
    fallback = max(0, min(page.selected_index, n - 1))
    state.lost_selection_id = page.selected_id
    state.message = SELECTION_LOST_MESSAGE
    page.selected_index = fallback
    page.selected_id = rows[fallback]["id"]
    page.offset = max(0, min(page.offset, max(0, n - 1)))


def _switch_page(state, name):
    state.current = name
    state.focus = "list"
    state.detail_id = None
    state.filter_open = False
    state.help_open = False
    if name in FLIGHT_PAGES:
        state.return_page = name
    state.message = ""


def _clear_filters(state, page):
    page.search_text = ""
    page.search_pre_edit = ""
    page.airline_filter = ""
    page.status_filter = ""
    page.selected_index = 0
    page.selected_id = None
    page.offset = 0


def _close_overlay(state):
    if state.help_open:
        state.help_open = False
    elif state.filter_open:
        state.filter_open = False
    elif state.detail_id:
        state.detail_id = None
        state.detail_page = None
    state.focus = "list"


def dispatch(state, rows, action):
    """Reduce an action into (new_state, commands). ``rows`` is the current
    page's visible row list (list of ``{"id", "record"}``)."""
    commands = []
    kind = action.get("type", "")

    if kind == "page":
        name = action["page"]
        if name in ALL_PAGES and name != state.current:
            _switch_page(state, name)
            reconcile(state, rows)

    elif kind == "move":
        page = _page(state)
        if state.focus == "search" or state.detail_id:
            return state, commands
        delta = 0
        direction = action.get("direction")
        height = action.get("height")
        n = len(rows)
        if n == 0:
            return state, commands
        if direction == "up":
            delta = -1
        elif direction == "down":
            delta = 1
        elif direction == "pgup":
            delta = -(height or 10)
        elif direction == "pgdn":
            delta = height or 10
        elif direction == "home":
            _select_index(state, rows, 0, height)
            return state, commands
        elif direction == "end":
            _select_index(state, rows, n - 1, height)
            return state, commands
        else:
            return state, commands
        _select_index(state, rows, page.selected_index + delta, height)

    elif kind == "slash":
        if state.current in FLIGHT_PAGES or state.current == ALERTS:
            page = _page(state)
            page.search_pre_edit = page.search_text
            state.focus = "search"

    elif kind == "search_char":
        if state.focus == "search":
            page = _page(state)
            page.search_text += action.get("char", "")
            reconcile(state, rows)

    elif kind == "search_backspace":
        if state.focus == "search":
            page = _page(state)
            page.search_text = page.search_text[:-1]
            reconcile(state, rows)

    elif kind == "search_submit":
        if state.focus == "search":
            state.focus = "list"
            reconcile(state, rows)

    elif kind == "search_cancel":
        if state.focus == "search":
            page = _page(state)
            page.search_text = page.search_pre_edit
            state.focus = "list"
            reconcile(state, rows)

    elif kind == "tab":
        if state.detail_id:
            return state, commands
        areas = ["list", "search"]
        if state.filter_open:
            areas.append("filter")
        forward = not action.get("backward", False)
        index = areas.index(state.focus) if state.focus in areas else 0
        index = (index + (1 if forward else -1)) % len(areas)
        state.focus = areas[index]

    elif kind == "enter":
        page = _page(state)
        if state.focus == "search":
            state.focus = "list"
            reconcile(state, rows)
        elif state.focus == "filter":
            state.filter_open = False
            state.focus = "list"
        elif state.current == AIRLINES and state.focus == "list" and rows:
            selected = rows[page.selected_index]["record"]
            code = selected.get("code", "")
            target = _page(state, state.return_page)
            target.airline_filter = code
            target.selected_id = None
            target.selected_index = 0
            target.offset = 0
            _switch_page(state, state.return_page)
        elif state.current in FLIGHT_PAGES and state.focus == "list" and rows:
            state.detail_id = rows[page.selected_index]["id"]
            state.detail_page = state.current
            state.focus = "detail"
        elif state.current == ALERTS and state.focus == "list" and rows:
            state.detail_id = rows[page.selected_index]["id"]
            state.detail_page = ALERTS
            state.focus = "detail"

    elif kind == "escape":
        page = _page(state)
        if state.focus == "search":
            page.search_text = page.search_pre_edit
            state.focus = "list"
            reconcile(state, rows)
        elif _has_overlay(state):
            _close_overlay(state)
        elif _has_filter(page):
            _clear_filters(state, page)
            reconcile(state, rows)
        elif state.current in AUX_PAGES:
            _switch_page(state, state.return_page)
            reconcile(state, rows)

    elif kind == "toggle_filter":
        if state.detail_id:
            return state, commands
        state.filter_open = not state.filter_open
        state.focus = "filter" if state.filter_open else "list"

    elif kind == "filter_status":
        if state.focus == "filter":
            page = _page(state)
            direction = action.get("direction", "next")
            options = list(STATUS_FILTERS) + [""]
            current = page.status_filter
            index = options.index(current) if current in options else 0
            index = (index + (1 if direction == "next" else -1)) % len(options)
            page.status_filter = options[index]
            reconcile(state, rows)

    elif kind == "help":
        state.help_open = not state.help_open
        state.focus = "help" if state.help_open else "list"

    elif kind == "refresh":
        commands.append("refresh")

    elif kind == "web":
        commands.append("web_toggle")

    elif kind == "quit":
        commands.append("quit")

    return state, commands
