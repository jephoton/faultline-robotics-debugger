"""Tests for the injectable, finite serverless workload orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import yaml

from robot_debug.job_process import InfrastructureError
from robot_debug.job_runtime import JobRuntimeError
from robot_debug.job_workload import WorkloadPaths, _driver_reason, run_workload
from scripts import run_failure_search


class FakeClock:
    def __init__(self, *values: float) -> None:
        self.values = list(values) or [100.0]
        self.last = self.values[0]

    def __call__(self) -> float:
        if self.values:
            self.last = max(self.last, self.values.pop(0))
        return self.last

    def advance_to(self, value: float) -> None:
        self.last = max(self.last, value)


class FakeCompleted:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode


class FakeModel:
    def __init__(self, events: list[object], *, failure: str | None = None, die_after_run: bool = False) -> None:
        self.events = events
        self.failure = failure
        self.die_after_run = die_after_run

    def start(self) -> None:
        self.events.append("start")
        if self.failure == "start":
            raise InfrastructureError("hidden")

    def wait_ready(self, *, deadline: float) -> None:
        self.events.append(("ready", deadline))
        if self.failure == "ready":
            raise InfrastructureError("hidden")

    def check_alive(self) -> None:
        self.events.append("alive")
        if self.failure == "dead" or (self.die_after_run and "run" in self.events):
            raise InfrastructureError("hidden")

    def close(self) -> None:
        self.events.append("close")
        if self.failure == "interrupt_close":
            raise KeyboardInterrupt
        if self.failure == "close":
            raise InfrastructureError("hidden")


class ClockAdvancingModel(FakeModel):
    def __init__(self, events: list[object], clock: FakeClock, *, advance_on_check: int, to: float) -> None:
        super().__init__(events)
        self.clock = clock
        self.advance_on_check = advance_on_check
        self.to = to
        self.check_count = 0

    def check_alive(self) -> None:
        self.check_count += 1
        super().check_alive()
        if self.check_count == self.advance_on_check:
            self.clock.advance_to(self.to)


def aggregate(*, success: bool, infrastructure: bool = False) -> dict[str, object]:
    episode = {
        "task_id": 0,
        "episode_idx": 0,
        "name": "task zero",
        "steps": 8,
        "elapsed_sec": 1.25,
        "metrics": {"success": success},
        "failure_reason": "exception" if infrastructure else (None if success else "task"),
    }
    return {
        "benchmark": "pilot",
        "created_at": "2026-10-09T00:00:00Z",
        "eval_id": "eval-pilot",
        "config": {
            "benchmark": "robot_debug.libero:DiagnosticLIBEROBenchmark",
            "params": {"task_id": 0, "seed": 7, "env_seed": 7},
        },
        "tasks": [{"task": "task zero", "episodes": [episode]}],
    }


class FixtureRunner:
    def __init__(self, events: list[object], outcomes=(True, False), *, bad: str | None = None) -> None:
        self.events = events
        self.outcomes = list(outcomes)
        self.bad = bad
        self.configs: list[dict[str, object]] = []

    def __call__(self, command, *, cwd, check=False):
        self.events.append("run")
        config = yaml.safe_load(Path(command[-1]).read_text(encoding="utf-8"))
        self.configs.append(config)
        if self.bad == "raise":
            raise RuntimeError("hidden")
        if self.bad == "timeout":
            raise TimeoutError("hidden")
        if self.bad == "raise_infra":
            raise InfrastructureError("hidden")
        if self.bad == "subprocess_timeout":
            raise subprocess.TimeoutExpired(command, timeout=1)
        output = Path(config["output_dir"])
        output.mkdir(parents=True)
        payload = aggregate(success=self.outcomes.pop(0), infrastructure=self.bad == "infra")
        if self.bad == "rewritten_episode_identity":
            payload["tasks"][0]["episodes"][0]["episode_idx"] = 1
        if self.bad == "rewritten_task_identity":
            payload["tasks"][0]["episodes"][0]["task_id"] = 1
        if self.bad == "sensitive_detail":
            payload["tasks"][0]["episodes"][0]["failure_detail"] = "secret-in-error-message"
        if self.bad == "malformed_aggregate":
            (output / "pilot_aggregate.json").write_text("{broken", encoding="utf-8")
            return FakeCompleted()
        (output / "pilot_aggregate.json").write_text(json.dumps(payload), encoding="utf-8")
        media = output / "episodes" / "pilot"
        media.mkdir(parents=True)
        task_prefix = "task0001" if self.bad == "rewritten_task_identity" else "task0000"
        episode_suffix = "0001" if self.bad == "rewritten_episode_identity" else "0000"
        (media / (task_prefix + "_ep" + episode_suffix + "_fixture.mp4")).write_bytes(b"mp4")
        (media / (task_prefix + "_ep" + episode_suffix + "_fixture.jsonl")).write_text('{"step":0}\n', encoding="utf-8")
        if self.bad == "missing":
            (media / "task0000_ep0000_fixture.mp4").unlink()
        if self.bad == "wrong_episode_media":
            (media / "task0000_ep0000_fixture.mp4").rename(media / "task0000_ep0001_fixture.mp4")
            (media / "task0000_ep0000_fixture.jsonl").rename(media / "task0000_ep0001_fixture.jsonl")
        if self.bad == "empty":
            (media / "task0000_ep0000_fixture.mp4").write_bytes(b"")
        if self.bad == "empty_trace":
            (media / "task0000_ep0000_fixture.jsonl").write_text("", encoding="utf-8")
        if self.bad == "ambiguous":
            (media / "task0000_ep0000_other.mp4").write_bytes(b"mp4")
        if self.bad == "multiple_aggregates":
            (output / "other_aggregate.json").write_text(json.dumps(payload), encoding="utf-8")
        return FakeCompleted(3 if self.bad == "nonzero" else 0)


class ValidEvaluatorRunner:
    """Write valid synthetic aggregate and media evidence for actual driver tests."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, command, *, cwd, check=False):
        config = yaml.safe_load(Path(command[-1]).read_text(encoding="utf-8"))
        output = Path(config["output_dir"])
        output.mkdir(parents=True)
        benchmark = config["benchmarks"][0]
        count = benchmark["episodes_per_task"]
        params = benchmark["params"]
        task_id = params.get("task_id", 0)
        episodes = [
            {
                "task_id": task_id,
                "episode_idx": index,
                "name": "task zero",
                "steps": 8,
                "elapsed_sec": 0.5,
                "metrics": {"success": True},
                "failure_reason": None,
            }
            for index in range(count)
        ]
        payload = {
            "benchmark": "pilot",
            "created_at": "2026-10-09T00:00:00Z",
            "eval_id": "eval-{}".format(output.name),
            "config": {
                "benchmark": "robot_debug.libero:DiagnosticLIBEROBenchmark",
                "params": {"task_id": task_id, "seed": 7, "env_seed": 7},
            },
            "tasks": [{"task": "task zero", "episodes": episodes}],
        }
        (output / "pilot_aggregate.json").write_text(json.dumps(payload), encoding="utf-8")
        media = output / "episodes" / "pilot"
        media.mkdir(parents=True)
        for episode in episodes:
            index = episode["episode_idx"]
            prefix = "task{:04d}_ep{:04d}".format(task_id, index)
            (media / (prefix + "_fixture.mp4")).write_bytes(b"fake-mp4")
            (media / (prefix + "_fixture.jsonl")).write_text('{"step":0}\n', encoding="utf-8")
        self.calls += 1
        return FakeCompleted()


