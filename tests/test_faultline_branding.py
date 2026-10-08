import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

import robot_debug.viewer as viewer
import robot_debug.viewer.server as viewer_server
from robot_debug.viewer.catalog import ArtifactCatalog
from robot_debug.viewer.server import make_handler


class FaultlineBrandingTests(unittest.TestCase):
    def test_homepage_uses_faultline_title_and_heading(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            web_root = (
                Path(__file__).resolve().parents[1]
                / "src"
                / "robot_debug"
                / "viewer"
                / "web"
            )
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), make_handler(ArtifactCatalog(root), web_root)
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen("http://127.0.0.1:{}/".format(server.server_port)) as response:
                    page = response.read().decode("utf-8")
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

        self.assertIn("<title>Faultline</title>", page)
        self.assertIn("<h1>Faultline</h1>", page)
        self.assertNotIn("Robot Debug Console", page)

    def test_distribution_and_console_scripts_use_faultline_brand(self):
        pyproject = (
            Path(__file__).resolve().parents[1] / "pyproject.toml"
        ).read_text(encoding="utf-8")

        self.assertIn('name = "faultline"', pyproject)
        self.assertIn(
            'faultline-viewer = "robot_debug.viewer.server:main"', pyproject
        )
        self.assertIn(
            'robot-debug-viewer = "robot_debug.viewer.server:main"', pyproject
        )

    def test_viewer_module_descriptions_use_faultline_brand(self):
        self.assertIn("Faultline", viewer.__doc__)
        self.assertIn("Faultline", viewer_server.__doc__)

    def test_main_announces_faultline_viewer_url(self):
        class FakeServer:
            server_address = ("127.0.0.1", 4321)

            def serve_forever(self):
                raise KeyboardInterrupt

            def server_close(self):
                pass

        with patch.object(viewer_server, "create_server", return_value=FakeServer()), patch(
            "builtins.print"
        ) as print_mock:
            result = viewer_server.main([])

        self.assertEqual(result, 0)
        print_mock.assert_called_once_with("Faultline Viewer: http://127.0.0.1:4321")


if __name__ == "__main__":
    unittest.main()
