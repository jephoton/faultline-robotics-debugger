"""Workload-level tests for the M3 batching modes, evaluator cancellation and parity launch."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import yaml

from robot_debug import job_entry
from robot_debug.job_entry import ImageLayout, ProductionModelFactory
from robot_debug.job_process import (
    CleanupUnconfirmed,
    DirectEvaluator,
    EvaluatorCancelled,
    InfrastructureError,
)
from robot_debug.job_workload import WorkloadPaths, run_workload
from tests.test_batch_experiment import World
from tests.test_batch_wiring import MEASUREMENT, SMOKE, _layout
from tests.test_serverless_workload import FakeCompleted, aggregate

POSIX = os.name == "posix"


class OutcomeRunner:
    """Thread-safe evaluator fake: nominal succeeds, masked episodes fail, evidence is real-shaped."""

    def __init__(self, *, returncode=0, drift=False, missing_media=False, raise_error=None, world=None):
        self.returncode = returncode
        self.drift = drift
        self.missing_media = missing_media
        self.raise_error = raise_error
        self.world = world
        self.lock = threading.Lock()
        self.calls = []

    def __call__(self, command, *, cwd, check=False):
        config = yaml.safe_load(Path(command[-1]).read_text(encoding="utf-8"))
        with self.lock:
            self.calls.append(command[-1])
        if self.raise_error is not None:
            raise self.raise_error
        output = Path(config["output_dir"])
        output.mkdir(parents=True)
        masked = "agentview_occlusion" in config["benchmarks"][0]["params"]
        payload = aggregate(success=self.drift or not masked)
        (output / "pilot_aggregate.json").write_text(json.dumps(payload), encoding="utf-8")
        media = output / "episodes" / "pilot"
        media.mkdir(parents=True)
        if not self.missing_media:
            (media / "task0000_ep0000_fixture.mp4").write_bytes(b"mp4")
            (media / "task0000_ep0000_fixture.jsonl").write_text('{"step":0}\n', encoding="utf-8")
        return FakeCompleted(self.returncode)


class BatchWorkloadTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = WorkloadPaths(*(root / n for n in ("project", "upstream", "work", "export")))
        for path in (self.paths.project_root, self.paths.upstream_root, self.paths.work_root,
                     self.paths.export_root):
            path.mkdir()
        self.exports = []
        self.progress_events = []

    def invoke(self, config, *, world=None, runner=None, parity=None, absolute_deadline=None,
               exporter=None):
        world = world or World(item_seconds=0.0)
        runner = runner or OutcomeRunner()
        factory_calls = []

        def evaluator_factory(**kwargs):
            factory_calls.append(kwargs)
            return runner

        def recording_exporter(source, destination, **kwargs):
            world.events.append("export")
            self.exports.append((Path(source), Path(destination), kwargs))
            return {"ok": True}

        summary = run_workload(
            config,
            paths=self.paths,
            model_factory=world.model_factory,
            evaluator_factory=evaluator_factory,
            exporter=exporter or recording_exporter,
            clock=time.monotonic,
            absolute_deadline=absolute_deadline,
            parity_runner=parity,
            progress=lambda event, **fields: self.progress_events.append((event, fields)),
        )
        return summary, world, runner, factory_calls

    @staticmethod
    def passing_parity(**_kwargs):
        return {"passed": True, "max_abs_diff": 0.01, "tolerance": 0.05}

    def batch_summary(self, config):
        path = self.paths.work_root / config["run_id"] / "m3-batch" / "batch_summary.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_smoke_runs_parity_then_one_batched_phase_and_exports_after_close(self) -> None:
        summary, world, runner, factory_calls = self.invoke(SMOKE, parity=self.passing_parity)
        self.assertEqual(("complete", "completed"), (summary["status"], summary["stop_reason"]))
        self.assertEqual("m3-batch-smoke", summary["mode"])
        self.assertEqual("incomplete", summary["batch_verdict"])  # one phase cannot make a comparison
        self.assertEqual(1, summary["batch_phases_complete"])
        self.assertEqual(
            [("start", 4), ("close", 4), "export"],
            [e for e in world.events if e == "export" or e[0] in ("start", "close")],
        )
        self.assertLess(world.events.index(("close", 4)), world.events.index("export"))
        self.assertEqual(5, len(runner.calls))  # four items and one warm-up
        self.assertEqual("complete", self.exports[0][2]["status"])
        detail = self.batch_summary(SMOKE)
        self.assertTrue(detail["smoke"]["passed"])
        self.assertEqual(["nominal", "mask"], sorted(detail["phases"][0]["outcomes_by_kind"], reverse=True))
        timing_log = world.models[0].kwargs["timing_log"]
        self.assertTrue(str(timing_log).endswith("m3-batch/phase-01-w04-b04/server-timing.jsonl")
                        or str(timing_log).endswith("m3-batch\\phase-01-w04-b04\\server-timing.jsonl"))

    def test_the_generic_model_start_is_skipped_for_batch_modes(self) -> None:
        _summary, world, _runner, _calls = self.invoke(SMOKE, parity=self.passing_parity)
        self.assertEqual(1, len(world.models))
        self.assertEqual("faultline", world.models[0].kwargs["server"])

    def test_every_evaluator_gets_the_cancel_event_and_a_bounded_timeout(self) -> None:
        _summary, _world, _runner, factory_calls = self.invoke(SMOKE, parity=self.passing_parity)
        self.assertEqual(5, len(factory_calls))
        for call in factory_calls:
            self.assertIsInstance(call["cancel"], threading.Event)
            self.assertLessEqual(call["timeout_seconds"], 480.0)
            self.assertEqual(self.paths.work_root / SMOKE["run_id"] / "logs", call["log_root"])

    def test_parity_failure_is_partial_and_starts_no_server_or_evaluator(self) -> None:
        summary, world, runner, _calls = self.invoke(
            SMOKE, parity=lambda **_k: {"passed": False, "max_abs_diff": 0.4, "error": None}
        )
        self.assertEqual(("partial", "parity_failed"), (summary["status"], summary["stop_reason"]))
        self.assertEqual("parity_failed", summary["batch_verdict"])
        self.assertEqual([], world.models)
        self.assertEqual([], runner.calls)
        self.assertEqual("partial", self.exports[0][2]["status"])
        self.assertFalse(self.batch_summary(SMOKE)["smoke"]["passed"])

    def test_missing_parity_runner_fails_closed(self) -> None:
        summary, world, _runner, _calls = self.invoke(SMOKE, parity=None)
        self.assertEqual("partial", summary["status"])
        self.assertEqual([], world.models)

    def test_measurement_runs_each_phase_over_the_full_manifest(self) -> None:
        config = dict(MEASUREMENT, run_id="m3-batch-measure-a", phases=[[4, 1], [4, 4]])
        summary, world, runner, _calls = self.invoke(config)
        self.assertEqual(("complete", "completed"), (summary["status"], summary["stop_reason"]))
        self.assertEqual(2, summary["batch_phases_complete"])
        self.assertEqual(49, len(runner.calls))  # 2 x 24 items and one warm-up
        detail = self.batch_summary(config)
        self.assertEqual(24, detail["items_per_phase"])
        self.assertEqual(["compared"], [c["status"] for c in detail["comparisons"]])
        self.assertIn(detail["verdict"], ("works", "no_measurable_gain"))
        self.assertIsNone(detail["parity"])
        for phase in detail["phases"]:
            self.assertEqual(24, phase["valid_count"])
            self.assertEqual({"success": 12}, phase["outcomes_by_kind"]["nominal"])
            self.assertEqual({"policy_failure": 12}, phase["outcomes_by_kind"]["mask"])
        self.assertEqual(1, world.max_live)

    def test_outcome_drift_is_a_complete_run_with_a_drift_verdict(self) -> None:
        config = dict(MEASUREMENT, run_id="m3-batch-measure-drift", phases=[[4, 1], [4, 4]])
        summary, _world, _runner, _calls = self.invoke(config, runner=OutcomeRunner(drift=True))
        self.assertEqual("complete", summary["status"])
        self.assertEqual("outcome_drift", summary["batch_verdict"])
        self.assertEqual(12, len(self.batch_summary(config)["phases"][0]["drift_ids"]))

    def test_nonzero_evaluator_latches_partial_cancels_and_skips_later_phases(self) -> None:
        config = dict(MEASUREMENT, run_id="m3-batch-measure-fail", phases=[[4, 1], [4, 4]])
        summary, world, _runner, _calls = self.invoke(config, runner=OutcomeRunner(returncode=3))
        self.assertEqual(("partial", "evaluator_failed"), (summary["status"], summary["stop_reason"]))
        self.assertEqual(1, len(world.models))
        self.assertIn(("close", 1), world.events)
        self.assertLess(world.events.index(("close", 1)), world.events.index("export"))
        detail = self.batch_summary(config)
        self.assertEqual(["incomplete", "not_run"], [p["status"] for p in detail["phases"]])
        self.assertEqual("partial", self.exports[0][2]["status"])

    def test_missing_media_is_invalid_evidence(self) -> None:
        config = dict(SMOKE, run_id="m3-batch-smoke-media")
        summary, _world, _runner, _calls = self.invoke(
            config, runner=OutcomeRunner(missing_media=True), parity=self.passing_parity
        )
        self.assertEqual(("partial", "invalid_evidence"), (summary["status"], summary["stop_reason"]))

    def test_a_cancelled_evaluator_is_not_cleanup_uncertainty(self) -> None:
        config = dict(SMOKE, run_id="m3-batch-smoke-cancel")
        summary, _world, _runner, _calls = self.invoke(
            config, runner=OutcomeRunner(raise_error=EvaluatorCancelled()), parity=self.passing_parity
        )
        self.assertEqual(("partial", "phase_incomplete"), (summary["status"], summary["stop_reason"]))
        self.assertEqual(1, len(self.exports), "cancellation confirmed the group, so export proceeds")

    def test_unconfirmed_server_cleanup_never_exports(self) -> None:
        config = dict(SMOKE, run_id="m3-batch-smoke-close")
        world = World(item_seconds=0.0, model_fail="close")
        summary, _world, _runner, _calls = self.invoke(config, world=world, parity=self.passing_parity)
        self.assertEqual(("partial", "cleanup_unconfirmed"), (summary["status"], summary["stop_reason"]))
        self.assertEqual([], self.exports)

    def test_prefetch_hook_runs_once_before_parity_with_the_run_log_root(self) -> None:
        order = []

        class Factory:
            def __init__(self, world):
                self.world = world

            def __call__(self, **kwargs):
                order.append("model")
                return self.world.model_factory(**kwargs)

            def prefetch(self, *, log_root):
                order.append(("prefetch", log_root))

        world = World(item_seconds=0.0)
        config = dict(SMOKE, run_id="m3-batch-smoke-prefetch")

        def parity(**kwargs):
            order.append("parity")
            return {"passed": True}

        summary = run_workload(
            config, paths=self.paths, model_factory=Factory(world),
            evaluator_factory=lambda **_k: OutcomeRunner(), exporter=lambda *a, **k: {"ok": True},
            clock=time.monotonic, parity_runner=parity,
        )
        self.assertEqual("complete", summary["status"])
        self.assertEqual(
            [("prefetch", self.paths.work_root / config["run_id"] / "logs"), "parity", "model"], order
        )
        detail = self.batch_summary(config)
        self.assertIsNotNone(detail["prefetch_seconds"])

    def test_unconfirmed_parity_group_cleanup_latches_and_never_exports(self) -> None:
        config = dict(SMOKE, run_id="m3-batch-smoke-parity-cleanup")

        def unconfirmed(**_kwargs):
            raise CleanupUnconfirmed("group")

        summary, world, _runner, _calls = self.invoke(config, parity=unconfirmed)
        self.assertEqual(("partial", "cleanup_unconfirmed"), (summary["status"], summary["stop_reason"]))
        self.assertEqual([], self.exports)
        self.assertEqual([], world.models)
        run_root = self.paths.work_root / config["run_id"] / "m3-batch"
        self.assertTrue((run_root / "parity.json").is_file())
        self.assertTrue((run_root / "batch_summary.json").is_file())

    def test_item_timeout_shortened_by_the_job_deadline_is_deadline_exhausted(self) -> None:
        config = dict(SMOKE, run_id="m3-batch-smoke-late-item")
        skew = {"seconds": 0.0, "calls": 0}

        def shorten_after_the_start_gate():
            # call 1 is the phase's own liveness check; call 2 is the first item's, after its gate
            skew["calls"] += 1
            if skew["calls"] == 2:
                skew["seconds"] = 5.0

        world = World(item_seconds=0.0, on_check_alive=shorten_after_the_start_gate)

        def clock():
            return time.monotonic() + skew["seconds"]

        runner = OutcomeRunner(raise_error=subprocess.TimeoutExpired(["vla-eval"], 1))
        summary = run_workload(
            config, paths=self.paths, model_factory=world.model_factory,
            evaluator_factory=lambda **_k: runner, exporter=lambda *a, **k: {"ok": True},
            clock=clock, absolute_deadline=clock() + 14.0 + 301.0, parity_runner=self.passing_parity,
        )
        self.assertEqual(("partial", "deadline_exhausted"), (summary["status"], summary["stop_reason"]))
        # the first item to run is the warm-up; it is the one cut short by the deadline
        self.assertEqual("timed_out", self.batch_summary(config)["warmup"]["status"])

    def test_a_killed_evaluators_leftover_companions_do_not_block_the_real_export(self) -> None:
        config = dict(MEASUREMENT, run_id="m3-batch-measure-companions", phases=[[4, 1]])
        world = World(timeout_case="nominal-01", leave_companions=True, item_seconds=0.02)

        class WorldRunner:
            """Adapts the fake world's killer to the evaluator-runner interface."""

            def __call__(self, command, *, cwd, check=False):
                config_path = Path(command[-1])
                case = config_path.stem
                output = config_path.parent.parent / "runs" / case
                output.mkdir(parents=True, exist_ok=True)
                (output / "recording.sqlite").write_bytes(b"x")
                (output / "recording.sqlite-wal").write_bytes(b"x")
                (output / "recording.sqlite-shm").write_bytes(b"x")
                if case == "nominal-01":
                    raise subprocess.TimeoutExpired(command, 1)
                import shutil
                shutil.rmtree(str(output))
                return OutcomeRunner()(command, cwd=cwd, check=check)

        summary = run_workload(
            config, paths=self.paths, model_factory=world.model_factory,
            evaluator_factory=lambda **_k: WorldRunner(), clock=time.monotonic,
        )
        self.assertEqual("partial", summary["status"])
        exported = self.paths.export_root / config["run_id"]
        self.assertTrue((exported / "manifest.json").is_file(), "the real exporter must have succeeded")
        self.assertFalse(list(exported.rglob("*.sqlite-*")))

    def test_a_short_deadline_skips_the_phase_instead_of_starting_it(self) -> None:
        config = dict(SMOKE, run_id="m3-batch-smoke-late")
        summary, world, runner, _calls = self.invoke(
            config, parity=self.passing_parity, absolute_deadline=time.monotonic() + 100
        )
        self.assertEqual(("partial", "deadline_exhausted"), (summary["status"], summary["stop_reason"]))
        self.assertEqual([], world.models)
        self.assertEqual([], runner.calls)
        self.assertEqual(["deadline_skipped"], [p["status"] for p in self.batch_summary(config)["phases"]])

    def test_progress_events_cover_parity_phases_and_summary(self) -> None:
        self.invoke(SMOKE, parity=self.passing_parity)
        names = [event for event, _ in self.progress_events]
        self.assertEqual(
            ["batch_parity_start", "batch_parity_done", "batch_phase_start", "batch_warmup_done",
             "batch_phase_done", "batch_summary"],
            names,
        )

    def test_exported_batch_evidence_is_closed_and_numeric(self) -> None:
        config = dict(SMOKE, run_id="m3-batch-smoke-real-export")
        world = World(item_seconds=0.0)
        summary = run_workload(
            config, paths=self.paths, model_factory=world.model_factory,
            evaluator_factory=lambda **_k: OutcomeRunner(), clock=time.monotonic,
            parity_runner=self.passing_parity,
        )
        self.assertEqual("complete", summary["status"])
        exported = self.paths.export_root / config["run_id"]
        names = {p.relative_to(exported).as_posix() for p in exported.rglob("*") if p.is_file()}
        self.assertIn("m3-batch/batch_summary.json", names)
        self.assertIn("m3-batch/phase-01-w04-b04/server-timing.jsonl", names)
        self.assertIn("manifest.json", names)


