import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from robot_debug.session import (
    classify_aggregate,
    is_reproducible,
    should_launch_next,
)


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_failure_search.py"
SPEC = importlib.util.spec_from_file_location("run_failure_search", SCRIPT_PATH)
run_failure_search = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_failure_search)


def aggregate_with_episode(
    *,
    success=True,
    failure_reason=None,
    failure_detail=None,
    episode_index=0,
):
    episode = {
        "episode_idx": episode_index,
        "task_id": 0,
        "metrics": {"success": success},
        "steps": 12,
        "elapsed_sec": 2.5,
    }
    if failure_reason is not None:
        episode["failure_reason"] = failure_reason
    if failure_detail is not None:
        episode["failure_detail"] = failure_detail
    return {"tasks": [{"episodes": [episode]}]}


class AggregateClassificationTests(unittest.TestCase):
    def test_success_parses_episode_metrics(self):
        result = classify_aggregate(aggregate_with_episode(success=True, episode_index=3))

        self.assertEqual(result.outcome, "success")
        self.assertTrue(result.success)
        self.assertEqual(result.steps, 12)
        self.assertEqual(result.elapsed_seconds, 2.5)
        self.assertEqual(result.episode_index, 3)

    def test_completed_unsuccessful_episode_is_policy_failure(self):
        result = classify_aggregate(aggregate_with_episode(success=False))

        self.assertEqual(result.outcome, "policy_failure")

    def test_exception_is_not_a_policy_failure(self):
        result = classify_aggregate(
            aggregate_with_episode(
                success=False,
                failure_reason="exception",
                failure_detail="model server disconnected",
            )
        )

        self.assertEqual(result.outcome, "infrastructure_error")
        self.assertEqual(result.failure_detail, "model server disconnected")

    def test_rejects_missing_or_multiple_aggregate_members(self):
        cases = [
            {"tasks": []},
            {"tasks": [{"episodes": []}]},
            {"tasks": [{"episodes": [{}, {}]}]},
            {"tasks": [{"episodes": [{}]}, {"episodes": [{}]}]},
        ]

        for aggregate in cases:
            with self.subTest(aggregate=aggregate):
                with self.assertRaises(ValueError):
                    classify_aggregate(aggregate)

    def test_rejects_missing_success_metric(self):
        aggregate = aggregate_with_episode()
        del aggregate["tasks"][0]["episodes"][0]["metrics"]["success"]

        with self.assertRaisesRegex(ValueError, "success"):
            classify_aggregate(aggregate)

    def test_deadline_and_replay_decisions_are_pure(self):
        self.assertTrue(should_launch_next(1559, 1560))
        self.assertFalse(should_launch_next(1560, 1560))
        self.assertTrue(is_reproducible(["policy_failure"] * 4 + ["success"]))
        self.assertFalse(is_reproducible(["policy_failure"] * 3 + ["success"] * 2))
        with self.assertRaises(ValueError):
            is_reproducible(["policy_failure", "infrastructure_error"])


class FakeRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.commands = []

    def __call__(self, command, *, cwd, check):
        self.commands.append((command, cwd, check))
        config_path = Path(command[-1])
        output_dir = None
        for line in config_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("output_dir: "):
                output_dir = Path(json.loads(line.partition(": ")[2]))
                break
        if output_dir is None:
            raise AssertionError("generated config omitted output_dir")
        output_dir.mkdir(parents=True, exist_ok=True)
        response = self.responses.pop(0)
        if isinstance(response, list):
            aggregate = {"tasks": [{"episodes": response}]}
        else:
            aggregate = response
        (output_dir / "fake_aggregate.json").write_text(
            json.dumps(aggregate), encoding="utf-8"
        )


