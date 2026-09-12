"""Enhanced UI: mounts and drives the shared session.

Skipped when Textual is not installed, so the base suite stays dependency-free.
"""

import asyncio
import html
import importlib.util
import re
import tempfile
import time
import unittest
from datetime import datetime, timedelta

from hkg_flight.alerts import AlertManager
from hkg_flight.cache import CacheSystem
from hkg_flight.terminal import views
from hkg_flight.terminal.presenter import DEPARTURES, ARRIVALS, ALERTS, anchor_index
from hkg_flight.terminal.session import Session
from hkg_flight.utils import HKT, today_str

HAS_TEXTUAL = importlib.util.find_spec("textual") is not None

if HAS_TEXTUAL:
    from hkg_flight.terminal.textual_app import FlightBoardApp

TODAY = today_str()


def at(minutes, day=TODAY):
    """A fixed HKT clock reading, so no test depends on the hour it runs at."""
    hour, minute = divmod(minutes, 60)
    year, month, day_of_month = (int(part) for part in day.split("-"))
    return datetime(year, month, day_of_month, hour, minute, tzinfo=HKT)


def shift_day(date_str, days):
    """``date_str`` moved by ``days``, in the same YYYY-MM-DD form."""
    year, month, day = (int(part) for part in date_str.split("-"))
    return (datetime(year, month, day, tzinfo=HKT)
            + timedelta(days=days)).date().isoformat()

# The longest status the HKIA feed produces; its parenthesised date is what
# used to wrap onto a row of its own on a phone screen.
LONG_STATUS = "At gate 23:47 (06/09/2026)"


def raw_payload(count=30, status="Scheduled", date_str=TODAY):
    entries = []
    for i in range(count):
        entries.append({
            "arrival": i % 2 == 1, "cargo": False, "date": date_str,
            "list": [{"flight": [{"airline": "CPA", "no": f"CX {100 + i}"}],
                      "time": f"{i % 24:02d}:{(i * 7) % 60:02d}",
                      "status": status,
                      "gate": str(10 + i) if i % 2 == 0 else None,
                      "stand": f"W{10 + i}" if i % 2 == 1 else None,
                      "terminal": "T1", "destination": ["NRT"], "origin": ["SYD"]}],
        })
    return entries


class FakeAPI:
    def __init__(self, status="Scheduled", count=30):
        self.status = status
        self.count = count

    def fetch_flights(self, date_str):
        # The requested date is what the payload is *about*. A board that spans
        # midnight fetches two dates, and returning the same day for both would
        # hide exactly the bug the window is here to expose.
        return raw_payload(count=self.count, status=self.status, date_str=date_str)

    def fetch_airlines_meta(self):
        return {"airlines": [{"code": "CX", "description": ["Cathay"]}],
                "source": "api", "ok": True, "error": None}


# Textual exports flat ``<text>`` elements today, but the attribute pattern
# still skips over quoted values so a ``>`` inside one cannot end the tag early.
_TEXT_RE = re.compile(r'<text((?:"[^"]*"|[^>"])*)>(.*?)</text>', re.S)
# Anchored so an attribute whose *name* ends in x/y (``index="5"``) cannot be
# mistaken for the coordinate.
_X_ATTR_RE = re.compile(r'(?<![A-Za-z0-9_-])x="([^"]*)"')
_Y_ATTR_RE = re.compile(r'(?<![A-Za-z0-9_-])y="([^"]*)"')
_INNER_TAG_RE = re.compile(r"<[^>]+>")


def _unescape(raw):
    """SVG text content as plain text.

    ``html.unescape`` covers named, decimal and hex references in one go, so a
    future Textual that switches to ``&#x2192;`` cannot quietly leave escaped
    junk in the text. Textual writes its spaces as ``&#160;``, and those have
    to come back as *plain* spaces: a non-breaking space is a different
    character to the rows ``views`` produces, so comparisons would stop
    matching even though the screen looks identical.
    """
    return html.unescape(raw).replace("\xa0", " ")


