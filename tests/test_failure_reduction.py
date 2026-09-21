"""Tests for the resumable bounded failure-reduction session driver."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_failure_reduction.py"
SPEC = importlib.util.spec_from_file_location("run_failure_reduction", SCRIPT_PATH)
reduction = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = reduction; SPEC.loader.exec_module(reduction)

def aggregate(success=True, *, episode_index=0, task_id=0):
    return {"tasks": [{"episodes": [{"episode_idx": episode_index, "task_id": task_id, "metrics": {"success": success}, "steps": 4, "elapsed_sec": 1.25}]}]}

class Response:
    def __init__(self, data=None, returncode=0): self.data, self.returncode = data, returncode

class Runner:
    def __init__(self, responses): self.responses, self.commands = list(responses), []
    def __call__(self, command, *, cwd, check):
        self.commands.append((command, cwd, check))
        config = Path(command[-1]).read_text(encoding="utf-8")
        output = Path(json.loads(next(line.split(": ", 1)[1] for line in config.splitlines() if line.startswith("output_dir: "))))
        output.mkdir(parents=True, exist_ok=True); response = self.responses.pop(0)
        if not isinstance(response, Response): response = Response(response)
        if response.data is not None: (output / "fake_aggregate.json").write_text(json.dumps(response.data), encoding="utf-8")
        return SimpleNamespace(returncode=response.returncode)

class InterruptingRunner(Runner):
    def __init__(self, responses, *, interrupt_at): super().__init__(responses); self.interrupt_at = interrupt_at
    def __call__(self, command, *, cwd, check):
        if len(self.commands) == self.interrupt_at: raise KeyboardInterrupt("intentional interruption")
        return super().__call__(command, cwd=cwd, check=check)

class Clock:
    def __init__(self, *values): self.values = iter(values)
    def __call__(self): return next(self.values)

class FailureReductionDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.upstream, self.project, self.results = self.root / "upstream", self.root / "project", self.root / "results"
        self.upstream.mkdir(); self.project.mkdir()
    def tearDown(self): self.temp.cleanup()
    def run_driver(self, responses, *, runner_class=Runner, clock=None, cutoff=1320):
        runner = runner_class(responses)
        summary = reduction.run_session(upstream_root=self.upstream, project_root=self.project, results_root=self.results, launch_cutoff_seconds=cutoff, command_runner=runner, monotonic_clock=clock or Clock(*range(1000)))
        return summary, runner
    @staticmethod
    def parent_passes(): return [aggregate(False)] * 4

    def test_restarts_after_bottom_acceptance_then_runs_controls_at_candidate_budget(self):
        responses = [aggregate(), *self.parent_passes(), aggregate(), aggregate(), *([aggregate(False)] * 4), aggregate(), aggregate(), aggregate(), aggregate(), aggregate(False), aggregate(), *([aggregate()] * 5)]
        summary, runner = self.run_driver(responses)
        self.assertEqual(summary["stop_reason"], "reduced_failure_with_nominal_controls")
        self.assertEqual(summary["certified_rectangle"], {"x": .5, "y": .0, "width": .5, "height": .375})
        self.assertEqual(summary["candidate_valid_attempts"], 12); self.assertEqual(summary["valid_episode_count"], 22); self.assertEqual(len(runner.commands), 22)
        decisions = summary["completed"]["decisions"]
        self.assertTrue(any(item["edge"] == "left" and item["decision"] == "reject" for item in decisions))
        self.assertTrue(any(item["edge"] == "bottom" and item["decision"] == "pass" for item in decisions))
        self.assertTrue(any(item["edge"] == "left" and item["rectangle"]["height"] == .375 for item in decisions))
        self.assertEqual(summary["lineage"][-1]["edge"], "bottom")
        manifest = json.loads((self.results / "failure-reduction" / "replay_case.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["rectangle"], summary["certified_rectangle"]); self.assertEqual(manifest["acceptance_rule"], {"failures": 4, "attempts": 5})
        self.assertNotIn(str(Path.home()), json.dumps(manifest)); self.assertTrue((self.results / "failure-reduction" / manifest["replay_command"].rsplit(" ", 1)[1]).is_file())
        self.assertEqual(summary["geometry"]["parent"]["area"], .25); self.assertEqual(summary["geometry"]["final"]["area"], .1875); self.assertEqual(summary["model_identity"], reduction.MODEL_ID)

    def test_resume_reconstructs_three_pending_attempts_and_launches_fourth_at_global_limit(self):
        initial = [aggregate(), *self.parent_passes(), *([aggregate(), aggregate()] * 4), *([aggregate(False)] * 3)]
        interrupted = InterruptingRunner(initial, interrupt_at=16)
        with self.assertRaises(KeyboardInterrupt): self.run_driver(initial, runner_class=lambda _: interrupted)
        resumed = Runner([aggregate(False), *([aggregate()] * 5)])
        summary = reduction.run_session(upstream_root=self.upstream, project_root=self.project, results_root=self.results, command_runner=resumed, monotonic_clock=Clock(*range(1000)))
        self.assertEqual(len(resumed.commands), 6); self.assertEqual(summary["candidate_valid_attempts"], 12); self.assertEqual(summary["lineage"][-1]["delta"], .0625); self.assertEqual(summary["stop_reason"], "reduced_failure_with_nominal_controls")

    def test_terminal_resume_repairs_missing_manifest_without_relaunching(self):
        responses = [aggregate(), *self.parent_passes(), aggregate(), aggregate(), *([aggregate(False)] * 4), aggregate(), aggregate(), aggregate(), aggregate(), aggregate(False), aggregate(), *([aggregate()] * 5)]
        summary, _ = self.run_driver(responses); self.assertEqual(summary["stop_reason"], "reduced_failure_with_nominal_controls")
        manifest = self.results / "failure-reduction" / "replay_case.json"; manifest.unlink(); resumed = Runner([])
        summary = reduction.run_session(upstream_root=self.upstream, project_root=self.project, results_root=self.results, command_runner=resumed, monotonic_clock=Clock(*range(1000)))
        self.assertTrue(manifest.is_file()); self.assertEqual(resumed.commands, []); self.assertEqual(summary["stop_reason"], "reduced_failure_with_nominal_controls")

    def test_resume_accumulates_active_elapsed_time_for_cutoff(self):
        session = reduction.ReductionSession(upstream_root=self.upstream, project_root=self.project, results_root=self.results, launch_cutoff_seconds=11, command_runner=Runner([]), monotonic_clock=Clock(0, 0))
        session.summary["elapsed_seconds"] = 10
        reduction.base._atomic_write_json(session.session_dir / "session_summary.json", session.summary)
        summary, runner = self.run_driver([aggregate()], clock=Clock(100, 102, 102), cutoff=11)
        self.assertEqual(summary["stop_reason"], "launch_cutoff_reached"); self.assertEqual(runner.commands, []); self.assertGreaterEqual(summary["elapsed_seconds"], 12)

    def test_controls_require_five_successes(self):
        responses = [aggregate(), *self.parent_passes(), aggregate(), aggregate(), *([aggregate(False)] * 4), aggregate(), aggregate(), aggregate(), aggregate(), aggregate(False), aggregate(), aggregate(), aggregate(), aggregate(), aggregate(), aggregate(False)]
        summary, _ = self.run_driver(responses); self.assertEqual(summary["stop_reason"], "reduced_failure_nominal_controls_failed")

    def test_invalid_task_index_and_malformed_aggregate_are_invalid_evidence(self):
        for response in (aggregate(True, task_id=1), {"tasks": []}):
            with self.subTest(response=response):
                self.results = self.root / str(len(str(response))) / "results"; summary, _ = self.run_driver([response]); self.assertEqual(summary["stop_reason"], "invalid_evidence")

    def test_runner_failure_is_infrastructure_and_invalid_results_never_enter_gate(self):
        self.results = self.root / "runner" / "results"; summary, _ = self.run_driver([Response(None, 2)]); self.assertEqual(summary["stop_reason"], "infrastructure_error")
        self.results = self.root / "episode" / "results"; summary, _ = self.run_driver([aggregate(), aggregate(False, episode_index=1)])
        self.assertEqual(summary["stop_reason"], "invalid_evidence"); self.assertEqual(summary["completed"]["decisions"], [])

    def test_parent_failure_budget_and_candidate_cap_are_never_exceeded(self):
        parent = [aggregate(False), aggregate(False), aggregate(False), aggregate(), aggregate(False)]
        candidates = [aggregate(), aggregate()] * 4 + [aggregate(False)] * 4
        summary, _ = self.run_driver([aggregate(), *parent, *candidates, *([aggregate()] * 5)])
        self.assertLessEqual(summary["candidate_valid_attempts"], 12); self.assertLessEqual(summary["valid_episode_count"], 23); self.assertEqual(summary["valid_episode_count"], 23)

    def test_sentinel_failure_parent_rejection_and_plan_mismatch_are_terminal(self):
        summary, _ = self.run_driver([aggregate(False)]); self.assertEqual(summary["stop_reason"], "nominal_sentinel_failed")
        self.results = self.root / "parent" / "results"; summary, _ = self.run_driver([aggregate(), aggregate(), aggregate()]); self.assertEqual(summary["stop_reason"], "parent_not_reproducible")
        self.results = self.root / "mismatch" / "results"; session = self.results / "failure-reduction"; session.mkdir(parents=True)
        plan = reduction.ReductionSession._plan(); plan["parent_rectangle"] = {"x": 0, "y": 0, "width": 1, "height": 1}
        (session / "session_summary.json").write_text(json.dumps({"planned": plan}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "constants or parent geometry"): self.run_driver([])

if __name__ == "__main__": unittest.main()
