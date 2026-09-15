import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_position_grid_search.py"
APPROVED_GRID = [
    ("grid-x000-y050", .00, .50), ("grid-x050-y050", .50, .50),
    ("grid-x000-y000", .00, .00), ("grid-x050-y000", .50, .00),
    ("grid-x025-y050", .25, .50), ("grid-x000-y025", .00, .25),
    ("grid-x050-y025", .50, .25), ("grid-x025-y000", .25, .00),
]
SPEC = importlib.util.spec_from_file_location("run_position_grid_search", SCRIPT_PATH)
position_grid = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = position_grid
SPEC.loader.exec_module(position_grid)


def aggregate(success=True, *, episode_index=0, infrastructure=False):
    episode = {"episode_idx": episode_index, "task_id": 0, "metrics": {"success": success}, "steps": 4, "elapsed_sec": 1.25}
    if infrastructure:
        episode.update(failure_reason="exception", failure_detail="runner unavailable")
        episode["metrics"]["success"] = False
    return {"tasks": [{"episodes": [episode]}]}


class Response:
    def __init__(self, data=None, returncode=0): self.data, self.returncode = data, returncode


class Runner:
    def __init__(self, responses): self.responses, self.commands = list(responses), []
    def __call__(self, command, *, cwd, check):
        self.commands.append((command, cwd, check))
        config = Path(command[-1]).read_text(encoding="utf-8")
        output = Path(json.loads(next(line.split(": ", 1)[1] for line in config.splitlines() if line.startswith("output_dir: "))))
        output.mkdir(parents=True, exist_ok=True)
        response = self.responses.pop(0)
        if not isinstance(response, Response): response = Response(response)
        if response.data is not None:
            (output / "fake_aggregate.json").write_text(json.dumps(response.data), encoding="utf-8")
        return SimpleNamespace(returncode=response.returncode)


class Clock:
    def __init__(self, *values): self.values = iter(values)
    def __call__(self): return next(self.values)


class PositionGridDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.upstream, self.project, self.results = self.root / "upstream", self.root / "project", self.root / "results"
        self.upstream.mkdir(); self.project.mkdir()
    def tearDown(self): self.temp.cleanup()
    def run_driver(self, responses, *, clock=None, cutoff=1320):
        runner = Runner(responses)
        summary = position_grid.run_session(upstream_root=self.upstream, project_root=self.project, results_root=self.results, launch_cutoff_seconds=cutoff, command_runner=runner, monotonic_clock=clock or Clock(*range(200)))
        return summary, runner
    def config(self, stage): return (self.results / "position-grid-search" / "configs" / (stage + ".yaml")).read_text(encoding="utf-8")

    def test_successful_sentinel_and_grid_record_fixed_geometry(self):
        summary, runner = self.run_driver([aggregate()] * 9)
        stages = ["nominal-sentinel"] + [stage for stage, _, _ in APPROVED_GRID]
        self.assertEqual(summary["stop_reason"], "no_policy_failure_in_grid")
        self.assertEqual(len(runner.commands), 9)
        self.assertEqual([stage["stage"] for stage in summary["completed"]["stages"]], stages)
        self.assertEqual(summary["completed"]["positions_attempted"], stages[1:])
        self.assertEqual(summary["planned"]["grid_area_fraction"], .25)
        self.assertEqual(summary["completed"]["sentinel_outcome"], "success")
        self.assertEqual(summary["completed"]["stages"][0]["perturbation"], {"enabled": False})
        self.assertEqual(summary["completed"]["stages"][1]["perturbation"]["width"], .5)
        self.assertEqual(summary["planned"]["grid_positions"], [
            {"stage": stage, "x": x, "y": y} for stage, x, y in APPROVED_GRID
        ])
        for stage, x, y in APPROVED_GRID:
            text = self.config(stage)
            for field, value in (("seed", "7"), ("env_seed", "7"), ("episodes_per_task", "1"), ("max_tasks", "1"), ("x", "{:.6f}".format(x)), ("y", "{:.6f}".format(y)), ("width", "0.500000"), ("height", "0.500000")):
                self.assertIn("{}: {}".format(field, value), text)
        self.assertNotIn("agentview_occlusion", self.config("nominal-sentinel"))

    def test_reproducible_second_cell_failure_runs_matched_controls(self):
        responses = [aggregate(), aggregate(), aggregate(False)] + [aggregate(False)] * 4 + [aggregate()] + [aggregate()] * 5
        summary, runner = self.run_driver(responses)
        point = position_grid.GRID_POINTS[1]
        self.assertEqual(summary["stop_reason"], "reproducible_failure_with_nominal_controls")
        self.assertEqual(len(runner.commands), 13)
        self.assertEqual(summary["first_apparent_failure"], {"stage": point.stage, "x": .5, "y": .5, "width": .5, "height": .5})
        self.assertTrue(summary["reproducible"]); self.assertTrue(summary["nominal_controls_passed"])
        self.assertEqual(len(summary["completed"]["replay_outcomes"]), 5)
        self.assertEqual(len(summary["completed"]["control_outcomes"]), 5)
        expected = self.config(point.stage).replace(point.stage, "STAGE")
        for index in range(1, 6): self.assertEqual(self.config("replay-{}".format(index)).replace("replay-{}".format(index), "STAGE"), expected)
        self.assertEqual(summary["outcomes"][2]["perturbation"]["x"], .5)
        self.assertEqual(summary["outcomes"][-1]["perturbation"], {"enabled": False})

    def test_failed_controls_are_terminal(self):
        summary, runner = self.run_driver([aggregate(), aggregate(), aggregate(False)] + [aggregate(False)] * 5 + [aggregate()] * 3 + [aggregate(False)] * 2)
        self.assertEqual(summary["stop_reason"], "reproducible_failure_nominal_controls_failed")
        self.assertFalse(summary["nominal_controls_passed"]); self.assertEqual(len(runner.commands), 13)

    def test_nonreproducible_failure_does_not_run_controls(self):
        summary, runner = self.run_driver([aggregate(), aggregate(False)] + [aggregate(False)] * 3 + [aggregate()] * 2)
        self.assertEqual(summary["stop_reason"], "policy_failure_not_reproducible")
        self.assertEqual(len(runner.commands), 7); self.assertEqual(summary["completed"]["control_outcomes"], [])

    def test_sentinel_failure_and_infrastructure_stop_durably(self):
        for response, reason in ((aggregate(False), "nominal_sentinel_failed"), (Response(None, 4), "nominal_sentinel_infrastructure_error")):
            with self.subTest(reason=reason):
                self.results = self.root / reason / "results"; summary, runner = self.run_driver([response])
                self.assertEqual(summary["stop_reason"], reason); self.assertEqual(len(runner.commands), 1)
                self.assertTrue((self.results / "position-grid-search" / "session_summary.json").exists())

    def test_wrong_sentinel_episode_index_is_invalid_evidence(self):
        summary, runner = self.run_driver([aggregate(True, episode_index=1)])
        self.assertEqual(summary["stop_reason"], "nominal_sentinel_invalid_evidence")
        self.assertIsNone(summary["completed"]["sentinel_outcome"])
        self.assertEqual(len(runner.commands), 1)

    def test_invalid_indices_and_incomplete_replay_or_control_never_pass_gates(self):
        summary, runner = self.run_driver([aggregate(), aggregate(True, episode_index=1)])
        self.assertEqual(summary["stop_reason"], "grid_invalid_evidence"); self.assertEqual(len(runner.commands), 2)
        self.assertEqual(summary["completed"]["positions_attempted"], [position_grid.GRID_POINTS[0].stage])
        self.results = self.root / "replay" / "results"
        summary, runner = self.run_driver([aggregate(), aggregate(False), aggregate(False), aggregate(False), aggregate(False), aggregate(False, episode_index=1)])
        self.assertEqual(summary["stop_reason"], "replay_invalid_evidence"); self.assertEqual(len(summary["completed"]["replay_outcomes"]), 3); self.assertIsNone(summary["reproducible"])
        self.results = self.root / "control" / "results"
        summary, runner = self.run_driver([aggregate(), aggregate(False)] + [aggregate(False)] * 5 + [aggregate()] * 3 + [aggregate(True, episode_index=1)])
        self.assertEqual(summary["stop_reason"], "control_invalid_evidence"); self.assertEqual(len(summary["completed"]["control_outcomes"]), 3); self.assertIsNone(summary["nominal_controls_passed"])

    def test_replay_and_control_infrastructure_stop_before_gate(self):
        summary, runner = self.run_driver([aggregate(), aggregate(False), aggregate(False), Response(None, 2)])
        self.assertEqual(summary["stop_reason"], "replay_infrastructure_error")
        self.assertEqual(summary["completed"]["replay_outcomes"], ["policy_failure"])
        self.assertIsNone(summary["reproducible"])
        self.results = self.root / "control-infra" / "results"
        summary, runner = self.run_driver([aggregate(), aggregate(False)] + [aggregate(False)] * 5 + [aggregate()] * 3 + [Response(None, 2)])
        self.assertEqual(summary["stop_reason"], "control_infrastructure_error")
        self.assertEqual(len(summary["completed"]["control_outcomes"]), 3)
        self.assertIsNone(summary["nominal_controls_passed"])

    def test_replay_and_control_aggregate_load_errors_stop_before_gate(self):
        summary, runner = self.run_driver([aggregate(), aggregate(False), aggregate(False), Response()])
        self.assertEqual(summary["stop_reason"], "replay_infrastructure_error")
        self.assertEqual(summary["completed"]["replay_outcomes"], ["policy_failure"])
        self.assertEqual(summary["completed"]["stages"][-1]["status"], "infrastructure_error")
        self.assertIsNone(summary["reproducible"])
        self.results = self.root / "control-aggregate" / "results"
        summary, runner = self.run_driver([aggregate(), aggregate(False)] + [aggregate(False)] * 5 + [aggregate()] * 2 + [Response()])
        self.assertEqual(summary["stop_reason"], "control_infrastructure_error")
        self.assertEqual(len(summary["completed"]["control_outcomes"]), 2)
        self.assertEqual(summary["completed"]["stages"][-1]["status"], "infrastructure_error")
        self.assertIsNone(summary["nominal_controls_passed"])

    def test_cutoff_during_replay_or_controls_preserves_incomplete_gates(self):
        replay_clock = Clock(*([0] * 8 + [1, 1]))
        summary, runner = self.run_driver([aggregate(), aggregate(False)], clock=replay_clock, cutoff=1)
        self.assertEqual(summary["stop_reason"], "launch_cutoff_reached")
        self.assertEqual(len(runner.commands), 2)
        self.assertEqual(summary["completed"]["replay_outcomes"], [])
        self.assertIsNone(summary["reproducible"])
        self.results = self.root / "control-cutoff" / "results"
        control_clock = Clock(*([0] * 24 + [1, 1]))
        summary, runner = self.run_driver([aggregate(), aggregate(False)] + [aggregate(False)] * 5, clock=control_clock, cutoff=1)
        self.assertEqual(summary["stop_reason"], "launch_cutoff_reached")
        self.assertEqual(len(runner.commands), 7)
        self.assertEqual(summary["completed"]["control_outcomes"], [])
        self.assertIsNone(summary["nominal_controls_passed"])

    def test_cutoff_and_unsafe_existing_session_are_rejected_or_persisted(self):
        summary, runner = self.run_driver([], clock=Clock(0, 1320, 1320), cutoff=1320)
        self.assertEqual(summary["stop_reason"], "launch_cutoff_reached"); self.assertEqual(runner.commands, [])
        self.results = self.root / "existing" / "results"; session = self.results / "position-grid-search"; session.mkdir(parents=True); (session / "old").write_text("x")
        with self.assertRaisesRegex(ValueError, "nonempty"): self.run_driver([])
        self.results = self.root / "symlink" / "results"; self.results.mkdir(parents=True); outside = self.root / "outside"; outside.mkdir()
        try: (self.results / "position-grid-search").symlink_to(outside, target_is_directory=True)
        except OSError as error: self.skipTest(str(error))
        with self.assertRaisesRegex(ValueError, "symlink"): self.run_driver([])

    def test_cli_help_runs_from_source_tree(self):
        env = dict(os.environ); env.pop("PYTHONPATH", None)
        completed = subprocess.run([sys.executable, str(SCRIPT_PATH), "--help"], cwd=str(SCRIPT_PATH.parents[1]), env=env, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr); self.assertIn("--launch-cutoff-seconds", completed.stdout)


if __name__ == "__main__": unittest.main()