class DirectEvaluatorCancelTests(unittest.TestCase):
    def evaluator(self, cancel, timeout=5.0):
        return DirectEvaluator(executable="/bin/evaluator", timeout_seconds=timeout, env={},
                               log_root=tempfile.gettempdir(), cancel=cancel)

    def test_without_cancel_the_single_wait_is_unchanged(self) -> None:
        process = mock.Mock()
        process.wait.return_value = 0
        self.assertEqual(0, self.evaluator(None, 9.0)._wait(process))
        process.wait.assert_called_once_with(timeout=9.0)

    def test_with_cancel_the_exit_code_is_returned_when_the_process_ends(self) -> None:
        process = mock.Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired("x", 0.2), 3]
        self.assertEqual(3, self.evaluator(threading.Event())._wait(process))

    def test_set_cancel_raises_before_waiting_again(self) -> None:
        cancel = threading.Event()
        cancel.set()
        process = mock.Mock()
        with self.assertRaises(EvaluatorCancelled):
            self.evaluator(cancel)._wait(process)
        process.wait.assert_not_called()

    def test_cancel_during_the_wait_is_noticed_within_a_poll_interval(self) -> None:
        cancel = threading.Event()
        process = mock.Mock()

        def wait(timeout):
            cancel.set()
            raise subprocess.TimeoutExpired("x", timeout)

        process.wait.side_effect = wait
        with self.assertRaises(EvaluatorCancelled):
            self.evaluator(cancel)._wait(process)

    def test_timeout_still_applies_with_a_cancel_event(self) -> None:
        process = mock.Mock()
        process.args = ["x"]
        process.wait.side_effect = subprocess.TimeoutExpired("x", 0.2)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.evaluator(threading.Event(), timeout=0.3)._wait(process)

    def test_evaluator_factory_forwards_cancel_only_when_given(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = _layout(Path(temporary))
            build = job_entry.evaluator_factory(layout, {})
            plain = build(timeout_seconds=5, log_root=layout.work_root / "logs")
            self.assertIsNone(plain.evaluator._cancel)
            cancel = threading.Event()
            cancellable = build(timeout_seconds=5, log_root=layout.work_root / "logs", cancel=cancel)
            self.assertIs(cancel, cancellable.evaluator._cancel)

    @unittest.skipUnless(POSIX, "needs real POSIX process groups")
    def test_cancel_terminates_the_real_process_group_and_confirms_absence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "evaluator"
            script.write_text("#!/bin/sh\nsleep 60 &\nwait\n", encoding="utf-8")
            script.chmod(0o755)
            cancel = threading.Event()
            evaluator = DirectEvaluator(executable=script, timeout_seconds=60, env={"PATH": os.environ["PATH"]},
                                        log_root=root / "logs", cancel=cancel)
            threading.Timer(0.5, cancel.set).start()
            started = time.monotonic()
            with self.assertRaises(EvaluatorCancelled):
                evaluator(["vla-eval", "run", "--config", str(root / "c.yaml")], cwd=root)
            self.assertLess(time.monotonic() - started, 15)


class ParityLaunchTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.layout = _layout(self.root)
        self.run_root = self.layout.work_root / "run"
        (self.run_root / "logs").mkdir(parents=True)
        self.output = self.run_root / "m3-batch" / "parity.json"
        self.output.parent.mkdir()
        self.prefetches = []
        patcher = mock.patch.object(
            job_entry, "prefetch_models",
            side_effect=lambda layout, **kw: self.prefetches.append(kw) or {"repositories": {}},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.factory = ProductionModelFactory(
            self.layout, base_env={"HF_TOKEN": "hf_value", "PATH": "/bin"}, deadline=100_000.0,
            clock=lambda: 0.0,
        )

    def run_parity(self, verdict, returncode, *, wait=None):
        if verdict is not None:
            self.output.write_text(json.dumps(verdict), encoding="utf-8")
        process = mock.Mock(pid=4242)
        process.wait.side_effect = wait or (lambda timeout: returncode)
        with mock.patch.object(job_entry, "_require_posix"), \
                mock.patch.object(job_entry.subprocess, "Popen", return_value=process) as popen, \
                mock.patch.object(job_entry, "close_owned_process_group") as close:
            result = self.factory.run_parity(
                output=self.output, log_root=self.run_root / "logs", max_batch_size=4, timeout_seconds=300
            )
        return result, popen, close, process

    def test_launch_command_environment_and_cleanup(self) -> None:
        result, popen, close, _process = self.run_parity({"passed": True, "max_abs_diff": 0.01}, 0)
        self.assertTrue(result["passed"])
        (argv,), kwargs = popen.call_args
        self.assertEqual(str(self.layout.model_python), argv[0])
        self.assertEqual(
            str(self.layout.project_root / "scripts" / "model_servers" / "groot_batch_parity.py"), argv[1]
        )
        self.assertIn("--args.max_batch_size=4", argv)
        self.assertIn("--args.policy_type=groot", argv)
        self.assertNotIn("--port=8000", argv)
        self.assertEqual("--output=" + self.output.as_posix(), argv[-1])
        self.assertTrue(kwargs["start_new_session"])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(str(self.layout.upstream_root), kwargs["cwd"])
        self.assertNotIn("HF_TOKEN", kwargs["env"])
        self.assertEqual("1", kwargs["env"]["HF_HUB_OFFLINE"])
        close.assert_called_once()
        self.assertEqual(1, len(self.prefetches), "parity needs the prefetched cache")

    def test_failed_check_returns_its_verdict(self) -> None:
        result, *_ = self.run_parity({"passed": False, "error": None, "max_abs_diff": 0.3}, 1)
        self.assertFalse(result["passed"])

    def test_crash_missing_or_inconsistent_verdicts_are_infrastructure_errors(self) -> None:
        cases = (
            ({"passed": False}, 2),
            (None, 1),
            ({"passed": True}, 1),
            ({"passed": False}, 0),
            ([1], 0),
        )
        for verdict, code in cases:
            with self.subTest(verdict=verdict, code=code):
                if self.output.exists():
                    self.output.unlink()
                with self.assertRaises(InfrastructureError):
                    self.run_parity(verdict, code)

    def test_timeout_closes_the_group_and_becomes_an_infrastructure_error(self) -> None:
        def hang(timeout):
            raise subprocess.TimeoutExpired("parity", timeout)

        process = mock.Mock(pid=4242)
        process.wait.side_effect = hang
        with mock.patch.object(job_entry, "_require_posix"), \
                mock.patch.object(job_entry.subprocess, "Popen", return_value=process), \
                mock.patch.object(job_entry, "close_owned_process_group") as close:
            with self.assertRaisesRegex(InfrastructureError, "timed out") as raised:
                self.factory.run_parity(
                    output=self.output, log_root=self.run_root / "logs", max_batch_size=4, timeout_seconds=1
                )
        self.assertNotIsInstance(raised.exception, subprocess.TimeoutExpired)
        close.assert_called_once()

    def test_an_unconfirmable_group_is_cleanup_unconfirmed(self) -> None:
        process = mock.Mock(pid=4242)
        process.wait.return_value = 0
        self.output.write_text(json.dumps({"passed": True}), encoding="utf-8")
        with mock.patch.object(job_entry, "_require_posix"), \
                mock.patch.object(job_entry.subprocess, "Popen", return_value=process), \
                mock.patch.object(job_entry, "close_owned_process_group",
                                  side_effect=InfrastructureError("stuck")):
            with self.assertRaises(CleanupUnconfirmed):
                self.factory.run_parity(
                    output=self.output, log_root=self.run_root / "logs", max_batch_size=4, timeout_seconds=5
                )

    def test_a_prefetch_timeout_inside_parity_is_an_infrastructure_error(self) -> None:
        with mock.patch.object(job_entry, "_require_posix"), \
                mock.patch.object(job_entry, "prefetch_models",
                                  side_effect=subprocess.TimeoutExpired("prefetch", 1)):
            with self.assertRaisesRegex(InfrastructureError, "prefetch timed out"):
                self.factory.run_parity(
                    output=self.output, log_root=self.run_root / "logs", max_batch_size=4, timeout_seconds=5
                )

    def test_batch_prefetch_hook_prefetches_once_and_records_the_faultline_server(self) -> None:
        self.factory.prefetch(log_root=self.run_root / "logs")
        self.factory.prefetch(log_root=self.run_root / "logs")
        self.assertEqual(1, len(self.prefetches))
        provenance = json.loads((self.run_root / "provenance.json").read_text(encoding="utf-8"))
        self.assertIn("faultline_groot_server.py", provenance["model_server_argv"][0])

    @unittest.skipIf(POSIX, "Windows-only fail-closed check")
    def test_non_posix_hosts_fail_closed(self) -> None:
        with self.assertRaises(InfrastructureError):
            self.factory.run_parity(
                output=self.output, log_root=self.run_root / "logs", max_batch_size=4, timeout_seconds=1
            )

    @unittest.skipUnless(POSIX, "real parity process")
    def test_real_process_round_trip(self) -> None:
        scripts = self.layout.project_root / "scripts" / "model_servers"
        scripts.mkdir(parents=True)
        (scripts / "groot_batch_parity.py").write_text(
            "import json, sys\n"
            "out = [a for a in sys.argv if a.startswith('--output=')][0].split('=', 1)[1]\n"
            "open(out, 'w').write(json.dumps({'passed': True, 'max_abs_diff': 0.0}))\n",
            encoding="utf-8",
        )
        result = self.factory.run_parity(
            output=self.output, log_root=self.run_root / "logs", max_batch_size=4, timeout_seconds=60
        )
        self.assertTrue(result["passed"])


class MainWiringTests(unittest.TestCase):
    def test_main_hands_the_runner_a_parity_launcher_and_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = _layout(root)
            config = root / "workload.json"
            config.write_text(json.dumps(SMOKE), encoding="utf-8")
            captured = {}

            def runner(config_value, **kwargs):
                captured.update(kwargs)
                return {"status": "complete", "run_id": config_value["run_id"]}

            def direct(argv, **_kwargs):
                return job_entry.export_preflight(layout, json.loads(argv[-1])["run_id"])

            # The export preflight is not under test here; run it in-process everywhere.
            with mock.patch.object(job_entry, "_run_preflight_process", side_effect=direct):
                code = job_entry.main(
                    ["--config", str(config)], layout=layout, environ={"HF_TOKEN": "hf_value"},
                    runner=runner, stdout=io.StringIO(),
                )
        self.assertEqual(0, code)
        factory = captured["model_factory"]
        self.assertIsInstance(factory, ProductionModelFactory)
        self.assertEqual(factory.run_parity, captured["parity_runner"])
        self.assertTrue(callable(captured["progress"]))


if __name__ == "__main__":
    unittest.main()