def valid_driver_summary(mode: str) -> dict[str, object]:
    stage = {
        "stage": "fixture",
        "status": "completed",
        "infrastructure_error": None,
        "invalid_evidence": None,
        "returncode": 0,
    }
    if mode == "search":
        return {
            "planned": {},
            "completed": {"stages": [stage], "nominal_successes": 20, "replay_outcomes": []},
            "outcomes": [],
            "elapsed_seconds": 1.0,
            "stop_reason": "no_policy_failure_in_sweep",
            "reproducible": False,
        }
    if mode == "grid":
        return {
            "planned": {},
            "completed": {
                "stages": [stage], "sentinel_outcome": "success", "positions_attempted": [],
                "replay_outcomes": [], "control_outcomes": [],
            },
            "outcomes": [],
            "first_apparent_failure": None,
            "reproducible": None,
            "nominal_controls_passed": None,
            "elapsed_seconds": 1.0,
            "stop_reason": "no_policy_failure_in_grid",
        }
    return {
        "schema_version": 1,
        "planned": {},
        "completed": {"stages": [stage], "decisions": [], "sentinel_outcome": "success", "control_outcomes": []},
        "outcomes": [],
        "lineage": [],
        "elapsed_seconds": 1.0,
        "stop_reason": "parent_not_reproducible",
    }


class ServerlessWorkloadTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.project = root / "project"
        self.upstream = root / "upstream"
        self.work = root / "work"
        self.export = root / "export"
        for path in (self.project, self.upstream, self.work, self.export):
            path.mkdir()
        self.paths = WorkloadPaths(self.project, self.upstream, self.work, self.export)
        self.config = {
            "schema_version": 1,
            "mode": "pilot",
            "run_id": "pilot-001",
            "deadline_seconds": 60,
        }

    def invoke(self, *, model_failure=None, model=None, runner=None, exporter=None, clock=None,
               config=None, evaluator_factory=None, model_factory=None):
        events: list[object] = []
        model = model or FakeModel(events, failure=model_failure)
        runner = runner or FixtureRunner(events)
        exports = []

        def recording_evaluator_factory(**kwargs):
            events.append(("factory", kwargs))
            return runner

        def recording_exporter(source, destination, **kwargs):
            events.append("export")
            exports.append((source, destination, kwargs))
            if exporter is not None:
                return exporter(source, destination, **kwargs)
            return {"ok": True}

        result = run_workload(
            config if config is not None else self.config,
            paths=self.paths,
            model_factory=model_factory or (lambda **kwargs: model),
            evaluator_factory=evaluator_factory or recording_evaluator_factory,
            exporter=recording_exporter,
            clock=clock or FakeClock(100, 100, 101, 102, 103, 104, 105, 106, 107),
        )
        return result, events, runner, exports

    def test_pilot_runs_serial_nominal_then_masked_and_exports_after_close(self) -> None:
        result, events, runner, exports = self.invoke()
        self.assertEqual("complete", result["status"])
        self.assertEqual("completed", result["stop_reason"])
        self.assertEqual(["success", "policy_failure"], [item["outcome"] for item in result["pilot_outcomes"]])
        self.assertNotIn("agentview_occlusion", runner.configs[0]["benchmarks"][0]["params"])
        self.assertEqual(
            {"enabled": True, "x": 0.5, "y": 0.0, "width": 0.375, "height": 0.375,
             "color": [0, 0, 0], "opacity": 1.0},
            runner.configs[1]["benchmarks"][0]["params"]["agentview_occlusion"],
        )
        self.assertLess(events.index("close"), events.index("export"))
        self.assertEqual("complete", exports[0][2]["status"])

    def test_masked_policy_success_is_a_valid_complete_outcome(self) -> None:
        result, _, _, _ = self.invoke(runner=FixtureRunner([], outcomes=(True, True)))
        self.assertEqual("complete", result["status"])
        self.assertEqual(["success", "success"], [item["outcome"] for item in result["pilot_outcomes"]])

    def test_actual_exporter_publishes_complete_manifest_and_preserves_local_evidence(self) -> None:
        result, _, _, _ = self.invoke(exporter=None)
        # The default is tested separately because invoke records an injected exporter.
        second_config = dict(self.config, run_id="pilot-actual")
        events: list[object] = []
        model = FakeModel(events)
        summary = run_workload(second_config, paths=self.paths,
            model_factory=lambda **kwargs: model,
            evaluator_factory=lambda **kwargs: FixtureRunner(events),
            clock=FakeClock(1, 1, 2, 3, 4, 5, 6, 7, 8))
        self.assertEqual("complete", summary["status"])
        self.assertTrue((self.export / "pilot-actual" / "manifest.json").is_file())
        self.assertTrue((self.work / "pilot-actual" / "workload_summary.json").is_file())

    def test_actual_exporter_publishes_partial_manifest_and_preserves_local_evidence(self) -> None:
        config = dict(self.config, run_id="pilot-partial")
        events: list[object] = []
        model = FakeModel(events, failure="start")
        summary = run_workload(
            config,
            paths=self.paths,
            model_factory=lambda **kwargs: model,
            evaluator_factory=lambda **kwargs: self.fail("runner must not be created"),
            clock=FakeClock(1, 1, 2, 3, 4),
        )
        manifest = json.loads((self.export / "pilot-partial" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("partial", summary["status"])
        self.assertEqual("partial", manifest["status"])
        local_summary = self.work / "pilot-partial" / "workload_summary.json"
        self.assertTrue(local_summary.is_file())
        self.assertEqual("model_start_failed", json.loads(local_summary.read_text(encoding="utf-8"))["stop_reason"])

    def test_exact_config_validation_and_preexisting_roots_happen_before_model(self) -> None:
        for bad in ({**self.config, "extra": True}, {**self.config, "mode": "unknown"}):
            with self.subTest(bad=bad), self.assertRaises(JobRuntimeError):
                self.invoke_with_config(bad)
        (self.work / self.config["run_id"]).mkdir()
        with self.assertRaises(JobRuntimeError):
            self.invoke_with_config(self.config)

    def invoke_with_config(self, config):
        return run_workload(config, paths=self.paths,
            model_factory=lambda **kwargs: self.fail("model must not be created"),
            evaluator_factory=lambda **kwargs: self.fail("runner must not be created"))

    def test_overlap_and_non_directory_roots_are_rejected(self) -> None:
        overlapping = WorkloadPaths(self.project, self.upstream, self.work, self.work / "child")
        (self.work / "child").mkdir()
        with self.assertRaises(JobRuntimeError):
            run_workload(self.config, paths=overlapping,
                model_factory=lambda **kwargs: self.fail("model created"),
                evaluator_factory=lambda **kwargs: self.fail("runner created"))

    def test_linked_roots_and_preexisting_export_destination_are_rejected(self) -> None:
        linked_project = self.project.parent / "project-link"
        try:
            linked_project.symlink_to(self.project, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable on this Windows account")
        linked_paths = WorkloadPaths(linked_project, self.upstream, self.work, self.export)
        with self.assertRaises(JobRuntimeError):
            run_workload(
                self.config,
                paths=linked_paths,
                model_factory=lambda **kwargs: self.fail("model created"),
                evaluator_factory=lambda **kwargs: self.fail("runner created"),
            )
        (self.export / self.config["run_id"]).mkdir()
        with self.assertRaises(JobRuntimeError):
            run_workload(
                self.config,
                paths=self.paths,
                model_factory=lambda **kwargs: self.fail("model created"),
                evaluator_factory=lambda **kwargs: self.fail("runner created"),
            )

    def test_deadline_exhausted_launches_nothing_but_exports_partial(self) -> None:
        result, events, _, exports = self.invoke(
            clock=FakeClock(100, 100), config=dict(self.config, deadline_seconds=14)
        )
        self.assertEqual("deadline_exhausted", result["stop_reason"])
        self.assertNotIn("start", events)
        self.assertFalse(any(isinstance(item, tuple) and item[0] == "factory" for item in events))
        self.assertEqual("partial", exports[0][2]["status"])

    def test_startup_consuming_launch_window_prevents_model_start(self) -> None:
        events: list[object] = []
        model = FakeModel(events)
        clock = FakeClock(100, 100, 200, 201, 202)

        def slow_factory(**kwargs):
            events.append("model_factory")
            clock()
            return model

        result, _, _, exports = self.invoke(
            clock=clock, model_factory=slow_factory, model=model
        )
        self.assertEqual("deadline_exhausted", result["stop_reason"])
        self.assertNotIn("start", model.events)
        self.assertEqual("partial", exports[0][2]["status"])

    def test_model_failures_close_and_export_partial_with_safe_codes(self) -> None:
        for failure, reason in (("start", "model_start_failed"), ("ready", "readiness_failed"), ("dead", "model_died")):
            with self.subTest(failure=failure):
                config = dict(self.config, run_id="pilot-" + failure)
                self.config = config
                result, events, _, exports = self.invoke(model_failure=failure)
                self.assertEqual(reason, result["stop_reason"])
                self.assertIn("close", events)
                self.assertEqual("partial", exports[0][2]["status"])
                self.assertNotIn("hidden", json.dumps(result))

    def test_cleanup_failure_never_exports(self) -> None:
        result, events, _, exports = self.invoke(model_failure="close")
        self.assertEqual("cleanup_unconfirmed", result["stop_reason"])
        self.assertEqual([], exports)
        self.assertNotIn("export", events)

    def test_evaluator_failures_latch_and_export_partial(self) -> None:
        for bad, reason in (("nonzero", "evaluator_failed"), ("infra", "evaluator_failed"),
                            ("missing", "invalid_evidence"), ("empty", "invalid_evidence"),
                            ("empty_trace", "invalid_evidence"),
                            ("malformed_aggregate", "invalid_evidence"),
                            ("ambiguous", "invalid_evidence"),
                            ("wrong_episode_media", "invalid_evidence"),
                            ("multiple_aggregates", "invalid_evidence")):
            with self.subTest(bad=bad):
                self.config = dict(self.config, run_id="pilot-" + bad.replace("_", "-"))
                events: list[object] = []
                result, _, runner, exports = self.invoke(runner=FixtureRunner(events, bad=bad))
                self.assertEqual(reason, result["stop_reason"])
                self.assertEqual(1, len(runner.configs))
                self.assertEqual("partial", exports[0][2]["status"])

    def test_unknown_physical_runner_failures_leave_cleanup_unconfirmed(self) -> None:
        for bad in ("raise", "timeout", "raise_infra"):
            with self.subTest(bad=bad):
                self.config = dict(self.config, run_id="uncertain-" + bad.replace("_", "-"))
                events: list[object] = []
                runner = FixtureRunner(events, bad=bad)
                result, _, _, exports = self.invoke(runner=runner)
                self.assertEqual("cleanup_unconfirmed", result["stop_reason"])
                self.assertEqual("partial", result["status"])
                self.assertEqual([], exports)
                self.assertNotIn("export", events)

    def test_confirmed_subprocess_timeout_exports_partial_evidence(self) -> None:
        self.config = dict(self.config, run_id="confirmed-timeout")
        events: list[object] = []
        runner = FixtureRunner(events, bad="subprocess_timeout")
        result, _, _, exports = self.invoke(runner=runner)
        self.assertEqual("evaluator_failed", result["stop_reason"])
        self.assertEqual("partial", result["status"])
        self.assertEqual("partial", exports[0][2]["status"])

    def test_evaluator_factory_failure_before_dispatch_keeps_cleanup_confirmed(self) -> None:
        self.config = dict(self.config, run_id="factory-failure")

        def fail_factory(**kwargs):
            raise RuntimeError("no evaluator process was started")

        result, _, _, exports = self.invoke(evaluator_factory=fail_factory)
        self.assertEqual("evaluator_failed", result["stop_reason"])
        self.assertEqual("partial", result["status"])
        self.assertEqual("partial", exports[0][2]["status"])

    def test_pilot_summary_omits_untrusted_failure_text(self) -> None:
        self.config = dict(self.config, run_id="safe-pilot")
        result, _, _, _ = self.invoke(runner=FixtureRunner([], outcomes=(False, True), bad="sensitive_detail"))
        self.assertEqual("policy_failure", result["pilot_outcomes"][0]["outcome"])
        self.assertNotIn("secret-in-error-message", json.dumps(result))

    def test_aggregate_and_media_cannot_rewrite_requested_episode_identity(self) -> None:
        for bad, run_id in (("rewritten_episode_identity", "rewritten-episode"),
                            ("rewritten_task_identity", "rewritten-task")):
            with self.subTest(bad=bad):
                self.config = dict(self.config, run_id=run_id)
                result, _, runner, exports = self.invoke(
                    runner=FixtureRunner([], outcomes=(True, True), bad=bad)
                )
                self.assertEqual("invalid_evidence", result["stop_reason"])
                self.assertEqual(1, len(runner.configs))
                self.assertEqual("partial", exports[0][2]["status"])

    def test_liveness_check_that_exhausts_deadline_prevents_dispatch(self) -> None:
        clock = FakeClock(100, 100, 101, 102, 103, 104, 105, 106)
        events: list[object] = []
        model = ClockAdvancingModel(events, clock, advance_on_check=2, to=200)
        runner = FixtureRunner(events)
        result, _, _, exports = self.invoke(model=model, runner=runner, clock=clock)
        self.assertEqual("deadline_exhausted", result["stop_reason"])
        self.assertEqual([], runner.configs)
        self.assertEqual("partial", exports[0][2]["status"])

    def test_evaluator_timeout_uses_budget_after_liveness_check(self) -> None:
        clock = FakeClock(100, 100, 101, 102, 103, 104, 105, 106, 107, 108)
        events: list[object] = []
        model = ClockAdvancingModel(events, clock, advance_on_check=2, to=108)
        runner = FixtureRunner(events)
        timeouts = []

        def evaluator_factory(**kwargs):
            timeouts.append(kwargs["timeout_seconds"])
            return runner

        result, _, _, _ = self.invoke(
            model=model, runner=runner, clock=clock, evaluator_factory=evaluator_factory
        )
        self.assertEqual("complete", result["status"])
        self.assertEqual(2, len(timeouts))
        self.assertLess(timeouts[0], 43)

    def test_model_death_during_evaluator_factory_prevents_dispatch(self) -> None:
        events: list[object] = []
        model = FakeModel(events)
        runner = FixtureRunner(events)

        def evaluator_factory(**kwargs):
            model.failure = "dead"
            return runner

        result, _, _, exports = self.invoke(
            model=model, runner=runner, evaluator_factory=evaluator_factory
        )
        self.assertEqual("model_died", result["stop_reason"])
        self.assertEqual([], runner.configs)
        self.assertEqual("partial", exports[0][2]["status"])

    def test_factory_construction_that_exhausts_deadline_prevents_dispatch(self) -> None:
        clock = FakeClock(100, 100, 101, 102, 103, 104, 105, 106)
        events: list[object] = []
        model = FakeModel(events)
        runner = FixtureRunner(events)

        def evaluator_factory(**kwargs):
            clock.advance_to(200)
            return runner

        result, _, _, exports = self.invoke(
            model=model, runner=runner, evaluator_factory=evaluator_factory, clock=clock
        )
        self.assertEqual("deadline_exhausted", result["stop_reason"])
        self.assertEqual([], runner.configs)
        self.assertEqual("partial", exports[0][2]["status"])

    def test_model_death_after_evaluator_prevents_next_pilot_launch(self) -> None:
        events: list[object] = []
        model = FakeModel(events, die_after_run=True)
        runner = FixtureRunner(events)
        result, _, _, exports = self.invoke(model=model, runner=runner)
        self.assertEqual("model_died", result["stop_reason"])
        self.assertEqual(1, len(runner.configs))
        self.assertEqual("partial", exports[0][2]["status"])

    def test_each_evaluator_factory_gets_current_remaining_budget(self) -> None:
        events: list[object] = []
        model = FakeModel(events)
        runner = FixtureRunner(events)
        timeouts = []

        def evaluator_factory(**kwargs):
            timeouts.append(kwargs["timeout_seconds"])
            return runner

        result, _, _, _ = self.invoke(model=model, runner=runner, evaluator_factory=evaluator_factory)
        self.assertEqual("complete", result["status"])
        self.assertEqual(2, len(timeouts))
        self.assertGreater(timeouts[0], timeouts[1])

    def test_keyboard_interrupt_closes_exports_partial_and_reraises(self) -> None:
        events: list[object] = []
        model = FakeModel(events)
        exports = []
        with self.assertRaises(KeyboardInterrupt):
            run_workload(self.config, paths=self.paths,
                model_factory=lambda **kwargs: model,
                evaluator_factory=lambda **kwargs: mock.Mock(side_effect=KeyboardInterrupt),
                exporter=lambda *args, **kwargs: exports.append(kwargs),
                clock=FakeClock(10, 10, 11, 12, 13))
        self.assertIn("close", events)
        self.assertEqual("partial", exports[0]["status"])

    def test_keyboard_interrupt_during_close_is_not_swallowed_or_exported(self) -> None:
        events: list[object] = []
        model = FakeModel(events, failure="interrupt_close")
        with self.assertRaises(KeyboardInterrupt):
            run_workload(
                self.config,
                paths=self.paths,
                model_factory=lambda **kwargs: model,
                evaluator_factory=lambda **kwargs: self.fail("runner must not be created"),
                exporter=lambda *args, **kwargs: self.fail("uncertain cleanup must not export"),
                clock=FakeClock(10, 10, 11, 12, 13),
            )
        summary_path = self.work / self.config["run_id"] / "workload_summary.json"
        self.assertEqual("cleanup_unconfirmed", json.loads(summary_path.read_text(encoding="utf-8"))["stop_reason"])

    def test_export_failure_propagates_and_local_summary_remains(self) -> None:
        def fail_export(*args, **kwargs):
            raise RuntimeError("export failed")
        with self.assertRaisesRegex(RuntimeError, "export failed"):
            self.invoke(exporter=fail_export)
        self.assertTrue((self.work / self.config["run_id"] / "workload_summary.json").is_file())

    def test_nonpilot_modes_call_exact_driver_with_bounded_runner(self) -> None:
        targets = {
            "search": "scripts.run_failure_search.run_session",
            "grid": "scripts.run_position_grid_search.run_session",
            "reduce": "scripts.run_failure_reduction.run_session",
        }
        for mode, target in targets.items():
            with self.subTest(mode=mode):
                self.config = dict(self.config, mode=mode, run_id=mode + "-001")
                seen = {}
                def driver(**kwargs):
                    seen.update(kwargs)
                    return valid_driver_summary(mode)
                with mock.patch(target, side_effect=driver) as patched:
                    clock = FakeClock(100, 100, 101, 102, 103, 104, 105, 106, 107)
                    result, _, _, _ = self.invoke(clock=clock)
                patched.assert_called_once()
                self.assertEqual(self.work / self.config["run_id"], seen["results_root"])
                self.assertIs(clock, seen["monotonic_clock"])
                self.assertEqual(self.upstream, seen["upstream_root"])
                self.assertEqual(self.project, seen["project_root"])
                self.assertTrue(callable(seen["command_runner"]))
                self.assertGreater(seen["launch_cutoff_seconds"], 0)
                self.assertEqual("complete", result["status"])

    def test_actual_drivers_treat_null_error_fields_as_valid_policy_outcomes(self) -> None:
        expected = {"search": (7, "no_policy_failure_in_sweep"),
                    "grid": (9, "no_policy_failure_in_grid"),
                    "reduce": (3, "parent_not_reproducible")}
        for mode, (expected_calls, expected_stop) in expected.items():
            with self.subTest(mode=mode):
                config = dict(self.config, mode=mode, run_id="actual-" + mode)
                events: list[object] = []
                model = FakeModel(events)
                evaluator = ValidEvaluatorRunner()
                result = run_workload(
                    config,
                    paths=self.paths,
                    model_factory=lambda **kwargs: model,
                    evaluator_factory=lambda **kwargs: evaluator,
                    exporter=lambda *args, **kwargs: {"ok": True},
                    clock=FakeClock(100, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109),
                )
                self.assertEqual("complete", result["status"])
                self.assertEqual("completed", result["stop_reason"])
                self.assertEqual(expected_calls, evaluator.calls)
                driver_summary = json.loads(
                    (self.work / config["run_id"] / ("first-failure-search" if mode == "search" else "position-grid-search" if mode == "grid" else "failure-reduction") / "session_summary.json").read_text(encoding="utf-8")
                )
                self.assertEqual(expected_stop, driver_summary["stop_reason"])

    def test_driver_error_classification_uses_statuses_and_nonnull_error_values(self) -> None:
        valid = valid_driver_summary("search")
        valid["completed"]["stages"][0]["note"] = "ordinary text mentions infrastructure_error and invalid_evidence"
        self.assertIsNone(_driver_reason(valid))

        invalid = valid_driver_summary("grid")
        invalid["completed"]["stages"][0]["invalid_evidence"] = "aggregate did not match requested episode"
        self.assertEqual("invalid_evidence", _driver_reason(invalid))

        infrastructure = valid_driver_summary("reduce")
        infrastructure["completed"]["stages"][0]["infrastructure_error"] = "runner timed out"
        self.assertEqual("evaluator_failed", _driver_reason(infrastructure))

        outcome_error = valid_driver_summary("search")
        outcome_error["outcomes"] = [{"outcome": "infrastructure_error"}]
        self.assertEqual("evaluator_failed", _driver_reason(outcome_error))

    def test_driver_cannot_launch_again_after_swallowing_infrastructure_error(self) -> None:
        self.config = dict(self.config, mode="search", run_id="latched-search")
        events: list[object] = []
        model = FakeModel(events)
        runner = FixtureRunner(events, bad="nonzero")
        factory_calls = []

        def evaluator_factory(**kwargs):
            factory_calls.append(kwargs)
            return runner

        def swallowing_driver(**kwargs):
            config_path = self.work / self.config["run_id"] / "probe.yaml"
            run_failure_search._write_config(
                config_path=config_path,
                output_dir=config_path.parent / "output",
                project_root=self.project,
                stage_name="probe",
                episode_indices=(0,),
                task_id=0,
                seed=7,
            )
            command = ["vla-eval", "run", "--config", str(config_path)]
            with self.assertRaises(InfrastructureError):
                kwargs["command_runner"](command, cwd=self.upstream, check=False)
            with self.assertRaises(InfrastructureError):
                kwargs["command_runner"](command, cwd=self.upstream, check=False)
            return {"stop_reason": "caught_error"}

        with mock.patch("scripts.run_failure_search.run_session", side_effect=swallowing_driver):
            result, _, _, exports = self.invoke(
                model=model, runner=runner, evaluator_factory=evaluator_factory
            )
        self.assertEqual("evaluator_failed", result["stop_reason"])
        self.assertEqual(1, len(factory_calls))
        self.assertEqual(1, len(runner.configs))
        self.assertEqual("partial", exports[0][2]["status"])


if __name__ == "__main__":
    unittest.main()
