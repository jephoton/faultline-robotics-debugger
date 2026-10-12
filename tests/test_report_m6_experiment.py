"""Tests for the local M6 report renderer."""

from __future__ import annotations

import ast
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from robot_debug import m6_experiment as m6
from scripts import report_m6_experiment as report
from tests.test_m6_experiment import (
    BOUNDARIES,
    THRESHOLD_CONFIG,
    M6World,
    ProbingWorld,
    RunTestCase,
    boundary_decide,
    smoke_decide,
)

ROOT = Path(__file__).resolve().parents[1]


class RenderTests(RunTestCase):
    def smoke_summary(self, decide=smoke_decide):
        return self.run_m6(M6World(decide), "m6-smoke")

    def threshold_summary(self, **kwargs):
        world = kwargs.pop("world", None) or M6World(boundary_decide(BOUNDARIES))
        return self.run_m6(world, "m6-threshold", dict(THRESHOLD_CONFIG), **kwargs)

    def test_smoke_report_has_the_wrist_table_and_family_spot_checks(self):
        text = report.render_report([self.smoke_summary()])

        self.assertIn("## Wrist-camera conditions (smoke Job)", text)
        self.assertIn("| Nominal control (no perturbation) | 6 | 6 | 0 | 0 |", text)
        self.assertIn("| Reduced agent-view mask + wrist image black | 12 | 0 | 12 | 0 |", text)
        self.assertIn("| Same rectangle on the wrist image only | 12 | 12 | 0 | 0 |", text)
        self.assertIn("## Scalar families at one severity (smoke Job)", text)
        self.assertIn("| Darkening | 0.6 | brightness x0.43 | 0 | 2 |", text)
        self.assertIn("| Gaussian blur | 0.6 | blur sigma 4.80 px | 2 | 0 |", text)
        self.assertIn("All 6 nominal runs succeeded", text)
        self.assertIn("failed in all 12 completed runs", text)
        self.assertIn("succeeded in all 12 completed runs", text)
        self.assertIn("do not by themselves show which camera", text)
        self.assertIn("episodes/min", text)

    def test_threshold_report_has_the_table_levels_and_reading(self):
        text = report.render_report([self.threshold_summary()])

        self.assertIn("## Threshold search per family (main Job)", text)
        self.assertIn("| Darkening | 0.35 | brightness x0.67 | 0.3375 | 6 | 30 | threshold found |", text)
        self.assertIn("| Gaussian noise | 0.55 | noise sigma 55.0 of 255 | 0.5375 | 7 | 35 | threshold found |", text)
        self.assertIn("| Gaussian blur | none up to 1.0 | - | 1 | 5 | 25 | no reproducible failure up to s = 1.0 |", text)
        self.assertIn("| Contrast reduction | 0.05 | contrast x0.95 | 0.0375 | 5 | 25 | threshold found |", text)
        self.assertIn("0.2: 0/5; 0.4: 5/5; 0.3: 0/5; 0.35: 5/5; 0.325: 0/5; 0.3375: 0/5", text)
        self.assertIn("boundary under this rule lies in (0.3375, 0.35]", text)
        self.assertIn("robust to this family in the tested range", text)
        self.assertIn("Nominal controls: 5 of 5 succeeded", text)
        self.assertIn("4 of 5", text)
        self.assertIn("not the onset of any failure", text)

    def test_threshold_rows_follow_the_configured_family_order(self):
        text = report.render_report([self.threshold_summary()])
        order = [text.index("| {} |".format(label)) for label in (
            "Darkening", "Gaussian noise", "Gaussian blur", "Contrast reduction")]
        self.assertEqual(sorted(order), order)

    def test_wrist_reading_states_what_each_outcome_means_here(self):
        text = report.render_report([self.smoke_summary()])
        self.assertIn("(both cameras were degraded in these runs)", text)
        self.assertIn("(this wrist rectangle alone did not cause failure here)", text)

        def decide(case, kwargs):
            if case.startswith("wrist-mask-only"):
                return "policy_failure"
            if case.startswith("agentview-mask-wrist-black"):
                return "success"
            return smoke_decide(case, kwargs)

        text = report.render_report([self.smoke_summary(decide)])
        self.assertIn("(this wrist rectangle alone was enough to cause failure here)", text)
        self.assertIn("(the policy completed the task even with the wrist image black)", text)

    def test_both_summaries_in_one_report(self):
        text = report.render_report([self.smoke_summary(), self.threshold_summary()])
        self.assertLess(text.index("Wrist-camera conditions"), text.index("Threshold search per family"))
        self.assertEqual(1, text.count("# M6 results"))

    def test_failed_nominal_controls_are_called_out_loudly(self):
        def decide(case, kwargs):
            return "policy_failure" if case == "nominal-02" else smoke_decide(case, kwargs)

        text = report.render_report([self.smoke_summary(decide)])
        self.assertIn("**The nominal controls did not all succeed (5 successes, 1 failures, 0 not completed)", text)

        world = M6World(lambda case, kwargs: "policy_failure" if case == "nominal-control-01" else "success")
        text = report.render_report([self.threshold_summary(world=world)])
        self.assertIn("Stopped early: `nominal_controls_failed`", text)
        self.assertIn("not run: nominal controls failed", text)
        self.assertIn("not evaluated, the nominal controls did not all succeed", text)
        self.assertIn("Nominal controls: 4 of 5 succeeded", text)

    def test_partial_runs_are_reported_as_incomplete_with_the_coarse_level(self):
        world = M6World(boundary_decide(BOUNDARIES), item_seconds=0.01)
        summary = self.run_m6(world, "m6-threshold", dict(THRESHOLD_CONFIG),
                              remaining=lambda: 1000.0 if len(world.ran) < 40 else 10.0)
        text = report.render_report([summary])
        self.assertIn("Stopped early: `deadline_exhausted`", text)
        self.assertIn("incomplete (Job deadline reached)", text)
        self.assertIn("Items that never started:", text)

    def test_incomplete_conditions_show_not_completed_counts(self):
        world = M6World(smoke_decide, fail_case="wrist-mask-only-03", item_seconds=0.03)
        summary = self.run_m6(world, "m6-smoke")
        text = report.render_report([summary])
        self.assertIn("Stopped early: `evaluator_failed`", text)
        self.assertRegex(text, r"\| Same rectangle on the wrist image only \| 12 \| \d+ \| \d+ \| [1-9]\d* \|")

    def test_mixed_wrist_results_are_described_with_counts(self):
        def decide(case, kwargs):
            if case.startswith("wrist-mask-only") and int(case[-2:]) <= 5:
                return "policy_failure"
            return smoke_decide(case, kwargs)

        text = report.render_report([self.smoke_summary(decide)])
        self.assertIn("failed in 5 of 12 completed runs", text)

    def test_physical_text_formats_each_family_and_tolerates_gaps(self):
        self.assertEqual("brightness x0.43", report.physical_text({"name": "brightness_factor", "value": 0.43}))
        self.assertEqual("noise sigma 60.0 of 255", report.physical_text({"name": "noise_sigma", "value": 60.0}))
        self.assertEqual("blur sigma 4.80 px", report.physical_text({"name": "blur_sigma_px", "value": 4.8}))
        self.assertEqual("contrast x0.46", report.physical_text({"name": "contrast_factor", "value": 0.46}))
        for bad in (None, {}, {"name": "other", "value": 1}, {"name": "noise_sigma", "value": "x"}):
            self.assertEqual("-", report.physical_text(bad))


