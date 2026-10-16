"""`faultline ui` and `faultline-viewer`, the viewer's entry point (ADR 0033)."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import List
from unittest import mock

from robot_debug import cli
from robot_debug.viewer import server as viewer_server


class FakeGuard:
    def __init__(self, controls=True):
        self.controls = controls


class FakeServer:
    def __init__(self, host="127.0.0.1", port=8765, controls=True):
        self.server_address = (host, port)
        self.api = type("Api", (), {"guard": FakeGuard(controls)})()
        self.catalog = type("Catalog", (), {"snapshot": lambda self: None})()
        self.served = False
        self.closed = False

    def serve_forever(self):
        self.served = True

    def server_close(self):
        self.closed = True


class UiCommandTests(unittest.TestCase):
    def run_ui(self, argv, server=None):
        lines: List[str] = []
        server = server or FakeServer()
        with mock.patch.object(viewer_server, "create_server", return_value=server) as create, \
                mock.patch.object(viewer_server.webbrowser, "open") as opened:
            code = cli.main(["ui"] + argv, out=lines.append)
        return code, lines, create, opened, server

    def test_defaults(self):
        code, lines, create, opened, server = self.run_ui([])
        self.assertEqual(code, 0)
        args, kwargs = create.call_args
        self.assertEqual(args[:3], (Path("artifacts"), "127.0.0.1", 8765))
        self.assertIsNone(kwargs["runs_root"])
        self.assertEqual(lines, ["Faultline Viewer: http://127.0.0.1:8765"])
        self.assertTrue(server.served)
        self.assertTrue(server.closed)
        opened.assert_not_called()

    def test_options_are_passed_through(self):
        code, lines, create, opened, _server = self.run_ui(
            ["--artifacts", "elsewhere", "--runs-root", "elsewhere/runs-x", "--port", "9100", "--host", "localhost",
             "--cases", "cases-x", "--open"], FakeServer("127.0.0.1", 9100))
        args, kwargs = create.call_args
        self.assertEqual(args, (Path("elsewhere"), "localhost", 9100, Path("cases-x")))
        self.assertEqual(kwargs["runs_root"], Path("elsewhere/runs-x"))
        opened.assert_called_once_with("http://127.0.0.1:9100")
        self.assertEqual(lines, ["Faultline Viewer: http://127.0.0.1:9100"])

    def test_a_public_bind_says_controls_are_off(self):
        code, lines, _create, _opened, _server = self.run_ui(["--host", "0.0.0.0"], FakeServer("0.0.0.0", 8765, controls=False))
        self.assertEqual(lines[0], "Faultline Viewer: http://127.0.0.1:8765")
        self.assertIn("Controls are off", lines[1])
        self.assertIn("0.0.0.0", lines[1])

    def test_ctrl_c_stops_the_server_cleanly(self):
        server = FakeServer()
        server.serve_forever = mock.Mock(side_effect=KeyboardInterrupt)
        code, _lines, _create, _opened, _server = self.run_ui([], server)
        self.assertEqual(code, 0)
        self.assertTrue(server.closed)

    def test_the_viewer_entry_point_is_the_same_command(self):
        lines: List[str] = []
        with mock.patch.object(viewer_server, "create_server", return_value=FakeServer()) as create:
            self.assertEqual(viewer_server.main(["--artifacts", "x", "--port", "1234"], out=lines.append), 0)
        self.assertEqual(create.call_args[0][:3], (Path("x"), "127.0.0.1", 1234))

    def test_the_command_is_listed_in_the_help(self):
        self.assertIn("ui", cli._parser().format_help())



if __name__ == "__main__":
    unittest.main()
