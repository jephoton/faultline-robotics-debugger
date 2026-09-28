"""Tests for the fail-closed M3 mode-report command."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robot_debug.parallel_eval import build_manifest, manifest_hash


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_parallel_eval.py"
SPEC = importlib.util.spec_from_file_location("run_parallel_eval_report", SCRIPT_PATH)
runner_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner_module
SPEC.loader.exec_module(runner_module)


class M3ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = build_manifest(8)
        self.digest = manifest_hash(self.manifest)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_complete_modes_write_comparison_with_actual_manifest_and_cost_basis(self) -> None:
        paths = [self._write_mode(1, 160), self._write_mode(2, 100), self._write_mode(4, 80)]

        report_path = runner_module.report_mode_summaries(
            paths, hourly_rate_usd=36, billable_seconds={1: 160, 2: 100, 4: 80}, output_dir=self.root
        )

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual(self.digest, payload["manifest_hash"])
        self.assertEqual(16, payload["work_count"])
        self.assertEqual([1, 2, 4], [row["workers"] for row in payload["modes"]])
        self.assertEqual([1.0, 1.6, 2.0], [row["speedup"] for row in payload["modes"]])
        self.assertEqual([1.0, 0.8, 0.5], [row["efficiency"] for row in payload["modes"]])
        self.assertEqual([1.6, 1.0, 0.8], [row["cost_usd"] for row in payload["modes"]])
        self.assertEqual([160.0, 100.0, 80.0], [row["billable_seconds"] for row in payload["modes"]])
        self.assertEqual("hourly_rate_usd * billable_seconds / 3600", payload["cost_rate_basis"])
        self.assertTrue((self.root / "m3_comparison.md").is_file())
        table = (self.root / "m3_comparison.md").read_text(encoding="utf-8")
        self.assertIn("Cost/valid", table)
        self.assertIn("Nominal outcomes", table)
        self.assertIn("success=8, policy_failure=0", table)
        self.assertIn("success=0, policy_failure=8", table)

    def test_report_rejects_pilot_summary_before_computing_comparison_metrics(self) -> None:
        paths = [self._write_mode(1, 160), self._write_mode(2, 100), self._write_mode(4, 80)]
        pilot_path = self._write_mode(2, 10, directory="m3-pilot-workers-2", manifest=build_manifest(1))
        pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
        pilot["purpose"] = "pilot"
        pilot_path.write_text(json.dumps(pilot), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "pilot|benchmark"):
            runner_module.report_mode_summaries([paths[0], pilot_path, paths[2]], output_dir=self.root)

    def test_report_rejects_duplicate_workers_digest_mismatch_and_incomplete_modes(self) -> None:
        paths = [self._write_mode(1, 160), self._write_mode(2, 100), self._write_mode(4, 80)]
        duplicate = self._write_mode(1, 80, directory="duplicate")
        with self.assertRaises(ValueError):
            runner_module.report_mode_summaries([paths[0], paths[1], duplicate], output_dir=self.root)

        mismatched = self._write_mode(4, 80, directory="mismatch", manifest=build_manifest(2))
        with self.assertRaises(ValueError):
            runner_module.report_mode_summaries([paths[0], paths[1], mismatched], output_dir=self.root)

        partial = self._write_mode(4, 80, directory="partial")
        summary = json.loads(partial.read_text(encoding="utf-8"))
        summary["results"].pop()
        summary["valid_count"] -= 1
        partial.write_text(json.dumps(summary), encoding="utf-8")
        with self.assertRaises(ValueError):
            runner_module.report_mode_summaries([paths[0], paths[1], partial], output_dir=self.root)

    def test_report_rejects_completed_resumed_mode_from_throughput_comparison(self) -> None:
        paths = [self._write_mode(1, 160), self._write_mode(2, 100), self._write_mode(4, 80)]
        resumed = json.loads(paths[1].read_text(encoding="utf-8"))
        resumed["resumed"] = True
        paths[1].write_text(json.dumps(resumed), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "resumed"):
            runner_module.report_mode_summaries(paths, output_dir=self.root)

    def test_report_rejects_manifest_file_that_does_not_match_summary_digest(self) -> None:
        paths = [self._write_mode(1, 160), self._write_mode(2, 100), self._write_mode(4, 80)]
        manifest_path = paths[2].parent / "manifest.json"
        manifest_path.write_text(json.dumps(build_manifest(2)), encoding="utf-8")

        with self.assertRaises(ValueError):
            runner_module.report_mode_summaries(paths, output_dir=self.root)

    def test_report_requires_the_exact_frozen_manifest_not_a_self_consistent_alternative(self) -> None:
        alternative = build_manifest(1)
        paths = [
            self._write_mode(1, 160, directory="alternative-1", manifest=alternative),
            self._write_mode(2, 100, directory="alternative-2", manifest=alternative),
            self._write_mode(4, 80, directory="alternative-4", manifest=alternative),
        ]

        with self.assertRaises(ValueError):
            runner_module.report_mode_summaries(paths, output_dir=self.root)

    def test_report_rejects_boolean_substitution_in_frozen_integer_fields(self) -> None:
        alternative = json.loads(json.dumps(self.manifest))
        alternative[0]["task_id"] = False
        paths = [
            self._write_mode(1, 160, directory="boolean-1", manifest=alternative),
            self._write_mode(2, 100, directory="boolean-2", manifest=alternative),
            self._write_mode(4, 80, directory="boolean-4", manifest=alternative),
        ]

        with self.assertRaises(ValueError):
            runner_module.report_mode_summaries(paths, output_dir=self.root)

    def test_report_rejects_results_with_kinds_that_do_not_match_the_frozen_manifest(self) -> None:
        paths = [self._write_mode(1, 160), self._write_mode(2, 100), self._write_mode(4, 80)]
        for path in paths:
            changed = json.loads(path.read_text(encoding="utf-8"))
            for result in changed["results"]:
                result["kind"] = "incorrect-but-consistent"
            path.write_text(json.dumps(changed), encoding="utf-8")

        with self.assertRaises(ValueError):
            runner_module.report_mode_summaries(paths, output_dir=self.root)

    def test_report_refuses_output_colliding_with_input_or_existing_report(self) -> None:
        paths = [self._write_mode(1, 160), self._write_mode(2, 100), self._write_mode(4, 80)]
        existing = self.root / "m3_comparison.json"
        existing.write_text("do not replace", encoding="utf-8")
        with self.assertRaises(ValueError):
            runner_module.report_mode_summaries(paths, output_dir=self.root)
        self.assertEqual("do not replace", existing.read_text(encoding="utf-8"))

        existing.unlink()
        collision = self.root / "m3_comparison.json"
        source = json.loads(paths[0].read_text(encoding="utf-8"))
        (self.root / "manifest.json").write_text(
            (paths[0].parent / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        collision.write_text(json.dumps(source), encoding="utf-8")
        with self.assertRaises(ValueError):
            runner_module.report_mode_summaries([collision, paths[1], paths[2]], output_dir=self.root)
        self.assertEqual(source, json.loads(collision.read_text(encoding="utf-8")))

    def test_report_marks_outcome_drift_and_unavailable_cost(self) -> None:
        paths = [self._write_mode(1, 160), self._write_mode(2, 100), self._write_mode(4, 80)]
        changed = json.loads(paths[2].read_text(encoding="utf-8"))
        next(result for result in changed["results"] if result["case_id"] == "mask-01")["outcome"] = "success"
        paths[2].write_text(json.dumps(changed), encoding="utf-8")

        report_path = runner_module.report_mode_summaries(paths, output_dir=self.root)

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual([None, None, None], [row["cost_usd"] for row in payload["modes"]])
        self.assertEqual("unavailable", payload["cost_rate_basis"])
        self.assertEqual(["mask-01"], payload["modes"][2]["drift_case_ids"])

    def test_cost_inputs_are_all_or_none_and_validate_rate_and_each_worker_seconds(self) -> None:
        paths = [self._write_mode(1, 160), self._write_mode(2, 100), self._write_mode(4, 80)]
        invalid_inputs = [
            {"hourly_rate_usd": 1, "billable_seconds": None},
            {"hourly_rate_usd": None, "billable_seconds": {1: 1, 2: 1, 4: 1}},
            {"hourly_rate_usd": math.inf, "billable_seconds": {1: 1, 2: 1, 4: 1}},
            {"hourly_rate_usd": -1, "billable_seconds": {1: 1, 2: 1, 4: 1}},
            {"hourly_rate_usd": 1, "billable_seconds": {1: 1, 2: 1}},
            {"hourly_rate_usd": 1, "billable_seconds": {1: 1, 2: 1, 4: 0}},
        ]
        for arguments in invalid_inputs:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    runner_module.report_mode_summaries(paths, output_dir=self.root, **arguments)

    def test_report_cli_requires_complete_cost_flags_and_writes_to_requested_directory(self) -> None:
        paths = [self._write_mode(1, 160), self._write_mode(2, 100), self._write_mode(4, 80)]
        argv = ["run_parallel_eval.py", "report"] + [
            value for path in paths for value in ("--mode-summary", str(path))
        ] + ["--output-dir", str(self.root), "--hourly-rate-usd", "36",
             "--billable-seconds", "1=160", "--billable-seconds", "2=100", "--billable-seconds", "4=80"]
        output = io.StringIO()
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
            runner_module.main()
        self.assertTrue((self.root / "m3_comparison.json").is_file())
        self.assertIn("m3_comparison.json", output.getvalue())

    def _write_mode(self, workers: int, elapsed_seconds: float, *, directory: str | None = None,
                    manifest: list[dict] | None = None) -> Path:
        mode_manifest = manifest if manifest is not None else self.manifest
        directory = directory or f"m3-workers-{workers}"
        session = self.root / directory
        session.mkdir()
        digest = manifest_hash(mode_manifest)
        (session / "manifest.json").write_text(
            json.dumps(mode_manifest, sort_keys=True, separators=(",", ":"), allow_nan=False), encoding="utf-8"
        )
        summary = {
            "workers": workers,
            "manifest_hash": digest,
            "manifest_path": "manifest.json",
            "case_ids": [item["case_id"] for item in mode_manifest],
            "planned_ids": [item["case_id"] for item in mode_manifest],
            "elapsed_seconds": elapsed_seconds,
            "valid_count": len(mode_manifest),
            "stop_reason": None,
            "results": [
                {"case_id": item["case_id"], "kind": item["kind"], "status": "valid",
                 "outcome": "success" if item["kind"] == "nominal" else "policy_failure"}
                for item in mode_manifest
            ],
        }
        path = session / "session_summary.json"
        path.write_text(json.dumps(summary), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