class CameraEffectReportTests(RunTestCase):
    def test_smoke_tables_show_the_camera_ratios(self):
        summary = self.run_m6(ProbingWorld(smoke_decide), "m6-smoke")
        text = report.render_report([summary])

        self.assertIn("Agent view mean / std ratio | Wrist mean / std ratio", text)
        self.assertIn("| Same rectangle on the wrist image only | 12 | 12 | 0 | 0 | 0.0 | 1.00 / 1.00 | 0.50 / 0.75 |", text)
        self.assertIn("| Nominal control (no perturbation) | 6 | 6 | 0 | 0 | 0.0 | - | - |", text)
        self.assertRegex(text, r"\| Darkening \| 0\.6 \| brightness x0\.43 \| 0 \| 2 \| 0\.0 \| 0\.70 / 0\.85 \| 0\.70 / 0\.85 \|")

    def test_camera_check_says_which_cameras_changed(self):
        summary = self.run_m6(ProbingWorld(smoke_decide), "m6-smoke")
        text = report.render_report([summary])

        self.assertIn("## Camera-effect check (per-camera probe)", text)
        self.assertIn("Same rectangle on the wrist image only: policy input changed on wrist; unchanged on agent view.", text)
        self.assertIn("Reduced agent-view mask + wrist image black: policy input changed on agent view and wrist.", text)
        self.assertIn("Darkening at s = 0.6: policy input changed on agent view and wrist.", text)
        self.assertNotIn("fix before the main Job", text)

    def test_a_scalar_family_that_leaves_a_camera_unchanged_is_flagged(self):
        summary = self.run_m6(ProbingWorld(smoke_decide), "m6-smoke")
        summary["conditions"]["blur_0.6"]["camera_effect"]["wrist"] = {
            "mean_ratio": 1.0, "std_ratio": 1.004, "samples": 4}
        text = report.render_report([summary])
        self.assertIn("Gaussian blur at s = 0.6: policy input changed on agent view; unchanged on wrist. "
                      "**A scalar family should change both cameras; fix before the main Job**.", text)

    def test_missing_probe_data_is_stated(self):
        summary = self.run_m6(M6World(smoke_decide), "m6-smoke")
        text = report.render_report([summary])
        self.assertIn("Same rectangle on the wrist image only: no probe data.", text)
        self.assertIn("Darkening at s = 0.6: no probe data.", text)

    def test_noise_counts_as_changed_through_the_std_ratio(self):
        self.assertTrue(report.camera_changed({"wrist": {"mean_ratio": 1.0, "std_ratio": 1.6}}, "wrist"))
        self.assertFalse(report.camera_changed({"wrist": {"mean_ratio": 1.005, "std_ratio": 0.995}}, "wrist"))
        self.assertIsNone(report.camera_changed({"wrist": {}}, "wrist"))
        self.assertIsNone(report.camera_changed(None, "wrist"))

    def test_threshold_table_shows_the_effect_at_the_threshold_level(self):
        world = ProbingWorld(boundary_decide(BOUNDARIES))
        summary = self.run_m6(world, "m6-threshold", dict(THRESHOLD_CONFIG))
        text = report.render_report([summary])

        self.assertIn("Agent view mean / std ratio at threshold | Wrist mean / std ratio at threshold", text)
        expected = report.effect_text(summary["families"]["darken"]["threshold_camera_effect"], "wrist")
        self.assertNotEqual("-", expected)
        darken_row = [line for line in text.splitlines() if line.startswith("| Darkening | 0.35 |")][0]
        self.assertTrue(darken_row.endswith("| {} | {} |".format(expected, expected)))
        blur_row = [line for line in text.splitlines() if line.startswith("| Gaussian blur |")][0]
        self.assertTrue(blur_row.endswith("| - | - |"))


