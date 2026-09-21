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
reduction = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reduction
SPEC.loader.exec_module(reduction)


def aggregate(success=True, *, episode_index=0, infrastructure=False):
    episode = {"episode_idx": episode_index, "task_id": 0, "metrics": {"success": success}, "steps": 4, "elapsed_sec": 1.25}
    if infrastructure:
        episode.update(failure_reason="exception", failure_detail="runner unavailable")
        episode["metrics"]["success"] = False
    return {"tasks": [{"episodes": [episode]}]}


class Response:
    def __init__(self, data=None, returncode=0):
        self.data, self.returncode = data, returncode


class Runner:
    def __init__(self, responses):
        self.responses, self.commands = list(responses), []

    def __call__(self, command, *, cwd, check):
        self.commands.append((command, cwd, check))
        config = Path(command[-1]).read_text(encoding="utf-8")
        output = Path(json.loads(next(line.split(": ", 1)[1] for line in config.splitlines() if line.startswith("output_dir: "))))
        output.mkdir(parents=True, exist_ok=True)
        response = self.responses.pop(0)
        if not isinstance(response, Response):
            response = Response(response)
        if response.data is not None:
            (output / "fake_aggregate.json").write_text(json.dumps(response.data), encoding="utf-8")
        return SimpleNamespace(returncode=response.returncode)


class InterruptingRunner(Runner):
    def __init__(self, responses, *, interrupt_at):
        super().__init__(responses)
        self.interrupt_at = interrupt_at

    def __call__(self, command, *, cwd, check):
        if len(self.commands) == self.interrupt_at:
            raise KeyboardInterrupt("intentional interruption")
        return super().__call__(command, cwd=cwd, check=check)


class Clock:
    def __init__(self, *values): self.values = iter(values)
    def __call__(self): return next(self.values)


class FailureReductionDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.upstream, self.project, self.results = self.root / "upstream", self.root / "project", self.root / "results"
        self.upstream.mkdir(); self.project.mkdir()

    def tearDown(self): self.temp.cleanup()

    def run_driver(self, responses, *, runner_class=Runner):
        runner = runner_class(responses)
        summary = reduction.run_session(
            upstream_root=self.upstream, project_root=self.project, results_root=self.results,
            command_runner=runner, monotonic_clock=Clock(*range(1000)),
        )
        return summary, runner

    def test_reduces_bottom_after_left_rejection_and_exports_replay_manifest(self):
        responses = [aggregate(), *([aggregate(False)] * 4), aggregate(), aggregate(), *([aggregate(False)] * 4), *([aggregate()] * 5)]
        summary, runner = self.run_driver(responses)

        self.assertEqual(summary["stop_reason"], "reduced_failure_with_nominal_controls")
        self.assertEqual(summary["certified_rectangle"], {"x": .5, "y": .0, "width": .5, "height": .375})
        self.assertEqual(len(runner.commands), 16)
        decisions = summary["completed"]["decisions"]
        self.assertTrue(any(item["edge"] == "left" and item["decision"] == "reject" for item in decisions))
        self.assertTrue(any(item["edge"] == "bottom" and item["decision"] == "pass" for item in decisions))
        self.assertEqual(summary["lineage"][-1]["edge"], "bottom")
        self.assertEqual(len(summary["completed"]["stages"]), 16)
        manifest = json.loads((self.results / "failure-reduction" / "replay_case.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["rectangle"], summary["certified_rectangle"])
        self.assertEqual(manifest["acceptance_rule"], {"failures": 4, "attempts": 5})
        self.assertEqual(manifest["source_summary"], "session_summary.json")
        self.assertNotIn(str(Path.home()), json.dumps(manifest))
        replay_config = manifest["replay_command"].rsplit(" ", 1)[1]
        self.assertTrue((self.results / "failure-reduction" / replay_config).is_file())

    def test_resume_reuses_completed_stages_after_interruption(self):
        responses = [aggregate(), *([aggregate(False)] * 4), aggregate(), aggregate(), *([aggregate(False)] * 4), *([aggregate()] * 5)]
        interrupted = InterruptingRunner(responses, interrupt_at=6)
        with self.assertRaises(KeyboardInterrupt):
            reduction.run_session(upstream_root=self.upstream, project_root=self.project, results_root=self.results,
                                  command_runner=interrupted, monotonic_clock=Clock(*range(1000)))
        remaining = responses[6:]
        resumed = Runner(remaining)
        summary = reduction.run_session(upstream_root=self.upstream, project_root=self.project, results_root=self.results,
                                        command_runner=resumed, monotonic_clock=Clock(*range(1000)))
        self.assertEqual(summary["stop_reason"], "reduced_failure_with_nominal_controls")
        self.assertEqual(len(resumed.commands), 10)
        self.assertEqual(len(summary["completed"]["stages"]), 16)

    def test_resume_after_certification_starts_controls_without_new_candidates(self):
        responses = [aggregate(), *([aggregate(False)] * 4), aggregate(), aggregate(), *([aggregate(False)] * 4), *([aggregate()] * 5)]
        interrupted = InterruptingRunner(responses, interrupt_at=11)
        with self.assertRaises(KeyboardInterrupt):
            reduction.run_session(upstream_root=self.upstream, project_root=self.project, results_root=self.results,
                                  command_runner=interrupted, monotonic_clock=Clock(*range(1000)))
        resumed = Runner(responses[11:])
        summary = reduction.run_session(upstream_root=self.upstream, project_root=self.project, results_root=self.results,
                                        command_runner=resumed, monotonic_clock=Clock(*range(1000)))
        self.assertEqual(summary["stop_reason"], "reduced_failure_with_nominal_controls")
        self.assertEqual(len(resumed.commands), 5)

    def test_rejects_resume_with_different_saved_plan_constants(self):
        session = self.results / "failure-reduction"
        session.mkdir(parents=True)
        planned = reduction.ReductionSession._plan()
        planned["parent_rectangle"] = {"x": 0, "y": 0, "width": 1, "height": 1}
        (session / "session_summary.json").write_text(json.dumps({"planned": planned}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "constants or parent geometry"):
            self.run_driver([])

    def test_parent_successes_do_not_certify_failure(self):
        summary, runner = self.run_driver([aggregate(), aggregate(), aggregate()])
        self.assertEqual(summary["stop_reason"], "parent_not_reproducible")
        self.assertEqual(len(runner.commands), 3)

    def test_infrastructure_and_invalid_evidence_abort_without_gate_decision(self):
        for response, reason in ((Response(None, 2), "infrastructure_error"), (aggregate(False, episode_index=1), "invalid_evidence")):
            with self.subTest(reason=reason):
                self.results = self.root / reason / "results"
                summary, _ = self.run_driver([aggregate(), response])
                self.assertEqual(summary["stop_reason"], reason)
                self.assertEqual(summary["completed"]["decisions"], [])

    def test_pending_candidate_at_hard_budget_retains_parent_rectangle(self):
        # Five rejected candidates consume ten attempts; the final two valid
        # outcomes remain pending, so the driver must not certify it.
        candidate_outcomes = [aggregate(), aggregate()] * 5 + [aggregate(False), aggregate()]
        summary, runner = self.run_driver([aggregate(), *([aggregate(False)] * 4), *candidate_outcomes])
        self.assertEqual(summary["stop_reason"], "candidate_budget_exhausted")
        self.assertEqual(len(runner.commands), 17)
        self.assertEqual(summary["certified_rectangle"], {"x": .5, "y": .0, "width": .5, "height": .5})
        self.assertEqual(summary["completed"]["decisions"][-1]["decision"], "inconclusive_budget_exhausted")

    def test_sentinel_failure_and_launch_cutoff_are_terminal(self):
        summary, _ = self.run_driver([aggregate(False)])
        self.assertEqual(summary["stop_reason"], "nominal_sentinel_failed")
        self.results = self.root / "cutoff" / "results"
        summary = reduction.run_session(upstream_root=self.upstream, project_root=self.project, results_root=self.results,
                                        launch_cutoff_seconds=0, command_runner=Runner([]), monotonic_clock=Clock(0, 0, 0))
        self.assertEqual(summary["stop_reason"], "launch_cutoff_reached")

    def test_failed_matched_controls_are_reported_without_changing_certified_rectangle(self):
        responses = [aggregate(), *([aggregate(False)] * 4), aggregate(), aggregate(), *([aggregate(False)] * 4), aggregate(), aggregate(), aggregate(), aggregate(False), aggregate(False)]
        summary, _ = self.run_driver(responses)
        self.assertEqual(summary["stop_reason"], "reduced_failure_nominal_controls_failed")
        self.assertEqual(summary["certified_rectangle"], {"x": .5, "y": .0, "width": .5, "height": .375})


if __name__ == "__main__": unittest.main()