def screen_runs(app):
    """``(y, x, text)`` for every run Textual painted, in screen order."""
    svg = app.export_screenshot()
    runs = []
    for match in _TEXT_RE.finditer(svg):
        attrs, raw = match.group(1), match.group(2)
        # Strip inner tags *before* unescaping, so a literal ``&lt;tspan&gt;``
        # in the text survives as text instead of being eaten as markup.
        text = _unescape(_INNER_TAG_RE.sub("", raw))
        x = float(_X_ATTR_RE.search(attrs).group(1))
        y = float(_Y_ATTR_RE.search(attrs).group(1))
        runs.append((round(y, 1), x, text))
    return runs


def screen_lines(app):
    """The composited screen as plain text rows, straight from Textual.

    ``export_screenshot`` is the only view of what Textual actually painted
    after its own wrapping, so it is the one way to observe a wrap.

    Textual emits one ``<text>`` run per *style* run, not per row - a flight
    row's status is its own run at a larger ``x`` on the same ``y``. The rows
    therefore have to be rebuilt: group the runs by ``y``, then splice each one
    back in at the cell its ``x`` names. Reading every run as a row invents
    wraps that are not there.
    """
    runs = screen_runs(app)
    if not runs:
        return []
    # Rich sizes the SVG from the terminal width, and terminates every painted
    # line but the last with a blank end-of-line run at ``width * cell``. The
    # largest x is therefore the right margin, and it calibrates the cell width
    # (a font metric - 12.2 - rather than a round number) without hard-coding.
    #
    # The calibration only holds while that run is blank. If the rightmost run
    # is content, the cell comes out too small and every run gets spliced in
    # too far right - silently, since the geometry tests only compare text. So
    # refuse to guess rather than produce plausible-looking wrong rows.
    rightmost = max(runs, key=lambda run: run[1])
    if rightmost[2].strip():
        raise AssertionError(
            "cannot calibrate the cell width: the rightmost run is content "
            "(%r at x=%s), not the end-of-line run at the right margin"
            % (rightmost[2], rightmost[1]))
    cell = rightmost[1] / max(1, app.size.width)
    grouped = {}
    for y, x, text in runs:
        if text.strip():
            grouped.setdefault(y, []).append((x, text))
    lines = []
    for y in sorted(grouped):
        line = ""
        for x, text in sorted(grouped[y]):
            line += " " * max(0, int(round(x / cell)) - views.text_width(line))
            line += text
        lines.append(line)
    for line in lines:
        # The guard above covers the cell width; this one covers the splice.
        # A run placed at the wrong column pushes the row past the terminal,
        # which is the one failure the geometry tests cannot see in the text.
        if views.text_width(line) > app.size.width:
            raise AssertionError(
                "rebuilt row is wider than the terminal (%d > %d): %r"
                % (views.text_width(line), app.size.width, line))
    return lines


def build_session(status="Scheduled", count=30, clock=None, reconcile=True):
    """A session as the front-ends get one.

    ``reconcile=False`` mirrors the real start-up order: ``Session.start()``
    does not touch the UI state, so nothing has anchored the list by the time
    the app mounts - the app has to do it itself.
    """
    cache = CacheSystem(tempfile.mkdtemp())
    kwargs = {"no_poll": True}
    if clock is not None:
        kwargs["clock"] = clock
    session = Session(cache=cache, api=FakeAPI(status=status, count=count),
                      alert_manager=AlertManager(cache), **kwargs)
    session.poller.refresh_now()
    if reconcile:
        session.reconcile()
    return session


