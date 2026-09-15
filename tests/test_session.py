import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from robot_debug.session import (
    classify_aggregate,
    is_reproducible,
    should_launch_next,
)


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_failure_search.py"
SPEC = importlib.util.spec_from_file_location("run_failure_search", SCRIPT_PATH)
run_failure_search = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = run_failure_search
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
        with self.assertRaises(ValueError):
            is_reproducible(["policy_failure"] * 4)
        with self.assertRaises(ValueError):
            is_reproducible(["policy_failure"] * 4 + ["unknown"])

    def test_rejects_nonfinite_or_negative_timing_and_cutoff_values(self):
        for value in (float("nan"), float("inf"), -0.1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    should_launch_next(value, 1560)
                with self.assertRaises(ValueError):
                    should_launch_next(0, value)

        for field, value in (("steps", -1), ("elapsed_sec", float("nan"))):
            with self.subTest(field=field):
                aggregate = aggregate_with_episode()
                aggregate["tasks"][0]["episodes"][0][field] = value
                with self.assertRaises(ValueError):
                    classify_aggregate(aggregate)

    def test_rejects_fractional_episode_index_and_overflowing_steps(self):
        fractional_index = aggregate_with_episode(episode_index=0.5)

        with self.assertRaises(ValueError):
            classify_aggregate(fractional_index)

        for steps in (float("inf"), 1e999):
            with self.subTest(steps=steps):
                aggregate = aggregate_with_episode()
                aggregate["tasks"][0]["episodes"][0]["steps"] = steps
                with self.assertRaises(ValueError):
                    classify_aggregate(aggregate)


class SourceTreeCliTests(unittest.TestCase):
    def test_help_runs_without_pythonpath(self):
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            cwd=str(SCRIPT_PATH.parents[1]),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--upstream-root", completed.stdout)


class EvaluatorCommandTests(unittest.TestCase):
    def test_uses_sibling_evaluator_from_virtual_environment(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            bin_dir = Path(temporary_directory) / "venv" / "bin"
            bin_dir.mkdir(parents=True)
            interpreter = bin_dir / "python"
            evaluator = bin_dir / "vla-eval"
            interpreter.touch()
            evaluator.touch()

            command = run_failure_search._resolve_evaluator_command(interpreter)

        self.assertEqual(command, str(evaluator))


class RunnerResponse:
    def __init__(self, aggregate=None, *, returncode=0, aggregate_text=None):
        self.aggregate = aggregate
        self.returncode = returncode
        self.aggregate_text = aggregate_text


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
        if isinstance(response, RunnerResponse):
            aggregate = response.aggregate
            returncode = response.returncode
            aggregate_text = response.aggregate_text
        else:
            aggregate = response
            returncode = 0
            aggregate_text = None
        if isinstance(aggregate, list):
            aggregate = {"tasks": [{"episodes": aggregate}]}
        if aggregate is not None or aggregate_text is not None:
            (output_dir / "fake_aggregate.json").write_text(
                aggregate_text if aggregate_text is not None else json.dumps(aggregate),
                encoding="utf-8",
            )
        return SimpleNamespace(returncode=returncode)


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
            [item["stage"] for item in summary["completed"]["stages"]],
            ["nominal", "sweep-0.25", "sweep-0.30", "sweep-0.35", "sweep-0.40", "sweep-0.45", "sweep-0.50"],
        )
        for command, cwd, check in runner.commands:
            self.assertEqual(command[:3], ["vla-eval", "run", "--config"])
            self.assertEqual(cwd, self.upstream.resolve())
            self.assertFalse(check)
        session_dir = self.results / "first-failure-search"
        self.assertTrue((session_dir / "session_summary.json").is_file())
        nominal_config = (session_dir / "configs" / "nominal.yaml").read_text(encoding="utf-8")
        self.assertIn("episodes_per_task: 20", nominal_config)
        self.assertIn("max_tasks: 1", nominal_config)
        self.assertNotIn("task_ids:", nominal_config)
        self.assertNotIn("episode_indices:", nominal_config)
        for side in run_failure_search.SWEEP_SIDES:
            config = (session_dir / "configs" / "sweep-{:.2f}.yaml".format(side)).read_text(
                encoding="utf-8"
            )
            offset = (1.0 - side) / 2.0
            self.assertIn("seed: 7", config)
            self.assertIn("env_seed: 7", config)
            self.assertIn("episodes_per_task: 1", config)
            self.assertIn("max_tasks: 1", config)
            self.assertNotIn("task_ids:", config)
            self.assertNotIn("episode_indices:", config)
            self.assertIn("x: {:.6f}".format(offset), config)
            self.assertIn("y: {:.6f}".format(offset), config)
            self.assertIn("width: {:.6f}".format(side), config)
            self.assertIn("height: {:.6f}".format(side), config)
            self.assertIn("color: [0, 0, 0]", config)
            self.assertIn("opacity: 1.0", config)

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
        session_dir = self.results / "first-failure-search"
        expected = self._normalise_config(
            (session_dir / "configs" / "sweep-0.30.yaml").read_text(encoding="utf-8")
        )
        for index in range(1, 6):
            replay = self._normalise_config(
                (session_dir / "configs" / "replay-{}.yaml".format(index)).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(replay, expected)

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

    def test_wrong_sweep_episode_index_stops_as_invalid_evidence(self):
        nominal = [single_episode(success=True, episode_index=index) for index in range(20)]

        summary, runner = self.run_driver(
            [nominal, aggregate_with_episode(success=True, episode_index=1)]
        )

        self.assertEqual(summary["stop_reason"], "sweep_invalid_evidence")
        self.assertEqual(len(runner.commands), 2)
        self.assertEqual(summary["completed"]["stages"][-1]["status"], "invalid_evidence")

    def test_wrong_replay_episode_index_stops_as_invalid_evidence(self):
        nominal = [single_episode(success=True, episode_index=index) for index in range(20)]

        summary, runner = self.run_driver(
            [
                nominal,
                aggregate_with_episode(success=False),
                aggregate_with_episode(success=False, episode_index=1),
            ]
        )

        self.assertEqual(summary["stop_reason"], "replay_invalid_evidence")
        self.assertEqual(len(runner.commands), 3)
        self.assertEqual(summary["completed"]["stages"][-1]["status"], "invalid_evidence")

    def test_cutoff_before_next_launch_writes_summary(self):
        summary, runner = self.run_driver([], clock=Clock(0, 1560, 1560), cutoff=1560)

        self.assertEqual(summary["stop_reason"], "launch_cutoff_reached")
        self.assertEqual(runner.commands, [])
        self.assertTrue((self.results / "first-failure-search" / "session_summary.json").is_file())

    def test_cutoff_after_nominal_preserves_success_count_in_summary(self):
        nominal = [single_episode(success=True, episode_index=index) for index in range(20)]
        summary, runner = self.run_driver(
            [nominal], clock=Clock(0, 0, 0, 0, 1, 1), cutoff=1
        )

        self.assertEqual(summary["stop_reason"], "launch_cutoff_reached")
        self.assertEqual(len(runner.commands), 1)
        persisted = json.loads(
            (self.results / "first-failure-search" / "session_summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(persisted["completed"]["nominal_successes"], 20)

    def test_invalid_nominal_episode_indices_stop_as_invalid_evidence(self):
        nominal = [single_episode(success=True, episode_index=index) for index in range(20)]
        nominal[-1]["episode_idx"] = 18

        summary, runner = self.run_driver([nominal])

        self.assertEqual(summary["stop_reason"], "nominal_invalid_evidence")
        self.assertEqual(len(runner.commands), 1)
        self.assertEqual(summary["completed"]["nominal_successes"], 20)

    def test_evaluator_and_aggregate_failures_become_durable_infrastructure_evidence(self):
        invalid_episode = single_episode(success=True)
        del invalid_episode["steps"]
        classifier_failure = [invalid_episode] + [
            single_episode(success=True, episode_index=index) for index in range(1, 20)
        ]
        cases = {
            "nonzero": RunnerResponse(aggregate_with_episode(), returncode=9),
            "missing": RunnerResponse(),
            "malformed": RunnerResponse(aggregate_text="{not json"),
            "nonstandard_constant": RunnerResponse(aggregate_text='{"value": NaN}'),
            "classification": RunnerResponse(classifier_failure),
        }

        for name, response in cases.items():
            with self.subTest(name=name):
                self.results = self.root / name / "results"
                summary, runner = self.run_driver([response])

                self.assertEqual(summary["stop_reason"], "nominal_infrastructure_error")
                self.assertEqual(len(runner.commands), 1)
                stage = summary["completed"]["stages"][0]
                self.assertEqual(stage["status"], "infrastructure_error")
                self.assertTrue(stage["infrastructure_error"])
                self.assertTrue(
                    (self.results / "first-failure-search" / "session_summary.json").is_file()
                )

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

    def test_rejects_symlinked_session_output(self):
        self.results.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        session_dir = self.results / "first-failure-search"
        try:
            session_dir.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest("symlink creation is unavailable: {}".format(error))

        with self.assertRaisesRegex(ValueError, "symlink"):
            run_failure_search.run_session(
                upstream_root=self.upstream,
                project_root=self.project,
                results_root=self.results,
                command_runner=FakeRunner([]),
                monotonic_clock=Clock(0),
            )

    def test_config_quotes_special_path_values(self):
        project = self.root / "project: # [unsafe]"
        output = self.root / "output: # [unsafe]"
        config_path = self.root / "config.yaml"

        run_failure_search._write_config(
            config_path=config_path,
            output_dir=output,
            project_root=project,
            stage_name="sweep-0.25",
            episode_indices=(0,),
            side=0.25,
        )

        config = config_path.read_text(encoding="utf-8")
        volume = "{}:/workspace/robot-debug-src:ro".format(project / "src")
        self.assertIn("    - {}".format(json.dumps(volume)), config)
        self.assertIn("output_dir: {}".format(json.dumps(str(output))), config)

    def test_config_writes_explicit_occlusion_position(self):
        config_path = self.root / "config.yaml"

        run_failure_search._write_config(
            config_path=config_path,
            output_dir=self.root / "output",
            project_root=self.project,
            stage_name="position-0.00-0.50",
            episode_indices=(0,),
            side=0.50,
            x=0.00,
            y=0.50,
        )

        config = config_path.read_text(encoding="utf-8")
        self.assertIn("        x: 0.000000", config)
        self.assertIn("        y: 0.500000", config)
        self.assertIn("        width: 0.500000", config)
        self.assertIn("        height: 0.500000", config)

    def test_config_rejects_invalid_explicit_occlusion_positions(self):
        base_arguments = {
            "config_path": self.root / "config.yaml",
            "output_dir": self.root / "output",
            "project_root": self.project,
            "stage_name": "position",
            "episode_indices": (0,),
            "side": 0.50,
        }

        with self.assertRaisesRegex(ValueError, "x and y"):
            run_failure_search._write_config(**base_arguments, x=0.00)
        with self.assertRaisesRegex(ValueError, "image bounds"):
            run_failure_search._write_config(**base_arguments, x=0.51, y=0.00)
        with self.assertRaisesRegex(ValueError, "finite number"):
            run_failure_search._write_config(**base_arguments, x=True, y=0.00)

    def test_prepare_session_directory_accepts_single_custom_name(self):
        session_dir = run_failure_search._prepare_session_directory(
            self.results, session_directory_name="position-grid-search"
        )

        self.assertEqual(session_dir, (self.results / "position-grid-search").resolve())
        with self.assertRaisesRegex(ValueError, "single directory name"):
            run_failure_search._prepare_session_directory(
                self.results, session_directory_name="../escape"
            )
        with self.assertRaisesRegex(ValueError, "single directory name"):
            run_failure_search._prepare_session_directory(
                self.results, session_directory_name="C:"
            )

    def test_atomic_json_rejects_nonfinite_values(self):
        target = self.root / "summary.json"

        with self.assertRaises(ValueError):
            run_failure_search._atomic_write_json(target, {"elapsed_seconds": float("nan")})

        self.assertFalse(target.exists())

    @staticmethod
    def _normalise_config(config):
        return "\n".join(
            line
            for line in config.splitlines()
            if not line.startswith("# Generated")
            and not line.startswith("output_dir: ")
            and not line.startswith("  - name: ")
        )


if __name__ == "__main__":
    unittest.main()