class Clock:
    def __init__(self, *values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


def single_episode(**kwargs):
    return aggregate_with_episode(**kwargs)["tasks"][0]["episodes"][0]


class SessionDriverTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.upstream = self.root / "upstream"
        self.project = self.root / "project"
        self.results = self.root / "results"
        self.upstream.mkdir()
        self.project.mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_driver(self, responses, *, clock=None, cutoff=1560):
        runner = FakeRunner(responses)
        summary = run_failure_search.run_session(
            upstream_root=self.upstream,
            project_root=self.project,
            results_root=self.results,
            launch_cutoff_seconds=cutoff,
            command_runner=runner,
            monotonic_clock=clock or Clock(*range(100)),
        )
        return summary, runner

    def test_no_failure_path_runs_nominal_then_all_sweep_severities(self):
        nominal = [single_episode(success=True, episode_index=index) for index in range(20)]
        summary, runner = self.run_driver(
            [[*nominal]] + [aggregate_with_episode(success=True) for _ in range(6)]
        )

        self.assertEqual(summary["stop_reason"], "no_policy_failure_in_sweep")
        self.assertEqual(len(runner.commands), 7)
        self.assertEqual(summary["completed"]["nominal_successes"], 20)
        self.assertEqual(
            [item[0] for item in summary["completed"]["stages"]],
            ["nominal", "sweep-0.25", "sweep-0.30", "sweep-0.35", "sweep-0.40", "sweep-0.45", "sweep-0.50"],
        )
        session_dir = self.results / "first-failure-search"
        self.assertTrue((session_dir / "session_summary.json").is_file())
        nominal_config = (session_dir / "configs" / "nominal.yaml").read_text(encoding="utf-8")
        self.assertIn("episodes_per_task: 20", nominal_config)
        self.assertIn("episode_indices: [0, 1, 2", nominal_config)

    def test_first_failure_replays_five_times_and_accepts_four_policy_failures(self):
        nominal = [single_episode(success=True, episode_index=index) for index in range(20)]
        replay_outcomes = [False, False, True, False, False]
        responses = [
            nominal,
            aggregate_with_episode(success=True),
            aggregate_with_episode(success=False),
        ] + [aggregate_with_episode(success=success) for success in replay_outcomes]

        summary, runner = self.run_driver(responses)

        self.assertEqual(summary["stop_reason"], "reproducible_policy_failure")
        self.assertEqual(len(runner.commands), 8)
        self.assertTrue(summary["reproducible"])
        self.assertEqual(summary["completed"]["replay_outcomes"].count("policy_failure"), 4)

    def test_nominal_infrastructure_error_stops_session(self):
        nominal = [single_episode(success=True, episode_index=index) for index in range(20)]
        nominal[4]["failure_reason"] = "exception"
        nominal[4]["metrics"]["success"] = False

        summary, runner = self.run_driver([nominal])

        self.assertEqual(summary["stop_reason"], "nominal_infrastructure_error")
        self.assertEqual(len(runner.commands), 1)

    def test_sweep_infrastructure_error_stops_session(self):
        nominal = [single_episode(success=True, episode_index=index) for index in range(20)]

        summary, runner = self.run_driver(
            [nominal, aggregate_with_episode(success=False, failure_reason="exception")]
        )

        self.assertEqual(summary["stop_reason"], "sweep_infrastructure_error")
        self.assertEqual(len(runner.commands), 2)

    def test_cutoff_before_next_launch_writes_summary(self):
        summary, runner = self.run_driver([], clock=Clock(0, 1560, 1560), cutoff=1560)

        self.assertEqual(summary["stop_reason"], "launch_cutoff_reached")
        self.assertEqual(runner.commands, [])
        self.assertTrue((self.results / "first-failure-search" / "session_summary.json").is_file())

    def test_rejects_nonempty_session_output(self):
        session_dir = self.results / "first-failure-search"
        session_dir.mkdir(parents=True)
        (session_dir / "old-summary.json").write_text("old", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "nonempty"):
            run_failure_search.run_session(
                upstream_root=self.upstream,
                project_root=self.project,
                results_root=self.results,
                command_runner=FakeRunner([]),
                monotonic_clock=Clock(0),
            )


if __name__ == "__main__":
    unittest.main()
