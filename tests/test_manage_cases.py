"""CLI behavior through the actual Python entry point."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_case_io import fixture


SCRIPT = Path(__file__).parents[1] / "scripts" / "manage_cases.py"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name)
        self.source = self.base / "source"; self.source.mkdir(); fixture(self.source)
        self.workspace = self.base / "cases"

    def tearDown(self): self.tmp.cleanup()

    def invoke(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=self.base, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(SCRIPT.parents[1] / "src")})

    def test_import_list_inspect_export_reimport_roundtrip(self):
        summary = self.source / "failure-reduction" / "session_summary.json"; before = hashlib.sha256(summary.read_bytes()).hexdigest()
        imported = self.invoke("import-m4", "--source-root", self.source, "--workspace", self.workspace)
        self.assertEqual(imported.returncode, 0, imported.stderr)
        case_id = json.loads(imported.stdout)["case_id"]
        listed = self.invoke("list", "--workspace", self.workspace)
        self.assertEqual([entry["case_id"] for entry in json.loads(listed.stdout)], [case_id])
        inspected = self.invoke("inspect", "--workspace", self.workspace, "--case-id", case_id)
        self.assertEqual(json.loads(inspected.stdout)["case_id"], case_id)
        output = self.base / "portable"
        exported = self.invoke("export", "--workspace", self.workspace, "--case-id", case_id, "--output", output)
        self.assertEqual(exported.returncode, 0, exported.stderr)
        rebound = self.invoke("reimport", "--index", output / "case.json", "--source-root", self.source, "--workspace", self.base / "other")
        self.assertEqual(json.loads(rebound.stdout)["case_id"], case_id)
        self.assertEqual(before, hashlib.sha256(summary.read_bytes()).hexdigest())

    def test_error_is_sanitized_json_and_exit_two(self):
        result = self.invoke("import-m4", "--source-root", self.source, "--workspace", self.workspace, "--summary", "../private.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", json.loads(result.stdout))
        self.assertNotIn(str(self.source), result.stdout)


if __name__ == "__main__": unittest.main()