@unittest.skipUnless(HAS_TEXTUAL, "Textual is not installed")
class TestTextualApp(unittest.TestCase):
    def setUp(self):
        # A fixed clock: the anchor is derived from it, so a real one would
        # make these tests pass or fail depending on the hour they ran at.
        self.session = build_session(clock=lambda: at(9 * 60))

    def tearDown(self):
        self.session.close()

    def test_mounts_and_renders(self):
        async def scenario():
            app = FlightBoardApp(self.session)
            async with app.run_test() as pilot:
                await pilot.pause()
                self.assertTrue(app.query("#header"))
                self.assertTrue(app.query("#body"))

        asyncio.run(scenario())

    def test_page_keys_switch_pages(self):
        async def scenario():
            app = FlightBoardApp(self.session)
            async with app.run_test() as pilot:
                await pilot.press("2")
                self.assertEqual(self.session.state.current, ARRIVALS)
                await pilot.press("5")
                self.assertEqual(self.session.state.current, ALERTS)
                await pilot.press("1")
                self.assertEqual(self.session.state.current, DEPARTURES)

        asyncio.run(scenario())

    def test_navigation_keys_move_the_selection(self):
        """The cursor moves one row per press, wherever the clock parked it."""
        async def scenario():
            app = FlightBoardApp(self.session)
            async with app.run_test() as pilot:
                page = self.session.state.pages[DEPARTURES]
                rows = self.session.rows_for(DEPARTURES)
                # The list opens on the first flight at or after the board's
                # clock, not on row 0, so only the movement is fixed here.
                start = page.selected_index
                await pilot.press("down")
                await pilot.press("down")
                self.assertEqual(page.selected_index, min(start + 2, len(rows) - 1))
                self.assertFalse(page.anchor_auto)

        asyncio.run(scenario())

    def render_row(self, row, page, width):
        """A row as the plain-text lines the screen should carry for it."""
        return [views.strip_tags(line) for line in views.flight_row(
            row["record"], width, color=False,
            selected=row["id"] == page.selected_id,
            compact=views.is_compact(width))]

    def test_the_board_opens_on_the_flights_that_are_current_now(self):
        """A 09:00 board starts at the first flight after 09:00, not at row 0."""
        session = build_session(count=200, clock=lambda: at(9 * 60), reconcile=False)
        try:
            async def scenario():
                app = FlightBoardApp(session)
                async with app.run_test(size=(100, 24)) as pilot:
                    await pilot.pause()
                    page = session.state.pages[DEPARTURES]
                    rows = session.rows_for(DEPARTURES)
                    # The fixture has to leave room on both sides, or the
                    # assertion would hold even if the anchor were ignored.
                    self.assertGreater(page.offset, 0)
                    self.assertLess(page.offset, len(rows) - 1)
                    self.assertTrue(page.anchor_auto)
                    screen = [views.strip_tags(line) for line in screen_lines(app)]
                    for line in self.render_row(rows[page.offset], page, app.size.width):
                        self.assertIn(line, screen)
                    for line in self.render_row(rows[page.offset - 1], page,
                                                app.size.width):
                        self.assertNotIn(line, screen)

            asyncio.run(scenario())
        finally:
            session.close()

    def test_the_page_keys_step_one_screen_from_the_clock(self):
        session = build_session(count=200, clock=lambda: at(9 * 60), reconcile=False)
        try:
            async def scenario():
                app = FlightBoardApp(session)
                async with app.run_test(size=(100, 24)) as pilot:
                    await pilot.pause()
                    page = session.state.pages[DEPARTURES]
                    rows = session.rows_for(DEPARTURES)
                    capacity = views.row_capacity(session.state, rows,
                                                  app.size.width, app.size.height)
                    self.assertGreater(capacity, 1)
                    start = page.offset
                    self.assertLess(start + capacity, len(rows))

                    await pilot.press("right_square_bracket")
                    self.assertEqual(page.offset, start + capacity)
                    self.assertFalse(page.anchor_auto)

                    await pilot.press("left_square_bracket")
                    self.assertEqual(page.offset, start)

                    await pilot.press("t")
                    self.assertTrue(page.anchor_auto)
                    self.assertEqual(page.offset, start)

            asyncio.run(scenario())
        finally:
            session.close()

    def test_a_board_opened_after_midnight_does_not_open_on_yesterday(self):
        """01:30: the board carries yesterday too, and must still open on today.

        This is the end-to-end form of the anchor's date: the same rows, the
        same renderer, and a viewport that would sit a whole day in the past if
        the anchor compared times of day alone.
        """
        yesterday = shift_day(TODAY, -1)
        session = build_session(count=200, clock=lambda: at(1 * 60 + 30),
                                reconcile=False)
        try:
            async def scenario():
                app = FlightBoardApp(session)
                async with app.run_test(size=(100, 24)) as pilot:
                    await pilot.pause()
                    snap = session.snapshot()["flights"]
                    self.assertEqual(snap["records_dates"], [yesterday, TODAY])

                    page = session.state.pages[DEPARTURES]
                    rows = session.rows_for(DEPARTURES)
                    self.assertEqual(rows[page.offset]["record"]["date"], TODAY)
                    # Yesterday really is on the board, at the top of it...
                    self.assertEqual(rows[0]["record"]["date"], yesterday)
                    # ...and the date-blind anchor would have stopped there.
                    blind = anchor_index(rows, 1 * 60 + 30)
                    self.assertEqual(rows[blind]["record"]["date"], yesterday)
                    self.assertNotEqual(blind, page.offset)

                    # And it is what the screen actually shows.
                    screen = [views.strip_tags(line) for line in screen_lines(app)]
                    for line in self.render_row(rows[page.offset], page, app.size.width):
                        self.assertIn(line, screen)

            asyncio.run(scenario())
        finally:
            session.close()

    def test_a_landed_refresh_carries_the_clock_anchor_with_it(self):
        now = [at(9 * 60)]
        session = build_session(count=200, clock=lambda: now[0], reconcile=False)
        try:
            async def scenario():
                app = FlightBoardApp(session)
                async with app.run_test(size=(100, 24)) as pilot:
                    await pilot.pause()
                    page = session.state.pages[DEPARTURES]
                    rows = session.rows_for(DEPARTURES)
                    self.assertEqual(page.offset, anchor_index(rows, 9 * 60, TODAY))

                    # Time passes while the board is open. The next refresh has
                    # to move the list with it, or the board would still be
                    # showing the morning's flights.
                    now[0] = at(15 * 60)
                    session.poller.refresh_now()
                    await asyncio.sleep(0.45)
                    self.assertTrue(page.anchor_auto)
                    self.assertEqual(page.offset, anchor_index(rows, 15 * 60, TODAY))

            asyncio.run(scenario())
        finally:
            session.close()

    def test_a_landed_refresh_leaves_a_pinned_page_where_the_user_left_it(self):
        now = [at(9 * 60)]
        session = build_session(count=200, clock=lambda: now[0], reconcile=False)
        try:
            async def scenario():
                app = FlightBoardApp(session)
                async with app.run_test(size=(100, 24)) as pilot:
                    await pilot.pause()
                    page = session.state.pages[DEPARTURES]
                    await pilot.press("right_square_bracket")
                    pinned = page.offset
                    self.assertFalse(page.anchor_auto)

                    now[0] = at(15 * 60)
                    session.poller.refresh_now()
                    await asyncio.sleep(0.45)
                    self.assertEqual(page.offset, pinned)

            asyncio.run(scenario())
        finally:
            session.close()

    def test_help_overlay_toggles(self):
        async def scenario():
            app = FlightBoardApp(self.session)
            async with app.run_test() as pilot:
                await pilot.press("question_mark")
                self.assertTrue(self.session.state.help_open)
                await pilot.press("escape")
                self.assertFalse(self.session.state.help_open)

        asyncio.run(scenario())

    def test_search_input_drives_the_shared_state(self):
        async def scenario():
            app = FlightBoardApp(self.session)
            async with app.run_test() as pilot:
                await pilot.press("slash")
                await pilot.press("C", "X", "1")
                await pilot.pause()
                self.assertEqual(self.session.state.pages[DEPARTURES].search_text, "CX1")

        asyncio.run(scenario())


