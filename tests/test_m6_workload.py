"""Workload-level tests for the M6 modes: real generated configs and real-shaped evidence."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import yaml

from robot_debug.job_process import EvaluatorCancelled
from robot_debug.job_workload import WorkloadPaths, run_workload
from tests.test_batch_experiment import World
from tests.test_m6_config import SMOKE, THRESHOLD
from tests.test_serverless_workload import FakeCompleted, aggregate

BOUNDARIES = {"darken": 0.35, "noise": 0.55, "blur": None, "contrast": 0.05}


def policy_fails(params):
    """The fake policy: reads the *written YAML* the benchmark would get."""

    spec = params.get("image_perturbation")
    if spec is not None:
        boundary = BOUNDARIES[spec["kind"]]
        return boundary is not None and spec["severity"] >= boundary
    return "agentview_occlusion" in params  # the reduced mask, with or without a black wrist


class M6Runner:
    """Thread-safe evaluator fake that writes real-shaped evidence for the generated config."""

    def __init__(self, *, returncode=0, nominal_fails=(), raise_error=None):
        self.returncode = returncode
        self.nominal_fails = set(nominal_fails)
        self.raise_error = raise_error
        self.lock = threading.Lock()
        self.params = {}
        self.calls = []

    def __call__(self, command, *, cwd, check=False):
        config = yaml.safe_load(Path(command[-1]).read_text(encoding="utf-8"))
        params = config["benchmarks"][0]["params"]
        stem = Path(command[-1]).stem
        with self.lock:
            self.calls.append(stem)
            self.params[stem] = params
        if self.raise_error is not None:
            raise self.raise_error
        output = Path(config["output_dir"])
        output.mkdir(parents=True)
        if params.get("camera_probe"):
            # What the benchmark writes: a half-brightness wrist and an untouched agent view.
            stats = {"unperturbed_mean": 100.0, "unperturbed_std": 20.0,
                     "perturbed_mean": 50.0, "perturbed_std": 10.0}
            clean = dict(stats, perturbed_mean=100.0, perturbed_std=20.0)
            Path(params["camera_probe"]).write_text(json.dumps({
                "schema_version": 1, "perturbation": {"seed": 7},
                "episodes": [{"episode_index": 0, "samples": [
                    {"step": 0, "agentview": clean, "wrist": stats}]}]}), encoding="utf-8")
        fails = policy_fails(params) or stem in self.nominal_fails
        document = aggregate(success=not fails)
        task_id = params.get("task_id", 0)
        document["config"]["params"]["task_id"] = task_id
        document["tasks"][0]["episodes"][0]["task_id"] = task_id
        (output / "pilot_aggregate.json").write_text(json.dumps(document), encoding="utf-8")
        media = output / "episodes" / "pilot"
        media.mkdir(parents=True)
        (media / "task0000_ep0000_fixture.mp4").write_bytes(b"mp4")
        (media / "task0000_ep0000_fixture.jsonl").write_text('{"step":0}\n', encoding="utf-8")
        return FakeCompleted(self.returncode)


class WorkloadTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = WorkloadPaths(*(root / n for n in ("project", "upstream", "work", "export")))
        for path in (self.paths.project_root, self.paths.upstream_root, self.paths.work_root,
                     self.paths.export_root):
            path.mkdir()
        self.exports = []
        self.progress_events = []

    def invoke(self, config, *, world=None, runner=None, absolute_deadline=None, parity=None,
               clock=time.monotonic):
        world = world or World(item_seconds=0.0)
        runner = runner or M6Runner()
        factory_calls = []

        def evaluator_factory(**kwargs):
            factory_calls.append(kwargs)
            return runner

        def recording_exporter(source, destination, **kwargs):
            world.events.append("export")
            self.exports.append((Path(source), Path(destination), kwargs))
            return {"ok": True}

        summary = run_workload(
            config, paths=self.paths, model_factory=world.model_factory,
            evaluator_factory=evaluator_factory, exporter=recording_exporter, clock=clock,
            absolute_deadline=absolute_deadline, parity_runner=parity,
            progress=lambda event, **fields: self.progress_events.append((event, fields)),
        )
        return summary, world, runner, factory_calls

    def m6_summary(self, config):
        path = self.paths.work_root / config["run_id"] / "m6" / "m6_summary.json"
        return json.loads(path.read_text(encoding="utf-8"))


class SmokeWorkloadTests(WorkloadTestCase):
    def test_smoke_runs_one_server_and_exports_after_close(self):
        summary, world, runner, factory_calls = self.invoke(SMOKE)

        self.assertEqual(("complete", "completed"), (summary["status"], summary["stop_reason"]))
        self.assertEqual("m6-smoke", summary["mode"])
        self.assertTrue(summary["m6_complete"])
        self.assertTrue(summary["m6_nominal_passed"])
        self.assertIsNone(summary["m6_stop_reason"])
        self.assertEqual(39, len(runner.calls), "38 items and the warm-up")
        self.assertEqual(1, len(world.models))
        self.assertEqual(("faultline", 12), (world.models[0].kwargs["server"],
                                             world.models[0].kwargs["max_batch_size"]))
        self.assertEqual(
            [("start", 12), ("close", 12), "export"],
            [e for e in world.events if e == "export" or e[0] in ("start", "close")])
        self.assertEqual("complete", self.exports[0][2]["status"])
        self.assertEqual(39, len(factory_calls))
        for call in factory_calls:
            self.assertIsInstance(call["cancel"], threading.Event)
            self.assertLessEqual(call["timeout_seconds"], 300.0)
            self.assertEqual(self.paths.work_root / SMOKE["run_id"] / "logs", call["log_root"])

    def test_generated_configs_carry_the_wrist_and_scalar_blocks(self):
        _summary, _world, runner, _calls = self.invoke(SMOKE)

        black = runner.params["agentview-mask-wrist-black-01"]
        self.assertEqual(0.625, black["agentview_occlusion"]["x"])
        self.assertEqual((0.0, 1.0, 1.0), (black["wrist_occlusion"]["x"], black["wrist_occlusion"]["width"],
                                            black["wrist_occlusion"]["height"]))
        wrist_only = runner.params["wrist-mask-only-01"]
        self.assertNotIn("agentview_occlusion", wrist_only)
        self.assertEqual((0.625, 0.0, 0.375, 0.375), tuple(
            wrist_only["wrist_occlusion"][key] for key in ("x", "y", "width", "height")))
        self.assertEqual({"kind": "blur", "severity": 0.6}, runner.params["blur-s600000-02"]["image_perturbation"])
        nominal = runner.params["nominal-01"]
        self.assertNotIn("agentview_occlusion", nominal)
        self.assertNotIn("wrist_occlusion", nominal)
        self.assertNotIn("image_perturbation", nominal)
        self.assertEqual(7, nominal["seed"])

    def test_the_smoke_summary_holds_the_wrist_table_inputs(self):
        self.invoke(SMOKE)
        detail = self.m6_summary(SMOKE)
        conditions = detail["conditions"]

        self.assertEqual({"success": 6}, conditions["nominal"]["outcomes"])
        self.assertEqual({"policy_failure": 12}, conditions["agentview_mask_wrist_black"]["outcomes"])
        self.assertEqual({"success": 12}, conditions["wrist_mask_only"]["outcomes"])
        self.assertEqual({"success": 2}, conditions["blur_0.6"]["outcomes"])
        self.assertEqual({"policy_failure": 2}, conditions["darken_0.6"]["outcomes"])
        self.assertTrue(detail["complete"])

    def test_perturbed_configs_get_a_probe_path_beside_them_and_the_summary_reports_the_effect(self):
        _summary, _world, runner, _calls = self.invoke(SMOKE)
        configs = self.paths.work_root / SMOKE["run_id"] / "m6" / "configs"

        self.assertEqual(str(configs / "wrist-mask-only-01.camera_probe.json"),
                         runner.params["wrist-mask-only-01"]["camera_probe"])
        self.assertNotIn("camera_probe", runner.params["nominal-01"])
        self.assertTrue((configs / "blur-s600000-01.camera_probe.json").is_file())
        self.assertFalse(list(configs.glob("nominal*.camera_probe.json")))
        conditions = self.m6_summary(SMOKE)["conditions"]
        self.assertIsNone(conditions["nominal"]["camera_effect"])
        effect = conditions["wrist_mask_only"]["camera_effect"]
        self.assertEqual({"mean_ratio": 1.0, "std_ratio": 1.0, "samples": 12}, effect["agentview"])
        self.assertEqual({"mean_ratio": 0.5, "std_ratio": 0.5, "samples": 12}, effect["wrist"])

    def test_the_generic_model_start_is_skipped(self):
        _summary, world, _runner, _calls = self.invoke(SMOKE)
        self.assertEqual(["faultline"], [m.kwargs["server"] for m in world.models])

    def test_nonzero_evaluator_latches_partial_and_closes_before_export(self):
        config = dict(SMOKE, run_id="m6-smoke-fail")
        summary, world, _runner, _calls = self.invoke(config, runner=M6Runner(returncode=3))

        self.assertEqual(("partial", "evaluator_failed"), (summary["status"], summary["stop_reason"]))
        self.assertFalse(summary["m6_complete"])
        self.assertLess(world.events.index(("close", 12)), world.events.index("export"))
        self.assertEqual("partial", self.exports[0][2]["status"])

    def test_a_missing_media_file_is_invalid_evidence(self):
        class NoMedia(M6Runner):
            def __call__(self, command, *, cwd, check=False):
                completed = super().__call__(command, cwd=cwd, check=check)
                for media in Path(yaml.safe_load(Path(command[-1]).read_text())["output_dir"]).rglob("*.mp4"):
                    media.unlink()
                return completed

        config = dict(SMOKE, run_id="m6-smoke-media")
        summary, _world, _runner, _calls = self.invoke(config, runner=NoMedia())
        self.assertEqual(("partial", "invalid_evidence"), (summary["status"], summary["stop_reason"]))

    def test_a_cancelled_evaluator_is_not_cleanup_uncertainty(self):
        config = dict(SMOKE, run_id="m6-smoke-cancel")
        summary, _world, _runner, _calls = self.invoke(
            config, runner=M6Runner(raise_error=EvaluatorCancelled()))
        self.assertEqual("partial", summary["status"])
        self.assertEqual(1, len(self.exports), "cancellation confirmed the group, so export proceeds")

    def test_unconfirmed_server_cleanup_never_exports(self):
        config = dict(SMOKE, run_id="m6-smoke-close")
        summary, _world, _runner, _calls = self.invoke(config, world=World(item_seconds=0.0, model_fail="close"))
        self.assertEqual(("partial", "cleanup_unconfirmed"), (summary["status"], summary["stop_reason"]))
        self.assertEqual([], self.exports)

    def test_prefetch_hook_runs_once_before_the_server(self):
        order = []

        class Factory:
            def __init__(self, world):
                self.world = world

            def __call__(self, **kwargs):
                order.append("model")
                return self.world.model_factory(**kwargs)

            def prefetch(self, *, log_root):
                order.append(("prefetch", log_root))

        config = dict(SMOKE, run_id="m6-smoke-prefetch")
        summary = run_workload(
            config, paths=self.paths, model_factory=Factory(World(item_seconds=0.0)),
            evaluator_factory=lambda **_k: M6Runner(), exporter=lambda *a, **k: {"ok": True},
            clock=time.monotonic)
        self.assertEqual("complete", summary["status"])
        self.assertEqual([("prefetch", self.paths.work_root / config["run_id"] / "logs"), "model"], order)
        self.assertIsNotNone(self.m6_summary(config)["prefetch_seconds"])

    def test_a_short_deadline_never_starts_the_server(self):
        config = dict(SMOKE, run_id="m6-smoke-late")
        summary, world, runner, _calls = self.invoke(config, absolute_deadline=time.monotonic() + 100)
        self.assertEqual(("partial", "deadline_exhausted"), (summary["status"], summary["stop_reason"]))
        self.assertEqual([], runner.calls)
        self.assertEqual("partial", self.exports[0][2]["status"])


class ThresholdWorkloadTests(WorkloadTestCase):
    def test_threshold_run_finds_each_family_and_reports_it_in_the_workload_summary(self):
        summary, world, runner, factory_calls = self.invoke(THRESHOLD, world=World(item_seconds=0.0))

        self.assertEqual(("complete", "completed"), (summary["status"], summary["stop_reason"]))
        self.assertEqual("m6-threshold", summary["mode"])
        self.assertTrue(summary["m6_complete"])
        self.assertTrue(summary["m6_nominal_passed"])
        self.assertEqual({"darken": 0.35, "noise": 0.55, "blur": None, "contrast": 0.05},
                         summary["m6_thresholds"])
        self.assertEqual(121, len(runner.calls), "5 controls, 115 attempts and the warm-up")
        self.assertEqual(1, len(world.models))
        self.assertLess(world.events.index(("close", 12)), world.events.index("export"))
        for call in factory_calls:
            self.assertLessEqual(call["timeout_seconds"], 300.0)

    def test_threshold_summary_has_the_per_level_evidence(self):
        self.invoke(THRESHOLD)
        detail = self.m6_summary(THRESHOLD)

        self.assertEqual(THRESHOLD["families"], list(detail["config"]["families"]))
        darken = detail["families"]["darken"]
        self.assertEqual([0.2, 0.4, 0.3, 0.35, 0.325, 0.3375], darken["levels_tried"])
        self.assertEqual("threshold_found", darken["stop_reason"])
        self.assertEqual(["sweep", "sweep", "bisect", "bisect", "bisect", "bisect"],
                         [level["phase"] for level in darken["levels"]])
        self.assertEqual({"name": "brightness_factor", "value": round(1 - 0.95 * 0.3, 6)},
                         darken["levels"][2]["physical"])
        self.assertEqual("no_reproducible_failure", detail["families"]["blur"]["stop_reason"])
        self.assertTrue(detail["nominal_controls"]["passed"])

    def test_threshold_configs_use_the_real_writer_for_each_attempt(self):
        _summary, _world, runner, _calls = self.invoke(THRESHOLD)
        attempts = [stem for stem in runner.params if stem.startswith("noise-s550000")]
        self.assertEqual(5, len(attempts))
        for stem in attempts:
            self.assertEqual({"kind": "noise", "severity": 0.55}, runner.params[stem]["image_perturbation"])
        for control in [s for s in runner.params if s.startswith("nominal-control")]:
            self.assertNotIn("image_perturbation", runner.params[control])

    def test_the_audit_target_reaches_the_written_benchmark_params(self):
        config = dict(THRESHOLD, run_id="m6-threshold-target", families=["darken"], sweep=[0.5, 1.0],
                      attempts=2, required_failures=2, bisection_steps=1,
                      suite="libero_10", task_id=3, init_state_index=14)
        summary, _world, runner, _calls = self.invoke(config)
        self.assertEqual(("complete", "completed"), (summary["status"], summary["stop_reason"]))
        self.assertGreater(len(runner.params), 6)
        for stem, params in runner.params.items():
            with self.subTest(stem=stem):
                self.assertEqual(("libero_10", 3, 14), (
                    params["suite"], params["task_id"], params["init_state_index"]))
        detail = self.m6_summary(config)
        self.assertEqual(("libero_10", 3, 14), (
            detail["config"]["suite"], detail["config"]["task_id"], detail["config"]["init_state_index"]))

    def test_without_a_target_the_params_keep_the_recorded_defaults(self):
        _summary, _world, runner, _calls = self.invoke(THRESHOLD)
        for params in runner.params.values():
            self.assertEqual("libero_object", params["suite"])
            self.assertNotIn("task_id", params)
            self.assertNotIn("init_state_index", params)

    def test_a_failed_control_makes_the_run_partial_and_runs_no_family(self):
        config = dict(THRESHOLD, run_id="m6-threshold-nominal")
        summary, world, runner, _calls = self.invoke(
            config, runner=M6Runner(nominal_fails={"nominal-control-03"}))

        self.assertEqual(("partial", "nominal_controls_failed"), (summary["status"], summary["stop_reason"]))
        self.assertFalse(summary["m6_nominal_passed"])
        self.assertEqual(6, len(runner.calls))
        detail = self.m6_summary(config)
        self.assertTrue(all(item["stop_reason"] == "nominal_failed" for item in detail["families"].values()))
        self.assertEqual("partial", self.exports[0][2]["status"])

    def test_evaluator_failure_cancels_the_pool_and_is_never_a_policy_failure(self):
        config = dict(THRESHOLD, run_id="m6-threshold-fail")
        summary, world, _runner, _calls = self.invoke(config, runner=M6Runner(returncode=3))
        self.assertEqual(("partial", "evaluator_failed"), (summary["status"], summary["stop_reason"]))
        detail = self.m6_summary(config)
        self.assertEqual(0, detail["valid_count"])
        self.assertIn(("close", 12), world.events)

    def test_a_deadline_short_of_the_work_ends_partial_and_exports(self):
        config = dict(THRESHOLD, run_id="m6-threshold-short")
        skew = [0.0]

        class JumpAfter(M6Runner):
            def __call__(self, command, *, cwd, check=False):
                completed = super().__call__(command, cwd=cwd, check=check)
                if len(self.calls) >= 30:
                    skew[0] = 1600.0  # leaves 186 s of a 1800 s Job: below the 300 s item guard
                return completed

        summary, _world, runner, _calls = self.invoke(
            config, runner=JumpAfter(), clock=lambda: time.monotonic() + skew[0])
        self.assertEqual(("partial", "deadline_exhausted"), (summary["status"], summary["stop_reason"]))
        self.assertLess(len(runner.calls), 60, "nothing new starts once the guard trips")
        self.assertEqual("partial", self.exports[0][2]["status"])
        detail = self.m6_summary(config)
        self.assertIn("deadline_exhausted", {item["stop_reason"] for item in detail["families"].values()})
        self.assertFalse(detail["complete"])


if __name__ == "__main__":
    unittest.main()
