"""Plain adapter: line commands, paging, exit codes, no ANSI output."""

import tempfile
import unittest
from datetime import datetime

from hkg_flight.alerts import AlertManager
from hkg_flight.cache import CacheSystem
from hkg_flight.terminal import plain, views
from hkg_flight.terminal.presenter import DEPARTURES, ARRIVALS, ALERTS, AIRLINES
from hkg_flight.terminal.session import Session
from hkg_flight.utils import HKT, today_str

TODAY = today_str()

# 23:30 on 2026-09-12 covers the service dates [09-12, 09-13]: the widest the
# board's date text ever gets ("2026-09-12 +1").
LATE_DAY = "2026-09-12"
LATE_NEXT = "2026-09-13"
LATE = datetime(2026, 9, 12, 23, 30, tzinfo=HKT)


def raw_payload(count=25, date_str=None):
    date_str = date_str or TODAY
    entries = []
    for i in range(count):
        entries.append({
            "arrival": i % 2 == 1, "cargo": False, "date": date_str,
            "list": [{"flight": [{"airline": "CPA", "no": f"CX {100 + i}"}],
                      "time": f"{i % 24:02d}:{(i * 7) % 60:02d}",
                      "status": "Scheduled",
                      "gate": str(10 + i) if i % 2 == 0 else None,
                      "stand": f"W{10 + i}" if i % 2 == 1 else None,
                      "terminal": "T1",
                      "destination": ["NRT"], "origin": ["SYD"]}],
        })
    return entries


class FakeAPI:
    def __init__(self, raw=None, fail=False):
        self.raw = raw
        self.fail = fail

    def fetch_flights(self, date_str):
        if self.fail:
            raise RuntimeError("offline")
        # A mapping answers per date, so a two-date window gets both days.
        if isinstance(self.raw, dict):
            return self.raw.get(date_str, [])
        return self.raw

    def fetch_airlines_meta(self):
        return {"airlines": [], "source": "api", "ok": True, "error": None}


def make_session(raw=None, fail=False, clock=None):
    cache = CacheSystem(tempfile.mkdtemp())
    extra = {"clock": clock} if clock is not None else {}
    return Session(cache=cache, api=FakeAPI(raw, fail), alert_manager=AlertManager(cache),
                   **extra)


def two_date_session():
    """A session whose board spans midnight, so the date text carries ``+1``."""
    raw = {LATE_DAY: raw_payload(6, LATE_DAY), LATE_NEXT: raw_payload(6, LATE_NEXT)}
    session = make_session(raw, clock=lambda: LATE)
    session.poller.refresh_now()
    return session


class TestResultFor(unittest.TestCase):
    def snap(self, **flights):
        base = {"source": "none", "last_error": None, "records": []}
        base.update(flights)
        return {"flights": base}

    def test_api_success_exits_zero(self):
        self.assertEqual(plain.result_for(self.snap(source="api", records=[{}]))[0], 0)

    def test_api_empty_result_is_success(self):
        code, label = plain.result_for(self.snap(source="api"))
        self.assertEqual(code, 0)
        self.assertIn("no flights", label)

    def test_cache_fallback_exits_zero(self):
        code, label = plain.result_for(self.snap(source="cache", records=[{}], last_error="x"))
        self.assertEqual(code, 0)
        self.assertIn("cache fallback", label)

    def test_error_exits_nonzero(self):
        self.assertEqual(plain.result_for(self.snap(last_error="boom"))[0], 1)

    def test_memory_without_fresh_source_exits_nonzero(self):
        self.assertEqual(plain.result_for(self.snap(source="memory", records=[{}]))[0], 1)

    def test_no_data_exits_nonzero(self):
        self.assertEqual(plain.result_for(self.snap())[0], 1)


class TestClampOffset(unittest.TestCase):
    def test_clamps_to_last_page_start(self):
        self.assertEqual(plain.clamp_offset(0, 25, 10), 0)
        self.assertEqual(plain.clamp_offset(20, 25, 10), 20)
        self.assertEqual(plain.clamp_offset(999, 25, 10), 20)

    def test_empty_and_degenerate(self):
        self.assertEqual(plain.clamp_offset(5, 0, 10), 0)
        self.assertEqual(plain.clamp_offset(5, 10, 0), 0)