@unittest.skipUnless(HAS_TEXTUAL, "Textual is not installed")
class TestTextualGeometry(unittest.TestCase):
    """The widget's content box must match what the renderer was handed.

    Textual wraps at the last *word*, so a line that is one cell too wide is
    not clipped - a whole value moves onto the next row. That is what put
    "(12/09/2026)" on a row of its own on a phone screen. ``theme.tcss`` used
    to pad every full-width widget by ``0 1``, which made the content box two
    cells narrower than the width the views were rendered at, so the invariant
    "content box == render width" has to be pinned on the real widget.
    """

    def setUp(self):
        self.session = build_session()

    def tearDown(self):
        self.session.close()

    def test_the_body_content_box_is_the_terminal_width(self):
        async def scenario():
            for size in ((55, 30), (80, 30), (100, 30), (45, 20), (120, 30)):
                app = FlightBoardApp(self.session)
                async with app.run_test(size=size) as pilot:
                    await pilot.pause()
                    body = app.query_one("#body")
                    self.assertEqual(body.content_size.width, app.size.width, size)
                    self.assertEqual(body.size.width, app.size.width, size)

        asyncio.run(scenario())

    def test_nothing_the_views_render_can_wrap_or_be_clipped(self):
        async def scenario():
            for size in ((55, 30), (80, 30), (100, 30), (45, 20), (120, 30)):
                app = FlightBoardApp(self.session)
                async with app.run_test(size=size) as pilot:
                    await pilot.pause()
                    body = app.query_one("#body")
                    lines = views.body_lines(self.session.state, self.session.snapshot(),
                                             app.size.width, app.size.height, False)
                    for line in lines:
                        self.assertLessEqual(views.text_width(line), body.content_size.width,
                                             (size, line))
                    self.assertLessEqual(len(lines), body.content_size.height, size)

        asyncio.run(scenario())

    def test_the_chrome_row_count_matches_the_real_layout(self):
        async def scenario():
            for size in ((55, 30), (45, 20), (120, 40)):
                app = FlightBoardApp(self.session)
                async with app.run_test(size=size) as pilot:
                    await pilot.pause()
                    chrome = sum(app.query_one(f"#{name}").size.height
                                 for name in ("header", "nav", "search_row", "footer"))
                    self.assertEqual(chrome, views.CHROME_ROWS, size)
                    body = app.query_one("#body")
                    self.assertEqual(body.size.height,
                                     app.size.height - views.CHROME_ROWS, size)

        asyncio.run(scenario())

    def test_every_rendered_line_reaches_the_screen_intact(self):
        """The strongest end-to-end statement: nothing wraps anywhere.

        Every string the views produce has to arrive on the real screen as
        exactly one row - the four chrome bars and the body alike. A single
        line one cell too wide for its widget comes back as two rows and fails
        here, which is what the padded widgets used to do.
        """
        session = build_session(status=LONG_STATUS)
        try:
            async def scenario():
                for width in (42, 55, 80, 120):
                    app = FlightBoardApp(session)
                    async with app.run_test(size=(width, 30)) as pilot:
                        await pilot.pause()
                        snap = session.snapshot()
                        tier = views.layout_tier(width, 30)
                        expected = [
                            views.header_line(snap, snap["web"], now=time.time(),
                                              today=TODAY, width=width),
                            views.nav_line(session.state, len(snap["alerts"]["alerts"]),
                                           snap["flights"].get("polling_enabled", True),
                                           snap["web"]["status"], width=width),
                            views.search_line(session.state, snap, width=width),
                        # Colour only adds markup; strip_tags makes the visible
                        # text the same whether or not the app renders colour.
                        ] + views.body_lines(session.state, snap, width, 30, False) + [
                            views.footer_line(tier, session.state, width=width),
                        ]
                        painted = [row.rstrip() for row in screen_lines(app)]
                        for line in expected:
                            text = views.strip_tags(line).rstrip()
                            if not text:
                                continue
                            self.assertIn(text, painted,
                                          "%d columns: %r did not reach the screen "
                                          "as one row" % (width, text))

            asyncio.run(scenario())
        finally:
            session.close()

    def test_a_long_status_stays_on_its_flight_row(self):
        """The screenshot bug, observed end to end on the real screen.

        The status carries a parenthesised date ("At gate 23:47 (06/09/2026)").
        It used to be starved into a stub and pushed onto a row of its own,
        cut to "(06/09/20…". This drives the real app and reads the real
        composited screen back.
        """
        session = build_session(status=LONG_STATUS)
        fragment = LONG_STATUS[LONG_STATUS.index("("):]
        try:
            async def scenario():
                # 42 is the narrowest width at which the status still fits the
                # column minimums; 120 is wide enough for the single-line row.
                for width in (42, 45, 48, 55, 80, 100, 120):
                    app = FlightBoardApp(session)
                    async with app.run_test(size=(width, 30)) as pilot:
                        await pilot.pause()
                        rows = screen_lines(app)
                        carrying = [row for row in rows if LONG_STATUS in row]
                        self.assertTrue(carrying, "status not rendered at %d:\n%s"
                                        % (width, "\n".join(rows)))
                        for row in carrying:
                            self.assertIn("CX", row, row)      # same row as the flight
                            self.assertLessEqual(views.text_width(row), width, row)
                        self.assertFalse(
                            [row for row in rows if row.strip() == fragment],
                            "the date wrapped onto a row of its own at %d" % width)

            asyncio.run(scenario())
        finally:
            session.close()

    def test_a_word_that_does_not_fit_moves_to_its_own_row(self):
        """Negative control: the detector really can see a wrap.

        Textual does not clip a line that is too wide - it moves whole words
        onto the next row, which is how "(06/09/2026)" ended up on a row of its
        own on the phone. The fix is that a widget's content box is now exactly
        the width the views were handed, so no rendered line can overflow it.
        This overflows one on purpose to prove the detector is load-bearing.
        """
        session = build_session(status=LONG_STATUS)
        try:
            async def scenario():
                app = FlightBoardApp(session)
                async with app.run_test(size=(55, 30)) as pilot:
                    await pilot.pause()
                    body = app.query_one("#body")
                    record = next(r for r in session.snapshot()["flights"]["records"]
                                  if r.get("type") == "departure")
                    row = views.flight_row(record, app.size.width, compact=True)[0]
                    self.assertEqual(views.text_width(row), app.size.width)

                    body.update(row + "  MOVE-ME-NOW")
                    await pilot.pause()
                    await pilot.pause()
                    rows = screen_lines(app)
                    self.assertIn("MOVE-ME-NOW", [row.strip() for row in rows],
                                  "a word that cannot fit was clipped, not moved")

            asyncio.run(scenario())
        finally:
            session.close()

    def test_the_old_padding_would_have_wrapped(self):
        """Negative control: put the horizontal padding back and watch it break.

        ``theme.tcss`` used to pad every full-width widget by ``0 1``, so the
        content box was two cells narrower than the width the views rendered
        at. A line whose last token reaches the right edge cannot absorb that:
        the rule is exactly ``width`` dashes with no spaces to give, so it
        splits in two the moment the box shrinks. (A flight row has trailing
        padding to spare and survives - which is why the padding was easy to
        miss and the invariant needs its own test.)
        """
        session = build_session(status=LONG_STATUS)
        try:
            async def scenario():
                app = FlightBoardApp(session)
                async with app.run_test(size=(55, 30)) as pilot:
                    await pilot.pause()
                    body = app.query_one("#body")
                    rules = [row for row in screen_lines(app)
                             if row.strip() and set(row.strip()) == {"-"}]
                    self.assertEqual(len(rules), 1, rules)
                    self.assertEqual(views.text_width(rules[0]), app.size.width)

                    body.styles.padding = (0, 1)      # the old theme.tcss
                    app.revision += 1                 # re-render through the app
                    await pilot.pause()
                    await pilot.pause()
                    self.assertEqual(body.content_size.width, app.size.width - 2)
                    rules = [row for row in screen_lines(app)
                             if row.strip() and set(row.strip()) == {"-"}]
                    self.assertGreater(len(rules), 1,
                                       "the rule should have split in two: %s" % rules)

            asyncio.run(scenario())
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
