"""CLI entry point: backend selection, argument parsing, resource cleanup."""

import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

from hkg_flight import cli
from hkg_flight.alerts import AlertManager
from hkg_flight.cache import CacheSystem
from hkg_flight.terminal import plain  # noqa: F401  (importable so it can be patched)


class FakeAPI:
    def fetch_flights(self, date_str):
        return []

    def fetch_airlines_meta(self):
        return {"airlines": [], "source": "api", "ok": True, "error": None}


class TestParser(unittest.TestCase):
    def test_subcommands_are_registered(self):
        parser = cli.create_parser()
        for argv, command in (
            (["query", "CX759"], "query"),
            (["departures"], "departures"),
            (["arrivals"], "arrivals"),
            (["alerts"], "alerts"),
            (["clear-cache"], "clear-cache"),
            (["web"], "web"),
            (["tui"], "tui"),
        ):
            self.assertEqual(parser.parse_args(argv).command, command, argv)

    def test_no_subcommand_defaults_to_none(self):
        self.assertIsNone(cli.create_parser().parse_args([]).command)

    def test_query_options(self):
        args = cli.create_parser().parse_args(["query", "CX759", "2026-09-11", "--details", "--codeshare"])
        self.assertEqual(args.flight, "CX759")
        self.assertEqual(args.date, "2026-09-11")
        self.assertTrue(args.details)
        self.assertTrue(args.codeshare)

    def test_ui_choices_are_validated(self):
        with self.assertRaises(SystemExit):
            cli.create_parser().parse_args(["tui", "--ui", "bogus"])


class TestBackendSelection(unittest.TestCase):
    def _run(self, ui, textual_available, interactive):
        """Run _run_terminal_ui with a stubbed environment; return (code, backend)."""
        cache = CacheSystem(tempfile.mkdtemp())
        # textual_app is imported lazily inside the CLI, so inject a stub module.
        fake_textual = types.ModuleType("hkg_flight.terminal.textual_app")
        textual_mock = MagicMock(return_value=None)
        fake_textual.run_textual = textual_mock

        with patch("importlib.util.find_spec",
                   return_value=object() if textual_available else None), \
                patch.object(sys.stdin, "isatty", return_value=interactive), \
                patch.object(sys.stdout, "isatty", return_value=interactive), \
                patch("hkg_flight.terminal.plain.run_plain", return_value=0) as plain_mock, \
                patch.dict(sys.modules, {"hkg_flight.terminal.textual_app": fake_textual}):
            code = cli._run_terminal_ui(cache, FakeAPI(), AlertManager(cache),
                                        port=18099, no_poll=True, ui=ui)
        backend = "textual" if textual_mock.called else ("plain" if plain_mock.called else None)
        return code, backend

    def test_explicit_plain_always_uses_plain(self):
        self.assertEqual(self._run("plain", True, True), (0, "plain"))

    def test_explicit_textual_requires_install(self):
        code, backend = self._run("textual", False, True)
        self.assertEqual(code, 1)
        self.assertIsNone(backend)

    def test_explicit_textual_requires_interactive_terminal(self):
        code, _ = self._run("textual", True, False)
        self.assertEqual(code, 1)

    def test_explicit_textual_runs_when_available(self):
        self.assertEqual(self._run("textual", True, True), (0, "textual"))

    def test_auto_prefers_textual_when_available(self):
        self.assertEqual(self._run("auto", True, True), (0, "textual"))

    def test_auto_falls_back_to_plain_without_textual(self):
        self.assertEqual(self._run("auto", False, True), (0, "plain"))

    def test_auto_falls_back_to_plain_without_tty(self):
        self.assertEqual(self._run("auto", True, False), (0, "plain"))

    def test_session_is_closed_even_if_the_backend_raises(self):
        cache = CacheSystem(tempfile.mkdtemp())
        closed = {}
        from hkg_flight.terminal.session import Session as RealSession

        original = RealSession.close

        def spy(self):
            closed["yes"] = True
            return original(self)

        with patch("hkg_flight.terminal.plain.run_plain", side_effect=RuntimeError("boom")), \
                patch("importlib.util.find_spec", return_value=None), \
                patch.object(sys.stdin, "isatty", return_value=True), \
                patch.object(sys.stdout, "isatty", return_value=True), \
                patch.object(RealSession, "close", spy):
            with self.assertRaises(RuntimeError):
                cli._run_terminal_ui(cache, FakeAPI(), AlertManager(cache),
                                     port=18099, no_poll=True, ui="plain")
        self.assertTrue(closed.get("yes"), "session.close() must run on the error path")


if __name__ == "__main__":
    unittest.main()
