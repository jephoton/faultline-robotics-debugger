"""Workload-level tests for the scenario modes: real generated configs and real-shaped evidence."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import yaml

from robot_debug import scenario_experiment as se
from robot_debug.job_workload import WorkloadPaths, run_workload
from tests.scenario_world import FakeSimulation
from tests.test_batch_experiment import World
from tests.test_scenario_experiment import SCREEN, SMOKE, make_plan
from tests.test_scenario_replay import replay_config
from tests.test_serverless_workload import FakeCompleted


class YamlRunner:
    """Evaluator fake: reads the *written YAML* the benchmark would get and writes its evidence."""

    def __init__(self, simulation=None, *, returncode=0):
        self.simulation = simulation or FakeSimulation()
        self.returncode = returncode
        self.lock = threading.Lock()
        self.params = {}

    def __call__(self, command, *, cwd, check=False):
        config = yaml.safe_load(Path(command[-1]).read_text(encoding="utf-8"))
        params = config["benchmarks"][0]["params"]
        with self.lock:
            self.params[Path(command[-1]).stem] = params
        self.simulation.run(params, Path(config["output_dir"]))
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

    def invoke(self, config, *, runner=None):
        world = World(item_seconds=0.0)
        runner = runner or YamlRunner()
        factory_calls = []

        def evaluator_factory(**kwargs):
            factory_calls.append(kwargs)
            return runner

        def exporter(source, destination, **kwargs):
            world.events.append("export")
            self.exports.append((Path(source), Path(destination), kwargs))
            return {"ok": True}

        summary = run_workload(
            config, paths=self.paths, model_factory=world.model_factory,
            evaluator_factory=evaluator_factory, exporter=exporter, clock=time.monotonic,
            progress=lambda *_a, **_k: None)
        return summary, world, runner, factory_calls

    def detail(self, config):
        path = self.paths.work_root / config["run_id"] / "scenario" / se.SUMMARY_NAME
        return json.loads(path.read_text(encoding="utf-8"))


class SmokeWorkloadTests(WorkloadTestCase):
    def test_the_smoke_job_completes_even_though_one_scene_is_invalid(self):
        summary, world, runner, factory_calls = self.invoke(SMOKE)
        self.assertEqual(("complete", "completed"), (summary["status"], summary["stop_reason"]), summary)
        self.assertTrue(summary["scenario_complete"])
        self.assertIsNone(summary["scenario_stop_reason"])
        self.assertEqual({"invalid_scene": 1, "success": 5}, summary["scenario_outcomes"])
        self.assertEqual("complete", self.exports[0][2]["status"])
        self.assertEqual(7, len(factory_calls), "six episodes and the warm-up")
        detail = self.detail(SMOKE)
        self.assertEqual("invalid_scene", {s["case_id"]: s["outcome"] for s in detail["scenes"]}["overlap-s0"])

    def test_generated_configs_select_suite_task_start_and_exports(self):
        _summary, _world, runner, _calls = self.invoke(dict(SMOKE, task_id=2))
        first = runner.params["init0-a"]
        self.assertEqual(("libero_10", 2, 0), (first["suite"], first["task_id"], first["init_state_index"]))
        self.assertTrue(first["layout_out"].endswith("layout.json"))
        self.assertTrue(first["state_out"].endswith("start_state.json"))
        self.assertNotIn("layout_out", runner.params["init1"])
        hybrid = runner.params["hybrid-objects-s1"]
        self.assertTrue(hybrid["scenario_start"]["candidate"].endswith("hybrid-objects-s1.json"))
        self.assertTrue(hybrid["scenario_start"]["metadata_out"].endswith("scenario_start.json"))
        self.assertNotIn("init_state_index", hybrid)

    def test_a_nonzero_evaluator_still_latches_partial(self):
        summary, _world, _runner, _calls = self.invoke(dict(SMOKE, run_id="scn-smoke-fail"),
                                                       runner=YamlRunner(returncode=3))
        self.assertEqual(("partial", "evaluator_failed"), (summary["status"], summary["stop_reason"]))
        self.assertFalse(summary["scenario_complete"])
        self.assertEqual("partial", self.exports[0][2]["status"])

    def test_the_invalid_scene_episode_has_the_evidence_the_job_checks(self):
        self.invoke(SMOKE)
        base = self.paths.work_root / SMOKE["run_id"] / "scenario" / "runs" / "overlap-s0"
        aggregate = json.loads(next(base.glob("*_aggregate.json")).read_text(encoding="utf-8"))
        episode = aggregate["tasks"][0]["episodes"][0]
        self.assertEqual({"success": False, "invalid_scene": True}, episode["metrics"])
        self.assertEqual(1, episode["steps"])


class ScreenWorkloadTests(WorkloadTestCase):
    def test_the_screen_job_writes_a_summary_the_planner_reads(self):
        from scripts import plan_scenario_reduction as planner

        summary, _world, _runner, _calls = self.invoke(SCREEN)
        self.assertEqual(("complete", "completed"), (summary["status"], summary["stop_reason"]), summary)
        self.assertEqual([[0, i] for i in range(5, 10)], summary["scenario_reproducible_failures"])
        detail = self.detail(SCREEN)
        plan = planner.build_plan(detail, 0, 7, use_llm=False)
        self.assertEqual(7, plan["failing"]["start_index"])

    def test_phase_one_configs_pick_the_start_and_export_its_state(self):
        _summary, _world, runner, _calls = self.invoke(dict(SCREEN, start_indices=[2, 6]))
        params = runner.params["t00-s06-a01"]
        self.assertEqual((6, 0, "libero_10"), (
            params["init_state_index"], params.get("task_id", 0), params["suite"]))
        self.assertTrue(params["state_out"].endswith("start_state.json"))
        self.assertIn("t00-s06-a02", runner.params, "failing start 6 is confirmed")
        self.assertNotIn("t00-s02-a02", runner.params, "a passing start is not")


class ReplayWorkloadTests(WorkloadTestCase):
    def test_the_replay_job_reports_its_verdict_and_exports(self):
        config = replay_config()
        summary, _world, runner, factory_calls = self.invoke(config)
        self.assertEqual(("complete", "completed"), (summary["status"], summary["stop_reason"]), summary)
        self.assertEqual("still_reproduces", summary["scenario_verdict"])
        self.assertTrue(summary["scenario_complete"])
        self.assertEqual("complete", self.exports[0][2]["status"])
        self.assertEqual(10, len(factory_calls), "nine attempts after early decisions and the warm-up")
        detail = self.detail(config)
        self.assertEqual("still_reproduces", detail["verdict"])
        replayed = [p for stem, p in runner.params.items() if not stem.startswith("warmup")]
        self.assertTrue(all(p["scenario_start"]["candidate"].endswith(".json") for p in replayed))


class ReduceWorkloadTests(WorkloadTestCase):
    def test_the_reduce_job_reduces_and_exports(self):
        config = se.build_reduce_workload(make_plan(), run_id="scn-reduce-1")
        summary, world, runner, _calls = self.invoke(config)
        self.assertEqual(("complete", "completed"), (summary["status"], summary["stop_reason"]), summary)
        self.assertEqual("reduced", summary["scenario_reduction_stop_reason"])
        self.assertEqual({"alphabet_soup_1": {"position": 0.125}}, summary["scenario_final_selection"])
        self.assertTrue(summary["scenario_complete"])
        self.assertEqual("complete", self.exports[0][2]["status"])
        detail = self.detail(config)
        self.assertEqual({"original", "minimal", "reference"}, set(detail["videos"]))
        for params in runner.params.values():
            self.assertIn("scenario_start", params)
            self.assertEqual("libero_10", params["suite"])

    def test_a_small_reduce_workload_fits_the_prepare_script_guard(self):
        config = se.build_reduce_workload(make_plan(), run_id="scn-reduce-1")
        self.assertGreaterEqual(config["deadline_seconds"], 1000)


if __name__ == "__main__":
    unittest.main()