class TestRenderBlock(unittest.TestCase):
    def setUp(self):
        self.session = make_session(raw_payload())
        self.session.poller.refresh_now()

    def tearDown(self):
        self.session.close()

    def test_no_ansi_escape_sequences(self):
        for line in plain.render_block(self.session, DEPARTURES, "", 0):
            self.assertNotIn("\x1b", line)

    def test_first_line_is_the_status_summary(self):
        lines = plain.render_block(self.session, DEPARTURES, "", 0)
        self.assertTrue(lines[0].startswith("HKG |"))

    def test_rows_are_paged(self):
        lines = plain.render_block(self.session, DEPARTURES, "", 0, page_size=5)
        rows = [ln for ln in lines if ln.strip() and ln.startswith("  ") and ":" in ln]
        self.assertLessEqual(len(rows), 5)

    def test_all_pages_render(self):
        for page in (DEPARTURES, ARRIVALS, ALERTS, AIRLINES):
            lines = plain.render_block(self.session, page, "", 0)
            self.assertTrue(lines, page)

    def test_no_line_exceeds_the_requested_width(self):
        # The plain adapter prints raw lines: one wider than the terminal wraps
        # and breaks the table apart. Scanned across the whole block because
        # every line in it - header, title and rows - is built from the width.
        for width in (120, 80, 60, 45, 30, 20):
            for page in (DEPARTURES, ARRIVALS, ALERTS, AIRLINES):
                for line in plain.render_block(self.session, page, "", 0, width=width):
                    self.assertLessEqual(
                        views.text_width(line), width, (width, page, line))

    def test_no_line_exceeds_the_width_on_a_two_date_board(self):
        # Across midnight the header grows by " +1" and the board doubles; that
        # is the widest this ever gets, and the narrow terminal is the case
        # that matters.
        session = two_date_session()
        try:
            self.assertIn("2026-09-12 +1",
                          plain.render_block(session, DEPARTURES, "", 0, width=120)[0])
            for width in (120, 60, 45, 30, 20):
                for page in (DEPARTURES, ARRIVALS, ALERTS, AIRLINES):
                    for line in plain.render_block(session, page, "", 0, width=width):
                        self.assertLessEqual(
                            views.text_width(line), width, (width, page, line))
        finally:
            session.close()


class TestPlainHeaderLine(unittest.TestCase):
    """The plain adapter's header, which carries the service-date span."""

    @staticmethod
    def snap(dates, error=None, source="api"):
        flights = {"records_dates": list(dates),
                   "records_date": dates[0] if dates else "",
                   "source": source}
        if error:
            flights["last_error"] = error
        return {"flights": flights, "web": {"status": "off", "error": None, "port": 8080}}

    def test_the_date_span_reaches_the_plain_header(self):
        line = views.plain_header_line(self.snap(["2026-09-12", "2026-09-13"]), 120)
        self.assertTrue(line.startswith("HKG |"))
        self.assertIn("2026-09-12 +1", line)

    def test_it_never_exceeds_the_width(self):
        # The error text is the API's own string and has no length bound, so
        # this is where a header most easily outgrows the terminal.
        for width in (120, 80, 60, 45, 30, 20, 6, 1):
            for dates in (["2026-09-12"], ["2026-09-12", "2026-09-13"]):
                for error in (None, "boom" * 12):
                    line = views.plain_header_line(self.snap(dates, error), width)
                    self.assertLessEqual(
                        views.text_width(line), width, (width, dates, error, line))

    def test_a_degenerate_width_yields_an_empty_line_not_a_wider_one(self):
        for width in (0, -5):
            self.assertEqual(views.plain_header_line(self.snap(["2026-09-12"]), width), "")


class TestRunPlainNonTty(unittest.TestCase):
    def test_prints_snapshot_and_exits_with_result(self):
        session = make_session(raw_payload())
        session.poller.refresh_now()
        out = []
        code = plain.run_plain(session, out=out.append, tty=False)
        self.assertEqual(code, 0)
        joined = "\n".join(out)
        self.assertIn("Result:", joined)
        self.assertIn("Commands:", joined)


class TestRunPlainInteractive(unittest.TestCase):
    def run_commands(self, commands, raw=None):
        session = make_session(raw if raw is not None else raw_payload())
        session.poller.refresh_now()
        out = []
        replies = iter(commands)
        code = plain.run_plain(session, input_func=lambda _p="": next(replies),
                               out=out.append, tty=True)
        return code, out

    def test_quit(self):
        code, out = self.run_commands(["q"])
        self.assertEqual(code, 0)
        self.assertTrue(out)

    def test_page_navigation_and_search(self):
        code, out = self.run_commands(["2", "n", "p", "/ CX1", "q"])
        self.assertEqual(code, 0)
        self.assertTrue(any("Arrivals" in line for line in out))

    def test_alerts_and_airlines_pages(self):
        code, out = self.run_commands(["5", "6", "q"])
        self.assertEqual(code, 0)
        self.assertTrue(any("Alerts" in line for line in out))
        self.assertTrue(any("Airlines" in line for line in out))

    def test_help_and_unknown_command(self):
        code, out = self.run_commands(["help", "bogus", "q"])
        self.assertEqual(code, 0)
        self.assertTrue(any("Unknown command" in line for line in out))

    def test_detail_command(self):
        code, out = self.run_commands(["detail 1", "q"])
        self.assertEqual(code, 0)
        self.assertTrue(any(line.startswith("Flight:") for line in out))

    def test_detail_out_of_range(self):
        code, out = self.run_commands(["detail 999", "q"])
        self.assertTrue(any("No such row" in line for line in out))

    def test_eof_exits_cleanly(self):
        session = make_session(raw_payload())
        session.poller.refresh_now()
        out = []

        def raise_eof(_prompt=""):
            raise EOFError

        code = plain.run_plain(session, input_func=raise_eof, out=out.append, tty=True)
        self.assertEqual(code, 0)

    def test_refresh_and_web_commands_do_not_crash(self):
        code, _ = self.run_commands(["r", "w", "w", "q"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
