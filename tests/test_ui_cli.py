"""`faultline ui` and `faultline-viewer` (the viewer's entry point) and `faultline export` (ADR 0033)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import List
from unittest import mock

from robot_debug import cli
from robot_debug.viewer import server as viewer_server
from tests import ui_fixtures as fx


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


class ExportCommandTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.paths = fx.build(self.base)
        self.app = self.base / "bundle"
        self.app.mkdir()
        (self.app / "index.html").write_text("<!doctype html>", encoding="utf-8")
        self.out = self.base / "gallery"

    def run_export(self, *extra):
        lines: List[str] = []
        code = cli.main(["export", "--out", str(self.out), "--artifacts", str(self.paths["artifacts"]),
                         "--app-root", str(self.app)] + list(extra), out=lines.append)
        return code, lines

    def test_export_writes_the_gallery(self):
        code, lines = self.run_export("--case", "d-" + fx.AUDIT_ID, "--case", fx.PARAPHRASE_ID)
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "Exported 2 case(s) and 0 video(s) to {}".format(self.out))
        listing = json.loads((self.out / "data" / "library.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(i["id"] for i in listing["items"]),
                         sorted(["d-" + fx.AUDIT_ID, "d-" + fx.PARAPHRASE_ID]))
        self.assertTrue((self.out / "vercel.json").is_file())
        self.assertIsNone(listing["items"][0]["run"])

    def test_the_runs_root_defaults_to_runs_beside_the_artifacts(self):
        self.run_export("--case", "d-" + fx.AUDIT_ID)
        path = self.out / "data" / "library" / ("d-" + fx.AUDIT_ID + ".json")
        detail = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(detail["audit"]["nominal"], {"failures": 0, "attempts": 5}, "the audit levels came from the run")

    def test_a_refusal_exits_two_with_a_sentence(self):
        self.out.mkdir()
        (self.out / "x.txt").write_text("x", encoding="utf-8")
        code, lines = self.run_export("--case", "d-" + fx.AUDIT_ID)
        self.assertEqual(code, 2)
        self.assertIn("--force", lines[0])
        code, lines = self.run_export("--force", "--case", "d-" + fx.AUDIT_ID)
        self.assertEqual(code, 0)

    def test_an_unknown_case_exits_two(self):
        code, lines = self.run_export("--case", "d-" + "0" * 64)
        self.assertEqual(code, 2)
        self.assertIn("No single case", lines[0])

    def test_out_is_required(self):
        self.assertEqual(cli.main(["export"], out=lambda line: None), 2)

    def test_the_app_root_option_is_hidden(self):
        parser = cli._parser()._subparsers._group_actions[0].choices["export"]
        self.assertNotIn("app-root", parser.format_help())


if __name__ == "__main__":
    unittest.main()
