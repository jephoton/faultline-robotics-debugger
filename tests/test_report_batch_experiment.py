"""Tests for the local batched-inference report renderer."""

from __future__ import annotations

import ast
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from robot_debug import batch_experiment as be
from scripts import report_batch_experiment as report

ROOT = Path(__file__).resolve().parents[1]


def phase(workers, size, epm, *, share=0.9, mean=None, drift=(), status="complete", timing=True):
    stats = {
        "calls": 100, "items_served": 240, "mean_batch_size": mean if mean is not None else float(size),
        "p95_batch_size": float(size), "max_batch_size_observed": size,
        "inference_ms_p50": 120.0, "inference_ms_p95": 180.0, "wait_ms_p50": 300.0, "wait_ms_p95": 700.0,
        "busy_seconds": 100.0, "model_call_busy_share": share, "malformed_lines": 0,
    }
    return {
        "index": 0, "label": be.phase_label(0, workers, size), "workers": workers, "max_batch_size": size,
        "status": status, "manifest_hash": "h", "planned": 24, "valid_count": 24 if status == "complete" else 5,
        "drift_ids": list(drift), "warm_elapsed_seconds": 24 / epm * 60 if epm else None,
        "episodes_per_minute": epm if status == "complete" else None, "total_seconds": 400.0,
        "timing": stats if timing else None,
    }


def summary_for(phases, parity=None, mode="m3-batch", stop_reason=None):
    planned = [[p["workers"], p["max_batch_size"]] for p in phases]
    return be.build_summary(
        mode=mode, repeats_per_kind=12, planned=planned, phases=phases, parity=parity, stop_reason=stop_reason
    )


class RenderTests(unittest.TestCase):
    def saturated(self):
        return summary_for([
            phase(4, 1, 4.0, share=0.4), phase(8, 1, 5.0, share=0.9), phase(8, 8, 6.5, share=0.7, mean=3.2),
        ])

    def test_report_has_every_section_and_a_verdict_per_worker_count(self) -> None:
        text = report.render_report(self.saturated())
        for heading in ("# M3 batched-inference results", "## Phases", "## Batched against unbatched",
                        "## Verdict per worker count", "## Where the bottleneck sits"):
            self.assertIn(heading, text)
        self.assertIn("- 8 workers: `works`", text)
        self.assertIn("1.300x", text)
        self.assertIn("Worker counts that passed: 8", text)
        self.assertNotIn("**Verdict:**", text, "there is no single overall verdict")
        self.assertIn("phase-01-w08-b08", text)
        self.assertIn("GR00T N1.7 on LIBERO-Object task 0", text)
        self.assertTrue(text.endswith("\n"))

    def test_table_rows_have_the_same_column_count_as_the_header(self) -> None:
        text = report.render_report(self.saturated())
        tables = [[line for line in block.splitlines() if line.startswith("|")] for block in text.split("\n\n")]
        for table in (t for t in tables if t):
            widths = {line.count("|") for line in table}
            self.assertEqual(1, len(widths), table)

    def test_mixed_worker_count_verdicts_are_each_stated(self) -> None:
        phases = [phase(4, 1, 4.0), phase(4, 4, 4.1), phase(8, 1, 5.0), phase(8, 8, 6.5, drift=["mask-03"]),
                  phase(12, 1, 6.0), phase(12, 12, 7.5)]
        text = report.render_report(summary_for(phases))
        self.assertIn("- 4 workers: `no_measurable_gain`", text)
        self.assertIn("- 8 workers: `outcome_drift`", text)
        self.assertIn("mask-03", text)
        self.assertIn("- 12 workers: `works`", text)
        self.assertIn("Worker counts that passed: 12", text)

    def test_no_passing_worker_counts_are_stated_plainly(self) -> None:
        text = report.render_report(summary_for([phase(8, 1, 5.0), phase(8, 8, 5.2)]))
        self.assertIn("Worker counts that passed: none", text)

    def test_saturated_server_is_described_as_the_place_batching_can_help(self) -> None:
        text = report.render_report(self.saturated())
        self.assertIn("close to saturated", text)
        self.assertIn("queueing exceeded the inference time", text)
        self.assertIn("averaged 3.20 requests per model call", text)

    def test_idle_server_points_at_the_simulators(self) -> None:
        text = report.render_report(summary_for([phase(4, 1, 4.0, share=0.3), phase(8, 1, 7.5, share=0.35)]))
        self.assertIn("simulator and evaluator processes", text)
        self.assertIn("still close to linear", text)

    def test_flat_scaling_and_barely_engaged_batching_are_called_out(self) -> None:
        phases = [phase(4, 1, 4.0, share=0.5), phase(12, 1, 4.4, share=0.6), phase(12, 12, 4.5, mean=1.1)]
        text = report.render_report(summary_for(phases))
        self.assertIn("had stopped paying off", text)
        self.assertIn("Batching barely engaged", text)
        self.assertIn("- 12 workers: `no_measurable_gain`", text)

    def test_missing_timing_and_missing_unbatched_phases_degrade_gracefully(self) -> None:
        text = report.render_report(summary_for([phase(8, 1, 5.0, timing=False)]))
        self.assertIn("no server timing", text)
        none = report.render_report(summary_for([phase(8, 8, 5.0)]))
        self.assertIn("no completed unbatched phase", none)

    def test_parity_early_stop_and_prerounding_details_are_stated(self) -> None:
        phases = [phase(8, 1, 5.0), phase(8, 8, 6.5)]
        parity = {"passed": True, "max_abs_diff": 0.012, "tolerance": 0.05, "compared_before_gripper_rounding": True,
                  "per_dim_max_abs_diff": [0.01, 0.0, 0.002, 0.0, 0.0, 0.0, 0.012], "gripper_flips_after_rounding": 3}
        text = report.render_report(summary_for(phases, parity=parity, stop_reason="deadline_exhausted"))
        self.assertIn("Parity: **passed**", text)
        self.assertIn("before the gripper rounding", text)
        self.assertIn("0.012", text)
        self.assertIn("3 gripper flips after rounding (information only", text)
        self.assertIn("Stopped early: `deadline_exhausted`", text)
        failed = report.render_report(summary_for(phases, parity={"passed": False, "max_abs_diff": 0.4,
                                                                  "tolerance": 0.05, "error": None}))
        self.assertIn("Parity: **failed**", failed)
        self.assertIn("Parity gate: `failed`", failed)

    def test_smoke_summary_reports_the_gate(self) -> None:
        smoke = summary_for([phase(4, 4, 6.0, mean=2.5)], parity={"passed": True, "max_abs_diff": 0.01,
                                                                  "tolerance": 0.05}, mode="m3-batch-smoke")
        text = report.render_report(smoke)
        self.assertIn("Smoke gate: **passed**", text)
        self.assertIn("Parity gate: `passed`", text)
        self.assertIn("Worker counts that passed: none", text)

    def test_parity_note_explains_where_it_is_checked_in_a_measurement_job(self) -> None:
        text = report.render_report(self.saturated())
        self.assertIn("Parity: not run in this Job", text)
        self.assertIn("Parity gate: `not_run`", text)

    def test_warmup_prefetch_and_scrub_facts_are_reported(self) -> None:
        summary = summary_for([phase(8, 1, 5.0)])
        summary["warmup"] = {"case_id": "warmup-nominal-01", "status": "valid", "outcome": "success",
                             "duration_seconds": 41.2}
        summary["prefetch_seconds"] = 310.5
        summary["sqlite_companions_removed"] = 2
        text = report.render_report(summary)
        self.assertIn("Warm-up episode `warmup-nominal-01`: valid, success in 41.2 s (excluded from every phase)", text)
        self.assertIn("Prefetch took 310.5 s (not part of any phase)", text)
        self.assertIn("2 stray SQLite companion files were removed", text)


