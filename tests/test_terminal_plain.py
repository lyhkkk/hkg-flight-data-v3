"""
Tests for the plain adapter: line commands, search reuse, detail, non-TTY
snapshot and non-zero exit on failure.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from hkg_flight.cache import CacheSystem
from hkg_flight.alerts import AlertManager
from hkg_flight.terminal.session import Session
from hkg_flight.terminal import plain
from hkg_flight.terminal.presenter import DEPARTURES
from tests.fixtures.terminal.data import make_flights


def make_raw(records):
    """Convert normalized records back to raw API payload."""
    entries = []
    for rec in records:
        is_arrival = rec.get("type") == "arrival"
        origin = rec.get("origin", "").split("|") if rec.get("origin") else []
        destination = rec.get("destination", "").split("|") if rec.get("destination") else []
        entry = {
            "arrival": is_arrival,
            "cargo": False,
            "date": rec.get("date", ""),
            "list": [{
                "flight": [{"airline": rec.get("airline_code", ""), "no": rec.get("flight_number", "")}],
                "time": rec.get("time", ""),
                "status": rec.get("status", ""),
                "origin": origin,
                "destination": destination,
                "terminal": rec.get("terminal", ""),
                "gate": rec.get("gate", ""),
                "stand": rec.get("stand", ""),
                "aisle": rec.get("aisle", ""),
                "hall": rec.get("hall", ""),
                "baggage": rec.get("belt", ""),
            }],
        }
        entries.append(entry)
    return entries


def build_session(flights=None, airlines=None, api_error=None):
    """Session whose API succeeded with ``flights`` (or raised ``api_error``)."""
    temp_dir = tempfile.mkdtemp()
    cache = CacheSystem(cache_dir=temp_dir)
    api = MagicMock()
    if api_error is not None:
        api.fetch_flights.side_effect = api_error
    else:
        api.fetch_flights.return_value = make_raw(flights or [])
    api.fetch_airlines_meta.return_value = {
        "airlines": airlines or [], "source": "api", "ok": True, "error": None}
    alert_manager = AlertManager(cache=cache)
    session = Session(cache=cache, api=api, alert_manager=alert_manager, no_poll=True)
    session.poller.refresh_today()
    return session, temp_dir


def run_non_tty(session, page_size=plain.DEFAULT_PAGE_SIZE):
    lines = []
    code = plain.run_plain(session, input_func=lambda prompt: "",
                           out=lines.append, tty=False, page_size=page_size)
    return code, lines


def run_tty(session, commands, page_size=plain.DEFAULT_PAGE_SIZE):
    lines = []
    inputs = iter(commands)
    code = plain.run_plain(session, input_func=lambda prompt: next(inputs),
                           out=lines.append, tty=True, page_size=page_size)
    return code, lines


class TestPlainAdapter(unittest.TestCase):
    def test_non_tty_prints_snapshot_and_exits(self):
        session, temp_dir = build_session(flights=make_flights(8))
        try:
            lines = []
            code = plain.run_plain(session, input_func=lambda prompt: "",
                                   out=lines.append, tty=False)
            self.assertEqual(code, 0)
            self.assertTrue(any("CX" in line for line in lines))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_non_tty_failure_returns_nonzero(self):
        # A real failure: the API raised and there is no cache to fall back to.
        session, temp_dir = build_session(api_error=RuntimeError("api_failed"))
        try:
            code, lines = run_non_tty(session)
            self.assertEqual(code, 1)
            self.assertTrue(any("ERROR (api_failed)" in line for line in lines), lines)
        finally:
            session.close()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_tty_commands_switch_pages_and_quit(self):
        session, temp_dir = build_session(flights=make_flights(12))
        try:
            lines = []
            inputs = iter(["2", "5", "1", "q"])
            plain.run_plain(session, input_func=lambda prompt: next(inputs),
                            out=lines.append, tty=True)
            joined = "\n".join(lines)
            self.assertIn("Arrivals", joined)
            self.assertIn("ACTIVE ALERTS", joined)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_search_reuses_whitelist_rules(self):
        session, temp_dir = build_session(flights=make_flights(30))
        try:
            lines = []
            inputs = iter(["/ CX 100", "q"])
            plain.run_plain(session, input_func=lambda prompt: next(inputs),
                            out=lines.append, tty=True)
            joined = "\n".join(lines)
            self.assertIn("Matches", joined)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_detail_prints_lines(self):
        session, temp_dir = build_session(flights=make_flights(5))
        try:
            lines = []
            inputs = iter(["detail 1", "q"])
            plain.run_plain(session, input_func=lambda prompt: next(inputs),
                            out=lines.append, tty=True)
            joined = "\n".join(lines)
            self.assertIn("Flight:", joined)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPlainEmptySuccess(unittest.TestCase):
    """R06: an API ``[]`` is a successful empty result, not a failure."""

    def test_empty_api_success_exits_zero(self):
        session, temp_dir = build_session(flights=[])
        try:
            code, lines = run_non_tty(session)
            self.assertEqual(code, 0)
            self.assertTrue(
                any("OK (api returned no flights)" in line for line in lines), lines)
        finally:
            session.close()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_failure_still_exits_nonzero(self):
        session, temp_dir = build_session(api_error=RuntimeError("boom"))
        try:
            code, _ = run_non_tty(session)
            self.assertEqual(code, 1)
        finally:
            session.close()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_empty_success_and_failure_labels_differ(self):
        ok_session, ok_dir = build_session(flights=[])
        bad_session, bad_dir = build_session(api_error=RuntimeError("boom"))
        try:
            ok_code, ok_lines = run_non_tty(ok_session)
            bad_code, bad_lines = run_non_tty(bad_session)
            self.assertEqual((ok_code, bad_code), (0, 1))
            ok_label = [line for line in ok_lines if line.startswith("Result: ")][-1]
            bad_label = [line for line in bad_lines if line.startswith("Result: ")][-1]
            self.assertNotEqual(ok_label, bad_label)
            self.assertIn("OK", ok_label)
            self.assertIn("ERROR", bad_label)
        finally:
            for session, directory in ((ok_session, ok_dir), (bad_session, bad_dir)):
                session.close()
                shutil.rmtree(directory, ignore_errors=True)

    def test_non_tty_output_is_bounded(self):
        session, temp_dir = build_session(flights=make_flights(200))
        try:
            code, lines = run_non_tty(session, page_size=10)
            self.assertEqual(code, 0)
            # 3 chrome lines + page_size rows + Result + Commands.
            self.assertLessEqual(len(lines), 10 + 5)
        finally:
            session.close()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_status_line_reports_manual_when_polling_off(self):
        session, temp_dir = build_session(flights=make_flights(2))
        try:
            lines = plain.render_block(session, DEPARTURES, "", 0)
            self.assertIn("MANUAL", lines[0], lines[0])
        finally:
            session.close()
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPlainOutputSafety(unittest.TestCase):
    """External data must not smuggle escape or control codes into a pipe."""

    DIRTY = "OK\x1b[31mRED\x07\x9bEND"

    def _dirty_session(self):
        flights = make_flights(3)
        flights[0]["status"] = self.DIRTY
        return build_session(flights=flights)

    def test_control_characters_are_stripped(self):
        session, temp_dir = self._dirty_session()
        try:
            _, lines = run_non_tty(session)
            joined = "\n".join(lines)
            for bad in ("\x1b", "\x07", "\x9b"):
                self.assertNotIn(bad, joined)
        finally:
            session.close()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_ansi_parameters_do_not_leak(self):
        session, temp_dir = self._dirty_session()
        try:
            _, lines = run_non_tty(session)
            joined = "\n".join(lines)
            self.assertNotIn("[31m", joined)
        finally:
            session.close()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_no_color_output_carries_the_same_information(self):
        session, temp_dir = self._dirty_session()
        previous = os.environ.get("NO_COLOR")
        os.environ["NO_COLOR"] = "1"
        try:
            code, lines = run_non_tty(session)
            joined = "\n".join(lines)
            self.assertEqual(code, 0)
            self.assertNotIn("\x1b", joined)
            self.assertIn("Result: OK", joined)
            self.assertIn("Departures", joined)
        finally:
            if previous is None:
                os.environ.pop("NO_COLOR", None)
            else:
                os.environ["NO_COLOR"] = previous
            session.close()
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPlainBoundedExit(unittest.TestCase):
    """EOF / Ctrl-C / exhausted input must end the loop, never hang."""

    def _session(self):
        return build_session(flights=make_flights(4))

    def _run(self, raiser):
        session, temp_dir = self._session()
        try:
            lines = []
            code = plain.run_plain(session, input_func=raiser,
                                   out=lines.append, tty=True)
            self.assertEqual(code, 0)
            # The TTY loop owns the session and closes it on every exit path.
            self.assertEqual(session.poller.request_refresh(), "closed")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_eof_exits_zero(self):
        def raise_eof(_prompt):
            raise EOFError
        self._run(raise_eof)

    def test_keyboard_interrupt_exits_zero(self):
        def raise_ctrl_c(_prompt):
            raise KeyboardInterrupt
        self._run(raise_ctrl_c)

    def test_exhausted_input_exits_zero(self):
        # An exhausted iterator raises StopIteration, which must be treated
        # exactly like EOF instead of escaping to the caller.
        self._run(lambda _prompt: next(iter([])))

    def test_none_input_exits_zero(self):
        self._run(lambda _prompt: None)


class TestPlainPaging(unittest.TestCase):
    """Detail offset, n/p bounds and bounded pagination."""

    def test_clamp_offset_lands_on_last_page_start(self):
        self.assertEqual(plain.clamp_offset(0, 6, 2), 0)
        self.assertEqual(plain.clamp_offset(2, 6, 2), 2)
        self.assertEqual(plain.clamp_offset(4, 6, 2), 4)
        self.assertEqual(plain.clamp_offset(6, 6, 2), 4)   # clamped
        self.assertEqual(plain.clamp_offset(999, 6, 2), 4)
        self.assertEqual(plain.clamp_offset(-2, 6, 2), 0)
        self.assertEqual(plain.clamp_offset(5, 0, 2), 0)   # no rows

    def _last_block(self, lines):
        starts = [i for i, line in enumerate(lines) if line.startswith("HKG | ")]
        return lines[starts[-1]:]

    def test_next_page_clamps_at_last_page(self):
        session, temp_dir = build_session(flights=make_flights(12))
        try:
            rows = session.rows_for(DEPARTURES)
            self.assertEqual(len(rows), 6)
            _, lines = run_tty(session, ["n", "n", "n", "n", "q"], page_size=2)
            block = self._last_block(lines)
            joined = "\n".join(block)
            # Last page starts at row index 4 and must not be empty.
            self.assertIn(rows[4]["record"]["flight_number"], joined)
            self.assertIn(rows[5]["record"]["flight_number"], joined)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prev_page_never_goes_below_zero(self):
        session, temp_dir = build_session(flights=make_flights(12))
        try:
            rows = session.rows_for(DEPARTURES)
            _, lines = run_tty(session, ["p", "p", "q"], page_size=2)
            joined = "\n".join(self._last_block(lines))
            self.assertIn(rows[0]["record"]["flight_number"], joined)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_detail_is_relative_to_current_offset(self):
        session, temp_dir = build_session(flights=make_flights(12))
        try:
            rows = session.rows_for(DEPARTURES)
            _, lines = run_tty(session, ["n", "detail 1", "q"], page_size=2)
            joined = "\n".join(lines)
            # After one page-down the first row on screen is absolute row 2.
            self.assertIn("Flight: {}".format(rows[2]["record"]["flight_number"]), joined)
            self.assertNotIn("Flight: {}".format(rows[0]["record"]["flight_number"]), joined)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_detail_out_of_range_reports_the_visible_range(self):
        session, temp_dir = build_session(flights=make_flights(12))
        try:
            _, lines = run_tty(session, ["detail 99", "q"])
            joined = "\n".join(lines)
            self.assertIn("No such row", joined)
            self.assertIn("rows 1-6", joined)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