class CommandLineTests(unittest.TestCase):
    def write(self, directory, name, data):
        path = Path(directory) / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def minimal(self, **changes):
        data = {"schema_version": 1, "mode": "m6-smoke", "conditions": {}, "families": {}}
        data.update(changes)
        return data

    def test_rejects_unreadable_or_foreign_summaries(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = {
                "missing.json": None,
                "list.json": [],
                "schema.json": self.minimal(schema_version=2),
                "mode.json": self.minimal(mode="m3-batch"),
                "conditions.json": self.minimal(conditions=[]),
                "threshold-config.json": self.minimal(mode="m6-threshold"),
            }
            for name, data in bad.items():
                path = Path(directory) / name
                if data is not None:
                    path.write_text(json.dumps(data), encoding="utf-8")
                with self.subTest(name=name), self.assertRaises(report.ReportError):
                    report.load_summary(path)
            (Path(directory) / "garbage.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(report.ReportError):
                report.load_summary(Path(directory) / "garbage.json")

    def test_cli_writes_a_file_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write(directory, "m6_summary.json", self.minimal(conditions={
                "nominal": {"planned": 6, "valid": 6, "outcomes": {"success": 6}, "median_duration_seconds": 7.0}}))
            output = Path(directory) / "report.md"
            self.assertEqual(0, report.main([str(source), "--output", str(output)]))
            data = output.read_bytes()
            self.assertIn(b"# M6 results", data)
            self.assertNotIn(b"\r\n", data)

    def test_cli_prints_to_standard_output_and_rejects_with_status_two(self):
        with tempfile.TemporaryDirectory() as directory:
            good = self.write(directory, "ok.json", self.minimal())
            bad = self.write(directory, "bad.json", {"schema_version": 3})
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.assertEqual(0, report.main([str(good)]))
            self.assertIn("# M6 results", buffer.getvalue())
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                self.assertEqual(2, report.main([str(bad)]))
            self.assertIn("report rejected", errors.getvalue())

    def test_script_syntax_is_python_38_compatible(self):
        path = ROOT / "scripts" / "report_m6_experiment.py"
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 8))


if __name__ == "__main__":
    unittest.main()
