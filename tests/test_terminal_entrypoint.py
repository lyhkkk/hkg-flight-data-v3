"""
Entrypoint tests (A1): both start commands route through the same session
assembly, auto backend selection falls back to plain when Textual is missing,
and --ui textual fails loudly instead of silently degrading.
"""

import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from hkg_flight import cli
from hkg_flight.alerts import AlertManager
from hkg_flight.cache import CacheSystem


class TestEntrypointRouting(unittest.TestCase):
    @patch("hkg_flight.cli._run_terminal_ui", return_value=0)
    @patch("hkg_flight.cli.CacheSystem")
    @patch("hkg_flight.cli.AlertManager")
    @patch("hkg_flight.cli.APIClient")
    def test_bare_and_tui_enter_same_session_path(self, api_cls, am_cls, cache_cls, run_ui):
        api_cls.return_value = MagicMock()
        am_cls.return_value = MagicMock()
        cache_cls.return_value = MagicMock()
        self.assertEqual(cli.main([]), 0)
        self.assertEqual(cli.main(["tui", "--no-poll"]), 0)
        self.assertEqual(run_ui.call_count, 2)


class TestBackendSelection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache = CacheSystem(cache_dir=self.temp_dir)
        self.api = MagicMock()
        self.api.fetch_flights.return_value = []
        self.api.fetch_airlines_meta.return_value = {
            "airlines": [], "source": "api", "ok": True, "error": None}
        self.alert_manager = AlertManager(cache=self.cache)
        self.args = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _run(self, ui):
        with patch.object(cli.sys.stdin, "isatty", return_value=False), \
             patch.object(cli.sys.stdout, "isatty", return_value=False):
            return cli._run_terminal_ui(
                self.args, self.cache, self.api, self.alert_manager,
                port=0, no_poll=True, ui=ui)

    @patch("importlib.util.find_spec", return_value=None)
    @patch("hkg_flight.terminal.plain.run_plain", return_value=0)
    def test_auto_uses_plain_when_textual_missing(self, run_plain, _spec):
        code = self._run("auto")
        self.assertEqual(code, 0)
        run_plain.assert_called_once()

    @patch("importlib.util.find_spec", return_value=None)
    def test_textual_required_missing_returns_nonzero(self, _spec):
        code = self._run("textual")
        self.assertEqual(code, 1)

    @patch("importlib.util.find_spec", return_value=None)
    @patch("hkg_flight.terminal.plain.run_plain", return_value=0)
    def test_plain_ui_uses_plain_backend(self, run_plain, _spec):
        code = self._run("plain")
        self.assertEqual(code, 0)
        run_plain.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
