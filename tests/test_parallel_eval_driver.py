import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from robot_debug.parallel_eval import summarize_modes


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
            self.assertIsNone(record["cost_usd"])
            self.assertTrue(all(result["task_id"] == result["episode_index"] == 0 for result in record["results"]))
        self.assertEqual([1, 2, 4], [row["workers"] for row in summarize_modes(records)])

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

    def test_nested_task_id_mismatch_is_invalid_evidence(self):
        def nested_mismatch(_):
            evidence = aggregate()
            evidence["tasks"][0]["episodes"][0]["task_id"] = 1
            return 0, evidence

        fake = FakeEvaluator(response=nested_mismatch)
        record = self.run_mode(fake, results=self.root / "nested-task-mismatch")

        self.assertEqual(0, record["valid_count"])
        self.assertEqual("invalid_evidence", record["results"][0]["status"])

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


if __name__ == "__main__":
    unittest.main()