class CommandLineTests(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = report.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_reads_a_summary_file_and_prints_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "batch_summary.json"
            path.write_text(json.dumps(summary_for([phase(8, 1, 5.0), phase(8, 8, 6.0)])), encoding="utf-8")
            code, out, _err = self.run_main([str(path)])
        self.assertEqual(0, code)
        self.assertIn("# M3 batched-inference results", out)

    def test_output_flag_writes_an_lf_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "s.json"
            target = Path(temporary) / "note.md"
            path.write_text(json.dumps(summary_for([phase(8, 1, 5.0)])), encoding="utf-8")
            code, out, _err = self.run_main([str(path), "--output", str(target)])
            data = target.read_bytes()
        self.assertEqual((0, ""), (code, out))
        self.assertNotIn(b"\r\n", data)

    def test_bad_inputs_exit_two_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bad.json").write_text("{", encoding="utf-8")
            (root / "old.json").write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
            (root / "thin.json").write_text(json.dumps({"schema_version": 1, "mode": "m"}), encoding="utf-8")
            (root / "lists.json").write_text(json.dumps(
                {"schema_version": 1, "mode": "m", "phases": {}, "passing_worker_counts": [], "comparisons": []}),
                encoding="utf-8")
            for name in ("missing.json", "bad.json", "old.json", "thin.json", "lists.json"):
                with self.subTest(name=name):
                    code, _out, err = self.run_main([str(root / name)])
                    self.assertEqual(2, code)
                    self.assertIn("report rejected", err)

    def test_script_uses_no_network_and_is_lf_only(self) -> None:
        path = ROOT / "scripts" / "report_batch_experiment.py"
        self.assertNotIn(b"\r\n", path.read_bytes())
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported & {"socket", "urllib", "http", "requests", "subprocess", "robot_debug"})


if __name__ == "__main__":
    unittest.main()
