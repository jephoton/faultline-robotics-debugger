import importlib.util
import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from robot_debug.parallel_eval import summarize_modes
from robot_debug.attempt_ledger import AttemptLedger
from robot_debug.parallel_eval import build_manifest, manifest_hash


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_parallel_eval.py"
SPEC = importlib.util.spec_from_file_location("run_parallel_eval", SCRIPT_PATH)
runner_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner_module
SPEC.loader.exec_module(runner_module)


def aggregate(*, success=True, episode_index=0, task_id=0):
    return {"tasks": [{"task_id": task_id, "episodes": [{
        "task_id": task_id, "episode_idx": episode_index, "metrics": {"success": success},
        "steps": 3, "elapsed_sec": 0.1,
    }]}]}


class FakeEvaluator:
    def __init__(self, *, barrier_size=1, response=None):
        self.barrier_size = barrier_size
        self.response = response or (lambda _: (0, aggregate()))
        self.lock = threading.Lock()
        self.active = self.maximum_active = 0
        self.commands = []
        self.ready = threading.Event()

    def __call__(self, argv, *, cwd, check, timeout):
        config = Path(argv[-1])
        output = next(Path(json.loads(line.split(": ", 1)[1])) for line in config.read_text().splitlines() if line.startswith("output_dir: "))
        with self.lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.commands.append((argv, cwd, check, timeout, config, output))
            if self.active >= self.barrier_size:
                self.ready.set()
        if self.barrier_size > 1:
            self.ready.wait(2)
        time.sleep(.005)
        try:
            code, evidence = self.response(len(self.commands))
            output.mkdir(parents=True, exist_ok=True)
            if evidence is not None:
                (output / "fake_aggregate.json").write_text(json.dumps(evidence), encoding="utf-8")
            return SimpleNamespace(returncode=code)
        finally:
            with self.lock:
                self.active -= 1


class ParallelEvalDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.upstream = self.root / "upstream"; self.upstream.mkdir()
        self.project = self.root / "project"; self.project.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def run_mode(self, fake, *, workers=1, results=None, clock=time.monotonic, cutoff=60):
        return runner_module.run_mode(upstream_root=self.upstream, project_root=self.project,
            results_root=results or self.root / "results", workers=workers, repeats_per_case=8,
            launch_cutoff_seconds=cutoff, item_timeout_seconds=5, command_runner=fake,
            monotonic_clock=clock)

    def write_safe_partial_session(self, results, *, workers=1):
        items = build_manifest(8)
        session = results / f"m3-workers-{workers}"
        (session / "configs").mkdir(parents=True)
        (session / "runs").mkdir()
        (session / "launches").mkdir()
        (session / "manifest.json").write_text(
            json.dumps(items, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        ledger = AttemptLedger([item["case_id"] for item in items])
        first = items[0]
        terminal = {"case_id": first["case_id"], "kind": first["kind"], "task_id": 0,
            "episode_index": 0, "status": "valid", "outcome": "success", "replayable": False}
        ledger.begin_submit(first["case_id"])
        ledger.register_active(first["case_id"])
        ledger.capture_result(first["case_id"], terminal, interrupted=False)
        ledger.finish(first["case_id"])
        summary = {
            "workers": workers, "manifest_hash": manifest_hash(items), "manifest_path": "manifest.json",
            "case_ids": [item["case_id"] for item in items], "planned_ids": [item["case_id"] for item in items],
            "cost_usd": None, "elapsed_seconds": 2.5, "stop_reason": "partial", **ledger.snapshot(),
        }
        (session / "session_summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return session, summary

    def test_runs_unique_cases_with_bounded_concurrency_and_reportable_records(self):
        records = []
        for workers in (1, 2, 4):
            fake = FakeEvaluator(barrier_size=workers)
            record = self.run_mode(fake, workers=workers, results=self.root / f"results-{workers}")
            records.append(record)
            self.assertLessEqual(fake.maximum_active, workers)
            self.assertEqual(16, len(fake.commands))
            self.assertEqual(16, len({call[4] for call in fake.commands}))
            self.assertEqual(16, len({call[5] for call in fake.commands}))
            self.assertEqual(16, record["valid_count"])
            self.assertEqual([], record["in_flight_ids"])
            self.assertEqual(16, len(record["attempt_states"]))
            self.assertTrue(all(state == "terminal" for state in record["attempt_states"].values()))
            self.assertIsNone(record["cost_usd"])
            self.assertTrue(all(result["task_id"] == result["episode_index"] == 0 for result in record["results"]))
        self.assertEqual([1, 2, 4], [row["workers"] for row in summarize_modes(records)])

    def test_successful_attempt_records_owned_evaluator_identity(self):
        fake = FakeEvaluator()

        def identified_runner(*args, **kwargs):
            result = fake(*args, **kwargs)
            result.evaluator_pid = 31337
            result.expected_container = "vla-eval-31337"
            return result

        record = self.run_mode(identified_runner, results=self.root / "identified-success")
        self.assertEqual(16, record["valid_count"])
        self.assertTrue(all(result["evaluator_pid"] == 31337 for result in record["results"]))
        self.assertTrue(all(result["expected_container"] == "vla-eval-31337" for result in record["results"]))

    def test_launch_observer_receives_exact_identity_before_wait_finishes(self):
        observer_called = threading.Event()
        release_observer = threading.Event()
        wait_started = threading.Event()
        release_wait = threading.Event()
        finished = threading.Event()
        observations = []
        errors = []

        class Process:
            pid = 9137
            returncode = None

            def wait(self, timeout):
                wait_started.set()
                release_wait.wait(2)
                self.returncode = 0
                return 0

        def observer(pid, container):
            observations.append((pid, container))
            observer_called.set()
            release_observer.wait(2)

        def run():
            try:
                runner_module._run_evaluator_safely(
                    ["vla-eval"], cwd=self.upstream, check=False, timeout=5,
                    process_factory=lambda *args, **kwargs: Process(),
                    launch_observer=observer,
                )
            except BaseException as error:
                errors.append(error)
            finally:
                finished.set()

        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(observer_called.wait(2))
            self.assertEqual([(9137, "vla-eval-9137")], observations)
            self.assertFalse(wait_started.is_set(), "observer must run before wait")
            self.assertFalse(finished.is_set(), "wait must still be blocking")
        finally:
            release_observer.set()
            release_wait.set()
            thread.join(2)
        self.assertEqual([], errors)

    def test_launch_observer_failure_uses_cleanup_and_surfaces_uncertainty(self):
        cleanup_calls = []

        class Process:
            pid = 9138
            returncode = None

            def wait(self, timeout):
                self.returncode = 143
                return self.returncode

            def terminate(self):
                cleanup_calls.append("terminate")

        def docker(*args, **kwargs):
            cleanup_calls.append(args[0][1])
            return SimpleNamespace(returncode=1, stdout="", stderr="daemon unavailable")

        with self.assertRaisesRegex(RuntimeError, "sidecar write failed") as raised:
            runner_module._run_evaluator_safely(
                ["vla-eval"], cwd=self.upstream, check=False, timeout=5,
                process_factory=lambda *args, **kwargs: Process(), docker_runner=docker,
                launch_observer=lambda pid, container: (_ for _ in ()).throw(RuntimeError("sidecar write failed")),
            )

        self.assertEqual(9138, raised.exception.evaluator_pid)
        self.assertEqual("vla-eval-9138", raised.exception.expected_container)
        self.assertFalse(raised.exception.cleanup_confirmed)
        self.assertIn("Docker inspection failed", raised.exception.cleanup_error)
        self.assertTrue(cleanup_calls)

    def test_production_runner_persists_launch_identity_sidecars_before_evidence(self):
        results = self.root / "launch-sidecars"
        observed_sidecars = []

        def launched_runner(argv, *, cwd, check, timeout, launch_observer, **kwargs):
            config = Path(argv[-1])
            case_id = config.stem
            launch_observer(7000 + len(observed_sidecars), f"vla-eval-{7000 + len(observed_sidecars)}")
            sidecar = results / "m3-workers-1" / "launches" / f"{case_id}.json"
            observed_sidecars.append(json.loads(sidecar.read_text(encoding="utf-8")))
            output = next(Path(json.loads(line.split(": ", 1)[1])) for line in config.read_text().splitlines()
                if line.startswith("output_dir: "))
            output.mkdir(parents=True, exist_ok=True)
            (output / "fake_aggregate.json").write_text(json.dumps(aggregate()), encoding="utf-8")
            return SimpleNamespace(returncode=0)

        with patch.object(runner_module, "_run_evaluator_safely", side_effect=launched_runner):
            record = runner_module.run_mode(
                upstream_root=self.upstream, project_root=self.project, results_root=results,
                workers=1, repeats_per_case=8, launch_cutoff_seconds=60, item_timeout_seconds=5,
            )

        self.assertEqual(16, record["valid_count"])
        self.assertEqual(16, len(observed_sidecars))
        self.assertEqual(
            {"schema_version", "case_id", "evaluator_pid", "expected_container"},
            set(observed_sidecars[0]),
        )
        self.assertEqual("nominal-01", observed_sidecars[0]["case_id"])
        self.assertEqual(7000, observed_sidecars[0]["evaluator_pid"])
        self.assertEqual("vla-eval-7000", observed_sidecars[0]["expected_container"])

    def test_bad_attempts_stop_new_launches_and_remain_nonvalid(self):
        cases = {
            "nonzero": lambda _: (9, aggregate()),
            "missing": lambda _: (0, None),
            "wrong-index": lambda _: (0, aggregate(episode_index=1)),
            "timeout": lambda _: (_ for _ in ()).throw(subprocess.TimeoutExpired("vla-eval", 5)),
        }
        for name, response in cases.items():
            with self.subTest(name=name):
                fake = FakeEvaluator(response=response)
                record = self.run_mode(fake, results=self.root / name)
                self.assertEqual(1, len(fake.commands))
                self.assertEqual(0, record["valid_count"])
                self.assertEqual(1, len(record["results"]))
                self.assertIn(record["results"][0]["status"], {"infrastructure_error", "invalid_evidence"})
                self.assertTrue(record["stop_reason"])
                self.assertEqual("terminal", record["attempt_states"]["nominal-01"])
                self.assertTrue(all(state == "prepared" for case_id, state in record["attempt_states"].items()
                    if case_id != "nominal-01"))
                if name == "timeout":
                    self.assertFalse(record["results"][0]["cleanup_confirmed"])
                    self.assertIn("cleanup risk", record["results"][0]["infrastructure_error"])

    def test_each_atomic_summary_is_derived_from_its_attempt_ledger(self):
        saved = []
        original_write = runner_module.base._atomic_write_json

        def capture_write(path, value):
            if path.name == "session_summary.json":
                saved.append(json.loads(json.dumps(value)))
            return original_write(path, value)

        with patch.object(runner_module.base, "_atomic_write_json", side_effect=capture_write):
            record = self.run_mode(FakeEvaluator(), results=self.root / "ledger-derived")

        self.assertGreater(len(saved), 1)
        self.assertEqual(record, saved[-1])
        for summary in saved:
            attempts = summary["attempt_records"]
            states = {case_id: attempt["state"] for case_id, attempt in attempts.items()}
            results = [attempt["result"] for attempt in attempts.values() if attempt["state"] == "terminal"]
            in_flight = [case_id for case_id, state in states.items()
                if state not in {"prepared", "terminal"}]
            self.assertEqual(states, summary["attempt_states"])
            self.assertEqual(results, summary["results"])
            self.assertEqual(sum(item["status"] == "valid" for item in results), summary["valid_count"])
            self.assertEqual(in_flight, summary["in_flight_ids"])

    def test_nested_task_id_mismatch_is_invalid_evidence(self):
        def nested_mismatch(_):
            evidence = aggregate()
            evidence["tasks"][0]["episodes"][0]["task_id"] = 1
            return 0, evidence

        fake = FakeEvaluator(response=nested_mismatch)
        record = self.run_mode(fake, results=self.root / "nested-task-mismatch")

        self.assertEqual(0, record["valid_count"])
        self.assertEqual("invalid_evidence", record["results"][0]["status"])

    def test_real_aggregate_without_top_level_task_id_is_valid(self):
        def response(_):
            evidence = aggregate()
            del evidence["tasks"][0]["task_id"]
            return 0, evidence

        record = self.run_mode(FakeEvaluator(response=response), results=self.root / "real-task-shape")
        self.assertEqual(16, record["valid_count"])

    def test_missing_nested_task_id_is_invalid_even_if_top_level_present(self):
        def response(_):
            evidence = aggregate()
            del evidence["tasks"][0]["episodes"][0]["task_id"]
            return 0, evidence

        record = self.run_mode(FakeEvaluator(response=response), results=self.root / "missing-nested-task")
        self.assertEqual("invalid_evidence", record["results"][0]["status"])

    def test_top_level_task_id_mismatch_is_invalid_when_present(self):
        def response(_):
            evidence = aggregate()
            evidence["tasks"][0]["task_id"] = 1
            return 0, evidence

        record = self.run_mode(FakeEvaluator(response=response), results=self.root / "top-task-mismatch")
        self.assertEqual("invalid_evidence", record["results"][0]["status"])

    def test_null_top_level_task_id_is_invalid_when_present(self):
        def response(_):
            evidence = aggregate()
            evidence["tasks"][0]["task_id"] = None
            return 0, evidence

        record = self.run_mode(FakeEvaluator(response=response), results=self.root / "null-top-task")
        self.assertEqual("invalid_evidence", record["results"][0]["status"])

    def test_nonfinite_or_nonpositive_budgets_fail_before_session_creation(self):
        for key in ("launch_cutoff_seconds", "item_timeout_seconds"):
            for value in (0, -1, True, float("nan"), float("inf"), -float("inf"), "5"):
                with self.subTest(key=key, value=value):
                    results = self.root / f"invalid-{key}-{str(value).replace('-', 'minus')}"
                    kwargs = dict(upstream_root=self.upstream, project_root=self.project,
                        results_root=results, workers=1, command_runner=FakeEvaluator(),
                        launch_cutoff_seconds=60, item_timeout_seconds=5)
                    kwargs[key] = value
                    with self.assertRaisesRegex(ValueError, key):
                        runner_module.run_mode(**kwargs)
                    self.assertFalse(results.exists())

    def test_timeout_starts_evaluator_session_and_signals_its_process_group(self):
        events = []

        class Process:
            pid = 4321
            returncode = None
            def wait(self, timeout):
                events.append(("wait", timeout))
                if len([event for event in events if event[0] == "wait"]) == 1:
                    raise subprocess.TimeoutExpired("vla-eval", timeout)
                self.returncode = 143
                return self.returncode
        def docker(argv, **kwargs):
            events.append(("docker", argv))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        def process_factory(*args, **kwargs):
            events.append(("launch", kwargs))
            return Process()

        group_alive = True
        def signal_group(pid, signum):
            nonlocal group_alive
            events.append(("signal", pid, signum))
            if signum == 0 and not group_alive:
                raise ProcessLookupError()
            if signum == signal.SIGTERM:
                group_alive = False
        with patch.object(runner_module.os, "killpg", create=True, side_effect=signal_group):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                runner_module._run_evaluator_safely(["vla-eval"], cwd=self.upstream,
                    check=False, timeout=5, process_factory=process_factory, docker_runner=docker)
        self.assertTrue(raised.exception.cleanup_confirmed)
        launches = [event[1] for event in events if event[0] == "launch"]
        self.assertEqual(1, len(launches))
        self.assertTrue(launches[0]["start_new_session"])
        self.assertIn(("signal", 4321, signal.SIGTERM), events)
        self.assertFalse(any(event[0] == "signal" and event[2] == getattr(signal, "SIGKILL", 9)
            for event in events))
        self.assertFalse(any(event[0] == "docker" and "rm" in event[1] for event in events))

    def test_timeout_escalates_owned_process_group_before_exact_container_removal(self):
        events = []

        class Process:
            pid = 5678
            returncode = None
            def wait(self, timeout):
                events.append(("wait", timeout))
                if len([event for event in events if event[0] == "wait"]) < 2:
                    raise subprocess.TimeoutExpired("vla-eval", timeout)
                self.returncode = -9
                return self.returncode

        def docker(argv, **kwargs):
            events.append(("docker", argv))
            checks = len([event for event in events if event[0] == "docker" and "ps" in event[1]])
            return SimpleNamespace(returncode=0, stdout="vla-eval-5678\n" if checks == 1 else "", stderr="")

        group_alive = True
        def signal_group(pid, signum):
            nonlocal group_alive
            events.append(("signal", pid, signum))
            if signum == 0 and not group_alive:
                raise ProcessLookupError()
            if signum == getattr(signal, "SIGKILL", 9):
                group_alive = False
        with patch.object(runner_module.os, "killpg", create=True, side_effect=signal_group):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                runner_module._run_evaluator_safely(["vla-eval"], cwd=self.upstream,
                    check=False, timeout=5, process_factory=lambda *a, **k: Process(), docker_runner=docker,
                    graceful_group_wait_seconds=0)
        self.assertTrue(raised.exception.cleanup_confirmed)
        self.assertEqual([("signal", 5678, signal.SIGTERM), ("signal", 5678, getattr(signal, "SIGKILL", 9))],
            [event for event in events if event[0] == "signal" and event[2] != 0])
        removal = ("docker", ["docker", "rm", "-f", "vla-eval-5678"])
        self.assertEqual([removal], [event for event in events if event[0] == "docker" and "rm" in event[1]])
        self.assertLess(events.index(("signal", 5678, getattr(signal, "SIGKILL", 9))), events.index(removal))

    def test_docker_inspection_exception_makes_cleanup_uncertain(self):
        class Process:
            pid = 7654
            returncode = None
            def wait(self, timeout):
                if self.returncode is None and timeout == 5:
                    raise subprocess.TimeoutExpired("vla-eval", timeout)
                self.returncode = 143
                return self.returncode
            def terminate(self):
                pass
            def kill(self):
                self.returncode = -9

        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            runner_module._run_evaluator_safely(["vla-eval"], cwd=self.upstream,
                check=False, timeout=5, process_factory=lambda *a, **k: Process(),
                docker_runner=lambda *a, **k: (_ for _ in ()).throw(OSError("daemon unavailable")))
        self.assertFalse(raised.exception.cleanup_confirmed)
        self.assertIn("Docker inspection failed", raised.exception.cleanup_error)

    def test_stuck_group_escalates_before_removing_only_its_container(self):
        events = []

        class Process:
            pid = 5678
            returncode = None
            def wait(self, timeout):
                events.append(("wait", timeout))
                if len([event for event in events if event[0] == "wait"]) < 2:
                    raise subprocess.TimeoutExpired("vla-eval", timeout)
                self.returncode = -9
                return self.returncode
        def docker(argv, **kwargs):
            events.append(("docker", argv))
            if "ps" in argv:
                checks = len([event for event in events if event[0] == "docker" and "ps" in event[1]])
                return SimpleNamespace(returncode=0, stdout="vla-eval-5678\n" if checks == 1 else "", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        group_alive = True
        def signal_group(pid, signum):
            nonlocal group_alive
            events.append(("signal", pid, signum))
            if signum == 0 and not group_alive:
                raise ProcessLookupError()
            if signum == getattr(signal, "SIGKILL", 9):
                group_alive = False
        with patch.object(runner_module.os, "killpg", create=True, side_effect=signal_group):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                runner_module._run_evaluator_safely(["vla-eval"], cwd=self.upstream,
                    check=False, timeout=5, process_factory=lambda *a, **k: Process(), docker_runner=docker,
                    graceful_group_wait_seconds=0)
        self.assertTrue(raised.exception.cleanup_confirmed)
        self.assertEqual([("signal", 5678, signal.SIGTERM), ("signal", 5678, getattr(signal, "SIGKILL", 9))],
            [event for event in events if event[0] == "signal" and event[2] != 0])
        removal = ("docker", ["docker", "rm", "-f", "vla-eval-5678"])
        self.assertEqual([removal], [event for event in events if event[0] == "docker" and "rm" in event[1]])
        self.assertLess(events.index(("signal", 5678, getattr(signal, "SIGKILL", 9))), events.index(removal))

    def test_does_not_reap_leader_before_escalating_a_surviving_group(self):
        """The leader PID must remain reserved while its group needs SIGKILL."""
        events = []
        group_alive = True

        class Process:
            pid = 9012
            returncode = None
            def wait(self, timeout):
                events.append(("wait", timeout))
                if len([event for event in events if event[0] == "wait"]) == 1:
                    raise subprocess.TimeoutExpired("vla-eval", timeout)
                self.returncode = -9
                return self.returncode

        def signal_group(pid, signum):
            nonlocal group_alive
            events.append(("signal", pid, signum))
            if signum == 0 and not group_alive:
                raise ProcessLookupError()
            if signum == getattr(signal, "SIGKILL", 9):
                group_alive = False

        with patch.object(runner_module.os, "killpg", create=True, side_effect=signal_group):
            with self.assertRaises(subprocess.TimeoutExpired):
                runner_module._run_evaluator_safely(["vla-eval"], cwd=self.upstream,
                    check=False, timeout=5, process_factory=lambda *a, **k: Process(),
                    docker_runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
                    graceful_group_wait_seconds=0)

        term = events.index(("signal", 9012, signal.SIGTERM))
        kill = events.index(("signal", 9012, getattr(signal, "SIGKILL", 9)))
        self.assertFalse(any(event[0] == "wait" for event in events[term + 1:kill]))

    def test_cleanup_observation_error_prevents_confirmation_even_when_final_inspection_is_absent(self):
        class Process:
            pid = 3457
            returncode = None
            waits = 0
            def wait(self, timeout):
                self.waits += 1
                if self.waits == 1:
                    raise subprocess.TimeoutExpired("vla-eval", timeout)
                self.returncode = 143
                return self.returncode

        inspections = 0
        def docker(argv, **kwargs):
            nonlocal inspections
            if "ps" in argv:
                inspections += 1
                if inspections == 1:
                    return SimpleNamespace(returncode=1, stdout="", stderr="first inspection failed")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(runner_module.os, "killpg", create=True, side_effect=ProcessLookupError):
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                runner_module._run_evaluator_safely(["vla-eval"], cwd=self.upstream,
                    check=False, timeout=5, process_factory=lambda *a, **k: Process(), docker_runner=docker)
        self.assertFalse(raised.exception.cleanup_confirmed)
        self.assertIn("first inspection failed", raised.exception.cleanup_error)

    def test_unconfirmed_cleanup_stops_session_and_records_risk(self):
        def risky_runner(*args, **kwargs):
            error = subprocess.TimeoutExpired("vla-eval", 5)
            error.cleanup_confirmed = False
            error.cleanup_error = "Docker daemon unavailable"
            error.evaluator_pid = 4242
            error.expected_container = "vla-eval-4242"
            raise error

        record = self.run_mode(risky_runner, results=self.root / "cleanup-risk")
        self.assertEqual("infrastructure_error", record["stop_reason"])
        self.assertEqual(1, len(record["results"]))
        self.assertFalse(record["results"][0]["cleanup_confirmed"])
        self.assertIn("Docker daemon unavailable", record["results"][0]["infrastructure_error"])
        self.assertEqual(4242, record["results"][0]["evaluator_pid"])
        self.assertEqual("vla-eval-4242", record["results"][0]["expected_container"])

    def test_timeout_requests_stop_before_graceful_cleanup_finishes(self):
        stop = threading.Event()
        cleanup_started = threading.Event()
        release_cleanup = threading.Event()
        errors = []
        events = []
        group_alive = True

        class Process:
            pid = 6789
            returncode = None
            waits = 0
            def wait(self, timeout):
                self.waits += 1
                if self.waits == 1:
                    raise subprocess.TimeoutExpired("vla-eval", timeout)
                self.returncode = 143
                return self.returncode

        def signal_group(pid, signum):
            nonlocal group_alive
            events.append((pid, signum))
            if signum == 0 and not group_alive:
                raise ProcessLookupError()
            if signum == signal.SIGTERM:
                cleanup_started.set()
                release_cleanup.wait(2)
                group_alive = False

        with patch.object(runner_module.os, "killpg", create=True, side_effect=signal_group):
            def run():
                try:
                    runner_module._run_evaluator_safely(["vla-eval"], cwd=self.upstream,
                        check=False, timeout=5, process_factory=lambda *a, **k: Process(),
                        docker_runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
                        stop_event=stop)
                except subprocess.TimeoutExpired as error:
                    errors.append(error)

            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(cleanup_started.wait(2))
                self.assertTrue(stop.is_set())
            finally:
                release_cleanup.set()
                thread.join(2)
        self.assertEqual(1, len(errors))
        self.assertTrue(errors[0].cleanup_confirmed)
        self.assertEqual([(6789, signal.SIGTERM)], [event for event in events if event[1] != 0])

    def test_stop_gate_prevents_late_process_creation(self):
        stop = threading.Event()
        stop.set()
        launches = []
        with self.assertRaises(runner_module._LaunchCancelled):
            runner_module._run_evaluator_safely(["vla-eval"], cwd=self.upstream,
                check=False, timeout=5, stop_event=stop, launch_lock=threading.Lock(),
                process_factory=lambda *a, **k: launches.append(True))
        self.assertEqual([], launches)

    def test_stop_gate_serializes_stop_with_process_creation(self):
        stop = threading.Event()
        attempting_gate = threading.Event()
        gate = threading.Lock()
        launches = []
        errors = []

        class ObservedGate:
            def __enter__(self):
                attempting_gate.set()
                gate.acquire()
            def __exit__(self, *args):
                gate.release()

        def run():
            try:
                runner_module._run_evaluator_safely(["vla-eval"], cwd=self.upstream,
                    check=False, timeout=5, stop_event=stop, launch_lock=ObservedGate(),
                    process_factory=lambda *a, **k: launches.append(True))
            except runner_module._LaunchCancelled as error:
                errors.append(error)

        gate.acquire()
        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(attempting_gate.wait(2))
            stop.set()
        finally:
            gate.release()
            thread.join(2)
        self.assertEqual([], launches)
        self.assertEqual(1, len(errors))

    def test_two_workers_do_not_launch_third_during_slow_timeout_cleanup(self):
        both_started = threading.Event()
        timeout_seen = threading.Event()
        release_cleanup = threading.Event()
        calls = []
        lock = threading.Lock()

        def fake_runner(
            argv, *, cwd, check, timeout, stop_event=None, interrupt_event=None,
            launch_lock=None, launch_observer=None,
        ):
            # This test replaces the production containment helper to control
            # its cleanup timing. It deliberately has no real PID to persist.
            self.assertIsNotNone(launch_observer)
            config = Path(argv[-1])
            output = next(Path(json.loads(line.split(": ", 1)[1])) for line in config.read_text().splitlines()
                if line.startswith("output_dir: "))
            with lock:
                calls.append(config.name)
            if config.stem == "nominal-01":
                both_started.wait(2)
                timeout_seen.set()
                if stop_event is not None:
                    with launch_lock:
                        stop_event.set()
                release_cleanup.wait(2)
                error = subprocess.TimeoutExpired("vla-eval", timeout)
                error.cleanup_confirmed = True
                raise error
            if config.stem == "nominal-02":
                both_started.set()
                timeout_seen.wait(2)
            output.mkdir(parents=True, exist_ok=True)
            (output / "fake_aggregate.json").write_text(json.dumps(aggregate()), encoding="utf-8")
            return SimpleNamespace(returncode=0)

        with patch.object(runner_module, "_run_evaluator_safely", side_effect=fake_runner):
            try:
                record = runner_module.run_mode(upstream_root=self.upstream, project_root=self.project,
                    results_root=self.root / "slow-timeout", workers=2, repeats_per_case=8,
                    launch_cutoff_seconds=60, item_timeout_seconds=5)
            finally:
                release_cleanup.set()
        self.assertEqual(2, len(calls))
        self.assertEqual("infrastructure_error", record["stop_reason"])
        self.assertEqual(2, len(record["results"]))

    def test_docker_query_failure_marks_timeout_cleanup_unconfirmed(self):
        class Process:
            pid = 3456
            returncode = None
            def wait(self, timeout):
                if self.returncode is None and timeout == 5:
                    raise subprocess.TimeoutExpired("vla-eval", timeout)
                self.returncode = 143
                return self.returncode
            def terminate(self):
                pass
            def kill(self):
                self.returncode = -9

        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            runner_module._run_evaluator_safely(["vla-eval"], cwd=self.upstream,
                check=False, timeout=5, process_factory=lambda *a, **k: Process(),
                docker_runner=lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="daemon unavailable"))
        self.assertFalse(raised.exception.cleanup_confirmed)
        self.assertIn("daemon unavailable", raised.exception.cleanup_error)

    def test_unexpected_wait_error_still_cleans_owned_container(self):
        class Process:
            pid = 2468
            returncode = None
            waits = 0
            def wait(self, timeout):
                self.waits += 1
                if self.returncode is None and self.waits == 1:
                    raise OSError("wait failed")
                self.returncode = 143
                return self.returncode
            def terminate(self):
                pass
            def kill(self):
                self.returncode = -9

        with patch.object(runner_module.os, "killpg", create=True,
                side_effect=ProcessLookupError):
            with self.assertRaises(OSError) as raised:
                runner_module._run_evaluator_safely(["vla-eval"], cwd=self.upstream,
                    check=False, timeout=5, process_factory=lambda *a, **k: Process(),
                    docker_runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
        self.assertTrue(raised.exception.cleanup_confirmed)

    def test_interrupted_wait_still_reaps_an_absent_owned_group(self):
        events = []
        class Process:
            pid = 1357
            returncode = None
            waits = 0
            def wait(self, timeout):
                self.waits += 1
                if self.waits == 1:
                    raise KeyboardInterrupt()
                self.returncode = 143
                return self.returncode
        with patch.object(runner_module.os, "killpg", create=True,
                side_effect=ProcessLookupError):
            with self.assertRaises(KeyboardInterrupt) as raised:
                runner_module._run_evaluator_safely(["vla-eval"], cwd=self.upstream,
                    check=False, timeout=5, process_factory=lambda *a, **k: Process(),
                    docker_runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
        self.assertTrue(raised.exception.cleanup_confirmed)
        self.assertEqual([], events)

    def test_main_thread_interrupt_cleans_active_processes_and_finalizes_summary(self):
        events = []
        processes = []
        both_started = threading.Event()

        class Process:
            returncode = None
            def __init__(self):
                self.pid = 8000 + len(processes)
                processes.append(self)
                if len(processes) == 2:
                    both_started.set()
            def wait(self, timeout):
                if self.returncode is None:
                    time.sleep(timeout)
                    raise subprocess.TimeoutExpired("vla-eval", timeout)
                return self.returncode
            def terminate(self):
                events.append(("terminate", self.pid))
                self.returncode = 143
            def kill(self):
                events.append(("kill", self.pid))
                self.returncode = -9

        def docker(argv, **kwargs):
            events.append(("docker", argv))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        real_wait = runner_module.wait
        interrupted = False
        def interrupt_once(futures, **kwargs):
            nonlocal interrupted
            if not interrupted:
                self.assertTrue(both_started.wait(2))
                interrupted = True
                raise KeyboardInterrupt()
            return real_wait(futures, **kwargs)

        results = self.root / "main-interrupt"
        real_evaluator = runner_module._run_evaluator_safely
        def evaluator(*args, **kwargs):
            return real_evaluator(*args, **kwargs, process_factory=lambda *a, **k: Process(), docker_runner=docker)
        def signal_group(pid, signum):
            process = next(process for process in processes if process.pid == pid)
            events.append(("signal", pid, signum))
            if signum == 0 and process.returncode is not None:
                raise ProcessLookupError()
            if signum == signal.SIGTERM:
                process.returncode = 143
        with patch.object(runner_module, "wait", side_effect=interrupt_once), \
                patch.object(runner_module, "_run_evaluator_safely", side_effect=evaluator), \
                patch.object(runner_module.os, "killpg", create=True, side_effect=signal_group):
            summary = runner_module.run_mode(upstream_root=self.upstream, project_root=self.project,
                results_root=results, workers=2, repeats_per_case=8,
                launch_cutoff_seconds=60, item_timeout_seconds=5)
        durable = json.loads((results / "m3-workers-2" / "session_summary.json").read_text())
        self.assertEqual(summary, durable)
        self.assertEqual("interrupted", summary["stop_reason"])
        self.assertEqual([], summary["in_flight_ids"])
        self.assertEqual(2, len(summary["results"]))
        self.assertEqual(2, len(processes))
        self.assertEqual({process.pid for process in processes},
            {event[1] for event in events if event[0] == "signal" and event[2] == signal.SIGTERM})
        self.assertFalse(any(event[0] == "signal" and event[2] == getattr(signal, "SIGKILL", 9)
            for event in events))
        self.assertEqual(4, len([event for event in events if event[0] == "docker" and "ps" in event[1]]))

    def test_interrupt_during_initial_summary_write_finalizes_without_launch(self):
        original_write = runner_module.base._atomic_write_json
        writes = 0
        def interrupt_first_write(path, value):
            nonlocal writes
            writes += 1
            if writes == 1:
                raise KeyboardInterrupt()
            return original_write(path, value)

        results = self.root / "initial-write-interrupt"
        fake = FakeEvaluator()
        with patch.object(runner_module.base, "_atomic_write_json", side_effect=interrupt_first_write):
            summary = self.run_mode(fake, results=results)
        durable = json.loads((results / "m3-workers-1" / "session_summary.json").read_text())
        self.assertEqual(summary, durable)
        self.assertEqual("interrupted", summary["stop_reason"])
        self.assertEqual([], summary["in_flight_ids"])
        self.assertEqual([], fake.commands)

    def test_interrupt_after_future_return_reconciles_the_known_future(self):
        """A Future returned before registration is never lost across interruption."""
        original_hash = Future.__hash__
        interrupted = False

        def interrupt_registration(future):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt()
            return original_hash(future)

        fake = FakeEvaluator()
        results = self.root / "submit-registration-interrupt"
        with patch.object(Future, "__hash__", new=interrupt_registration):
            summary = self.run_mode(fake, results=results)
        durable = json.loads((results / "m3-workers-1" / "session_summary.json").read_text())
        self.assertEqual(summary, durable)
        self.assertEqual("interrupted", summary["stop_reason"])
        state = summary["attempt_states"]["nominal-01"]
        if state == "prepared":
            # Cancellation won the race before execute entered the fake.
            self.assertEqual([], fake.commands)
        else:
            # execute won the race after launch_lock unwound.  The known
            # Future must still be either durable terminal or explicitly
            # in-flight, and any result first reconciled after interruption
            # cannot be benchmark-valid.
            self.assertIn(state, {"terminal", "active", "completing_pending"})
            records = [record for record in summary["results"]
                if record["case_id"] == "nominal-01"]
            self.assertLessEqual(len(records), 1)
            if records:
                self.assertNotEqual("valid", records[0]["status"])

    def test_submit_that_enqueues_then_interrupts_retains_uncertain_case(self):
        """submit() may have started work even when it raises before returning a future."""
        original_submit = runner_module.ThreadPoolExecutor.submit
        enqueued = []

        def enqueue_then_interrupt(executor, *args, **kwargs):
            # The scheduler never receives this Future, but the test owns it
            # so its fake worker has deterministically finished before this
            # TemporaryDirectory is cleaned up.  The durable summary remains
            # deliberately uncertain because production has no such handle.
            enqueued.append(original_submit(executor, *args, **kwargs))
            raise KeyboardInterrupt()

        results = self.root / "submit-return-interrupt"
        with patch.object(runner_module.ThreadPoolExecutor, "submit", new=enqueue_then_interrupt):
            summary = self.run_mode(FakeEvaluator(), results=results)
        enqueued[0].result(timeout=2)
        durable = json.loads((results / "m3-workers-1" / "session_summary.json").read_text())
        self.assertEqual(summary, durable)
        self.assertEqual("interrupted_cleanup_risk", summary["stop_reason"])
        self.assertEqual(["nominal-01"], summary["in_flight_ids"])
        self.assertEqual(0, summary["valid_count"])

    def test_known_future_after_registration_interrupt_is_reconciled_and_joined(self):
        original_hash = Future.__hash__
        interrupted = False
        shutdown_waits = []

        def interrupt_registration(future):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt()
            return original_hash(future)

        original_shutdown = runner_module.ThreadPoolExecutor.shutdown

        def observe_shutdown(executor, wait=True, *, cancel_futures=False):
            shutdown_waits.append(wait)
            return original_shutdown(executor, wait=wait, cancel_futures=cancel_futures)

        def interrupted_evaluator(*args, **kwargs):
            error = runner_module._EvaluatorInterrupted("interrupted")
            error.cleanup_confirmed = True
            error.cleanup_error = None
            raise error

        with patch.object(Future, "__hash__", new=interrupt_registration), \
                patch.object(runner_module.ThreadPoolExecutor, "shutdown", new=observe_shutdown):
            summary = self.run_mode(interrupted_evaluator,
                results=self.root / "registered-future-interrupt")
        self.assertEqual("interrupted", summary["stop_reason"])
        self.assertEqual([], summary["in_flight_ids"])
        # The Future is known.  It may be cancelled before its worker starts
        # or reconciled to one terminal record, but it cannot remain lost.
        self.assertLessEqual(len(summary["results"]), 1)
        self.assertEqual(len(summary["results"]), len({
            record["case_id"] for record in summary["results"]
        }))
        self.assertEqual([True], shutdown_waits)

    def test_completed_future_after_interrupt_is_not_counted_as_valid(self):
        started = threading.Event()
        release = threading.Event()

        def completes_after_interrupt(argv, *, cwd, check, timeout):
            config = Path(argv[-1])
            output = next(Path(json.loads(line.split(": ", 1)[1])) for line in config.read_text().splitlines()
                if line.startswith("output_dir: "))
            started.set()
            release.wait(2)
            output.mkdir(parents=True, exist_ok=True)
            (output / "fake_aggregate.json").write_text(json.dumps(aggregate()), encoding="utf-8")
            return SimpleNamespace(returncode=0)

        real_wait = runner_module.wait
        interrupted = False

        def interrupt_after_completion(futures, **kwargs):
            nonlocal interrupted
            if not interrupted:
                self.assertTrue(started.wait(2))
                release.set()
                time.sleep(.02)
                interrupted = True
                raise KeyboardInterrupt()
            return real_wait(futures, **kwargs)

        with patch.object(runner_module, "wait", side_effect=interrupt_after_completion):
            summary = self.run_mode(completes_after_interrupt,
                results=self.root / "completed-after-interrupt")
        self.assertIn(summary["stop_reason"], {"interrupted", "interrupted_cleanup_risk"})
        self.assertEqual(0, summary["valid_count"])
        self.assertTrue(summary["in_flight_ids"]
            or any(record["status"] != "valid" for record in summary["results"]))

    def test_event_after_wait_before_capture_makes_completed_result_nonvalid(self):
        """A handler event between wait and capture closes valid accounting."""
        interrupt_event = threading.Event()
        real_wait = runner_module.wait
        injected = False

        def signal_after_wait(futures, **kwargs):
            nonlocal injected
            done, pending = real_wait(futures, **kwargs)
            if done and not injected:
                injected = True
                interrupt_event.set()
            return done, pending

        with patch.object(runner_module, "wait", side_effect=signal_after_wait):
            summary = runner_module.run_mode(
                upstream_root=self.upstream,
                project_root=self.project,
                results_root=self.root / "event-after-wait",
                workers=1,
                repeats_per_case=8,
                launch_cutoff_seconds=60,
                item_timeout_seconds=5,
                command_runner=FakeEvaluator(),
                interrupt_event=interrupt_event,
            )

        self.assertTrue(injected)
        self.assertEqual("interrupted", summary["stop_reason"])
        self.assertEqual(0, summary["valid_count"])
        self.assertEqual(1, len(summary["results"]))
        self.assertEqual("infrastructure_error", summary["results"][0]["status"])

    def test_worker_base_exception_becomes_one_durable_infrastructure_record(self):
        """An unexpected worker exit cannot abandon an active ledger record."""
        def exits_worker(*args, **kwargs):
            raise SystemExit("fake worker exit")

        summary = self.run_mode(
            exits_worker, results=self.root / "worker-base-exception"
        )

        self.assertEqual("infrastructure_error", summary["stop_reason"])
        self.assertEqual([], summary["in_flight_ids"])
        self.assertEqual(0, summary["valid_count"])
        self.assertEqual(1, len(summary["results"]))
        self.assertEqual("infrastructure_error", summary["results"][0]["status"])
        self.assertIn("SystemExit", summary["results"][0]["infrastructure_error"])

    def test_interrupted_save_after_capture_preserves_pending_result_without_duplication(self):
        """A captured result survives an interrupt before its terminal save."""
        original_write = runner_module.base._atomic_write_json
        interrupted = False

        def interrupt_pending_save(path, value):
            nonlocal interrupted
            attempt = value["attempt_records"]["nominal-01"]
            if not interrupted and attempt["state"] == "completing_pending":
                interrupted = True
                raise KeyboardInterrupt()
            return original_write(path, value)

        results = self.root / "captured-save-interrupt"
        with patch.object(runner_module.base, "_atomic_write_json", side_effect=interrupt_pending_save):
            summary = self.run_mode(FakeEvaluator(), results=results)

        durable = json.loads((results / "m3-workers-1" / "session_summary.json").read_text())
        self.assertEqual(summary, durable)
        self.assertEqual("interrupted", summary["stop_reason"])
        self.assertEqual([], summary["in_flight_ids"])
        # Capture happened before the interrupt, so retain its exact evidence;
        # the mode-level stop reason keeps the summary non-comparable.
        self.assertEqual(1, summary["valid_count"])
        self.assertEqual(1, len(summary["results"]))
        self.assertEqual("valid", summary["results"][0]["status"])

    def test_interrupt_after_active_registration_before_its_save_reconciles_known_future(self):
        """A known Future is either cancelled before start or durably terminal."""
        original_write = runner_module.base._atomic_write_json
        interrupted = False

        def interrupt_active_save(path, value):
            nonlocal interrupted
            attempt = value["attempt_records"]["nominal-01"]
            if not interrupted and attempt["state"] == "active":
                interrupted = True
                raise KeyboardInterrupt()
            return original_write(path, value)

        fake = FakeEvaluator()
        results = self.root / "active-save-interrupt"
        with patch.object(runner_module.base, "_atomic_write_json", side_effect=interrupt_active_save):
            summary = self.run_mode(fake, results=results)

        durable = json.loads((results / "m3-workers-1" / "session_summary.json").read_text())
        self.assertEqual(summary, durable)
        self.assertEqual("interrupted", summary["stop_reason"])
        self.assertEqual([], summary["in_flight_ids"])
        self.assertLessEqual(len(summary["results"]), 1)
        self.assertEqual(len(summary["results"]), len({
            record["case_id"] for record in summary["results"]
        }))

    def test_interrupt_during_session_setup_writes_partial_summary_when_directory_exists(self):
        results = self.root / "setup-interrupt"
        session = results / "m3-workers-1"

        def create_then_interrupt(*args, **kwargs):
            session.mkdir(parents=True)
            raise KeyboardInterrupt()

        with patch.object(runner_module.base, "_prepare_session_directory", side_effect=create_then_interrupt):
            summary = self.run_mode(FakeEvaluator(), results=results)
        durable = json.loads((session / "session_summary.json").read_text())
        self.assertEqual(summary, durable)
        self.assertEqual("interrupted", summary["stop_reason"])
        self.assertEqual([], summary["in_flight_ids"])
        self.assertEqual([], summary["results"])

    def test_interrupt_before_submit_does_not_leave_unlaunched_id_in_flight(self):
        original_write = runner_module.base._atomic_write_json
        def interrupt_in_flight_write(path, value):
            if value["in_flight_ids"] and not value["results"]:
                raise KeyboardInterrupt()
            return original_write(path, value)

        results = self.root / "pre-submit-interrupt"
        fake = FakeEvaluator()
        with patch.object(runner_module.base, "_atomic_write_json", side_effect=interrupt_in_flight_write):
            summary = self.run_mode(fake, results=results)
        durable = json.loads((results / "m3-workers-1" / "session_summary.json").read_text())
        self.assertEqual(summary, durable)
        self.assertEqual("interrupted", summary["stop_reason"])
        self.assertEqual([], summary["in_flight_ids"])
        self.assertEqual([], fake.commands)

    def test_interrupt_with_unconfirmed_docker_cleanup_records_risk(self):
        started = threading.Event()
        docker_commands = []
        processes = []
        class Process:
            pid = 8123
            returncode = None
            def __init__(self):
                processes.append(self)
                started.set()
            def wait(self, timeout):
                if self.returncode is None:
                    time.sleep(timeout)
                    raise subprocess.TimeoutExpired("vla-eval", timeout)
                return self.returncode
            def terminate(self):
                self.returncode = 143
            def kill(self):
                self.returncode = -9

        def docker(argv, **kwargs):
            docker_commands.append(argv)
            return SimpleNamespace(returncode=1, stdout="", stderr="daemon unavailable")

        real_evaluator = runner_module._run_evaluator_safely
        def evaluator(*args, **kwargs):
            return real_evaluator(*args, **kwargs, process_factory=lambda *a, **k: Process(), docker_runner=docker)
        def signal_group(pid, signum):
            process = next(process for process in processes if process.pid == pid)
            if signum == 0 and process.returncode is not None:
                raise ProcessLookupError()
            if signum == signal.SIGTERM:
                process.returncode = 143
        real_wait = runner_module.wait
        interrupted = False
        def interrupt_once(futures, **kwargs):
            nonlocal interrupted
            if not interrupted:
                self.assertTrue(started.wait(2))
                interrupted = True
                raise KeyboardInterrupt()
            return real_wait(futures, **kwargs)
        with patch.object(runner_module, "wait", side_effect=interrupt_once), \
                patch.object(runner_module, "_run_evaluator_safely", side_effect=evaluator), \
                patch.object(runner_module.os, "killpg", create=True, side_effect=signal_group):
            summary = runner_module.run_mode(upstream_root=self.upstream, project_root=self.project,
                results_root=self.root / "interrupt-risk", workers=1, repeats_per_case=8,
                launch_cutoff_seconds=60, item_timeout_seconds=5)
        self.assertEqual("interrupted_cleanup_risk", summary["stop_reason"])
        self.assertEqual([], summary["in_flight_ids"])
        self.assertFalse(summary["results"][0]["cleanup_confirmed"])
        self.assertIn("daemon unavailable", summary["results"][0]["infrastructure_error"])
        self.assertIn(["docker", "rm", "-f", "vla-eval-8123"], docker_commands)

    def test_cli_sigterm_handler_requests_stop_and_reports_summary(self):
        child = f'''
import importlib.util, signal, sys
from pathlib import Path
from types import SimpleNamespace
spec = importlib.util.spec_from_file_location("run_parallel_eval_child", {str(SCRIPT_PATH)!r})
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.os = SimpleNamespace(name="posix")
def fake_run_mode(**kwargs):
    signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
    assert kwargs["interrupt_event"].is_set()
    return {{"workers": 1, "planned_ids": ["nominal-01"], "results": [],
        "valid_count": 0, "stop_reason": "interrupted"}}
module.run_mode = fake_run_mode
sys.argv = ["run_parallel_eval.py", "--upstream-root", {str(self.upstream)!r},
    "--project-root", {str(self.project)!r}, "--results-root", {str(self.root / 'signal-cli')!r},
    "--workers", "1", "--launch-cutoff-seconds", "60", "--item-timeout-seconds", "5"]
module.main()
'''
        child_result = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(SCRIPT_PATH.parents[1] / "src")}, timeout=10)
        self.assertEqual(1, child_result.returncode, child_result.stderr)
        self.assertIn("session_summary.json", child_result.stdout)
        self.assertIn("interrupted", child_result.stdout)

    @unittest.skipUnless(os.name == "posix", "requires real POSIX SIGTERM delivery")
    def test_cli_sigterm_interrupts_a_separate_runner_while_fake_evaluator_is_active(self):
        results = self.root / "real-sigterm-cli"
        ready = self.root / "fake-evaluator-ready"
        stopped = self.root / "fake-evaluator-stopped"
        child = f'''
import importlib.util, os, subprocess, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("run_parallel_eval_signal_child", {str(SCRIPT_PATH)!r})
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
ready = Path({str(ready)!r})
stopped = Path({str(stopped)!r})
evaluator = None
def fake_evaluator(argv, *, cwd, check, timeout, stop_event=None, interrupt_event=None, launch_lock=None):
    global evaluator
    evaluator = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    ready.write_text(str(evaluator.pid), encoding="utf-8")
    while not interrupt_event.is_set():
        time.sleep(.01)
    evaluator.terminate()
    evaluator.wait(timeout=2)
    stopped.write_text("stopped", encoding="utf-8")
    error = module._EvaluatorInterrupted("session interrupted")
    error.cleanup_confirmed = True
    error.cleanup_error = None
    error.evaluator_pid = evaluator.pid
    error.expected_container = f"vla-eval-{{evaluator.pid}}"
    raise error
module._run_evaluator_safely = fake_evaluator
sys.argv = ["run_parallel_eval.py", "--upstream-root", {str(self.upstream)!r},
    "--project-root", {str(self.project)!r}, "--results-root", {str(results)!r},
    "--workers", "1", "--launch-cutoff-seconds", "60", "--item-timeout-seconds", "5"]
module.main()
'''
        runner = subprocess.Popen([sys.executable, "-c", child], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env={**os.environ, "PYTHONPATH": str(SCRIPT_PATH.parents[1] / "src")})
        evaluator_pid = None
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(ready.exists(), "fake evaluator did not become active")
            evaluator_pid = int(ready.read_text(encoding="utf-8"))
            os.kill(runner.pid, signal.SIGTERM)
            stdout, stderr = runner.communicate(timeout=10)
        finally:
            if runner.poll() is None:
                runner.kill()
                runner.communicate(timeout=2)
            # If an assertion above fails before the runner's handler stops
            # its fake child, terminate that child while this fixture still
            # owns its freshly recorded PID.
            if evaluator_pid is not None and not stopped.exists():
                try:
                    os.kill(evaluator_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        self.assertEqual(1, runner.returncode, stderr)
        self.assertTrue(stopped.exists())
        self.assertIn("stop: interrupted", stdout)
        durable = json.loads((results / "m3-workers-1" / "session_summary.json").read_text())
        self.assertEqual("interrupted", durable["stop_reason"])
        self.assertEqual([], durable["in_flight_ids"])
        self.assertEqual(0, durable["valid_count"])

    def test_cli_prints_summary_and_returns_failure_for_partial_mode(self):
        argv = ["run_parallel_eval.py", "--upstream-root", str(self.upstream),
            "--project-root", str(self.project), "--results-root", str(self.root / "cli-results"),
            "--workers", "1", "--launch-cutoff-seconds", "60", "--item-timeout-seconds", "5"]
        output = io.StringIO()
        summary = {"workers": 1, "planned_ids": ["nominal-01", "mask-01"],
            "results": [{"status": "valid"}], "valid_count": 1,
            "stop_reason": "launch_cutoff_reached"}
        with patch.object(sys, "argv", argv), patch.object(runner_module, "run_mode", return_value=summary):
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                runner_module.main()
        self.assertNotEqual(0, raised.exception.code)
        self.assertIn("session_summary.json", output.getvalue())
        self.assertIn("launch_cutoff_reached", output.getvalue())
        self.assertIn("1/2", output.getvalue())

    def test_cutoff_crossing_during_config_preparation_does_not_submit(self):
        class Clock:
            value = 0

            def __call__(self):
                return self.value

        clock = Clock()
        original_write_config = runner_module.base._write_config

        def slow_write_config(**kwargs):
            original_write_config(**kwargs)
            clock.value = 10

        runner_module.base._write_config = slow_write_config
        try:
            fake = FakeEvaluator()
            record = self.run_mode(fake, results=self.root / "crossed-cutoff", clock=clock, cutoff=10)
        finally:
            runner_module.base._write_config = original_write_config

        self.assertEqual([], fake.commands)
        self.assertEqual([], record["in_flight_ids"])
        self.assertEqual("launch_cutoff_reached", record["stop_reason"])

    def test_rejects_float_worker_count(self):
        with self.assertRaisesRegex(ValueError, "workers"):
            self.run_mode(FakeEvaluator(), workers=1.0, results=self.root / "float-workers")

    def test_expired_cutoff_does_not_launch_or_relaunch(self):
        fake = FakeEvaluator()
        ticks = iter((0,) + (10,) * 20)
        record = self.run_mode(fake, results=self.root / "cutoff", clock=lambda: next(ticks), cutoff=10)
        self.assertEqual([], fake.commands)
        self.assertEqual([], record["results"])
        self.assertEqual("launch_cutoff_reached", record["stop_reason"])

    def test_refuses_nonempty_session_directory(self):
        results = self.root / "occupied"
        session = results / "m3-workers-1"; session.mkdir(parents=True)
        (session / "old.json").write_text("old", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "nonempty"):
            self.run_mode(FakeEvaluator(), results=results)

    def test_resume_runs_only_prepared_cases_and_preserves_terminal_evidence_once(self):
        results = self.root / "resume"
        _, original = self.write_safe_partial_session(results)
        fake = FakeEvaluator()

        summary = runner_module.run_mode(
            upstream_root=self.upstream, project_root=self.project, results_root=results,
            workers=1, repeats_per_case=8, launch_cutoff_seconds=60, item_timeout_seconds=5,
            command_runner=fake, resume=True,
        )

        self.assertEqual(15, len(fake.commands))
        self.assertEqual(["nominal-01"], [item["case_id"] for item in summary["results"][:1]])
        self.assertEqual(original["results"][0], summary["results"][0])
        self.assertEqual(16, summary["valid_count"])
        self.assertTrue(summary["resumed"])
        self.assertGreaterEqual(summary["elapsed_seconds"], original["elapsed_seconds"])

    def test_resume_refuses_unsafe_or_mismatched_partial_sessions(self):
        for mutation, message in (
            (lambda summary: summary["attempt_records"]["mask-01"].update(state="active"), "in-flight"),
            (lambda summary: summary["attempt_records"]["nominal-01"]["result"].update(status="invalid_evidence"), "terminal"),
            (lambda summary: summary.update(manifest_hash="wrong"), "manifest"),
            (lambda summary: summary.update(workers=2), "workers"),
            (lambda summary: summary.update(case_ids=[]), "case IDs"),
            (lambda summary: summary.clear(), "summary"),
        ):
            with self.subTest(message=message):
                results = self.root / f"unsafe-{message}"
                session, summary = self.write_safe_partial_session(results)
                mutation(summary)
                (session / "session_summary.json").write_text(json.dumps(summary), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    runner_module.run_mode(
                        upstream_root=self.upstream, project_root=self.project, results_root=results,
                        workers=1, repeats_per_case=8, launch_cutoff_seconds=60, item_timeout_seconds=5,
                        command_runner=FakeEvaluator(), resume=True,
                    )

    def test_resume_requires_an_existing_partial_session(self):
        with self.assertRaisesRegex(ValueError, "resume"):
            runner_module.run_mode(
                upstream_root=self.upstream, project_root=self.project, results_root=self.root / "missing",
                workers=1, repeats_per_case=8, launch_cutoff_seconds=60, item_timeout_seconds=5,
                command_runner=FakeEvaluator(), resume=True,
            )

    def test_resume_lease_prevents_concurrent_prepared_case_launches(self):
        results = self.root / "resume-lease"
        self.write_safe_partial_session(results)
        started = threading.Event()
        release = threading.Event()
        first_errors = []

        class BlockingEvaluator(FakeEvaluator):
            def __call__(self, argv, *, cwd, check, timeout):
                started.set()
                release.wait(2)
                return super().__call__(argv, cwd=cwd, check=check, timeout=timeout)

        errors = []
        def run_first():
            try:
                runner_module.run_mode(
                    upstream_root=self.upstream, project_root=self.project, results_root=results,
                    workers=1, repeats_per_case=8, launch_cutoff_seconds=60, item_timeout_seconds=5,
                    command_runner=BlockingEvaluator(), resume=True,
                )
            except BaseException as error:
                first_errors.append(error)

        first = threading.Thread(target=run_first)
        first.start()
        try:
            self.assertTrue(started.wait(2))
            with self.assertRaisesRegex(ValueError, "resume lease"):
                runner_module.run_mode(
                    upstream_root=self.upstream, project_root=self.project, results_root=results,
                    workers=1, repeats_per_case=8, launch_cutoff_seconds=60, item_timeout_seconds=5,
                    command_runner=FakeEvaluator(), resume=True,
                )
        except BaseException as error:
            errors.append(error)
        finally:
            release.set()
            first.join(5)
        self.assertEqual([], errors)
        self.assertFalse(first.is_alive())
        self.assertEqual([], first_errors)

    def test_resume_rejects_symlinked_session_layout_or_metadata(self):
        for target_name in ("session", "configs", "runs", "launches", "manifest.json", "session_summary.json"):
            with self.subTest(target_name=target_name):
                results = self.root / f"symlink-{target_name.replace('.', '-') }"
                session, _ = self.write_safe_partial_session(results)
                target = session if target_name == "session" else session / target_name
                replacement = self.root / f"real-{target_name.replace('.', '-') }"
                target.rename(replacement)
                try:
                    target.symlink_to(replacement, target_is_directory=replacement.is_dir())
                except OSError as error:
                    self.skipTest(f"symlinks unavailable: {error}")
                with self.assertRaisesRegex(ValueError, "symlink"):
                    runner_module.run_mode(
                        upstream_root=self.upstream, project_root=self.project, results_root=results,
                        workers=1, repeats_per_case=8, launch_cutoff_seconds=60, item_timeout_seconds=5,
                        command_runner=FakeEvaluator(), resume=True,
                    )


if __name__ == "__main__":
    unittest.main()
