"""The faultline command line: dry run, diagnose, resume, replay, image, cases."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import List

from robot_debug import cli
from tests.test_orchestrator import (
    BOTH, SOUP_ONLY, Crash, FakeBackend, FakeTools, finished, full_script, reduce_one, screen_summary)

ROOT = Path(__file__).parents[1]
SPEC = """\
faultline: 1
name: soup-start
mode: scenario
policy: {suite: libero_10}
scenario: {task: 3, start: 0}
budget: {max_spend_usd: 10.0, max_hours: 5, max_candidates: 36}
nemotron: {hypothesis: true, explain: true}
backend:
  kind: nebius
  image: cr.example.invalid/REGISTRY_ID/faultline@sha256:IMAGE_DIGEST
  hf_token_secret: faultline-hf-token
  hourly_usd: 1.8
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.spec_path = self.dir / "spec.yaml"
        self.spec_path.write_text(SPEC, encoding="utf-8")
        self.runs = self.dir / "runs"
        self.lines: List[str] = []
        self.backends: List[FakeBackend] = []

    def factory(self, behaviours=None, **setup):
        def make(spec):
            backend = FakeBackend(list(behaviours or []))
            for key, value in setup.items():
                setattr(backend, key, value)
            self.backends.append(backend)
            return backend
        return make

    def run_cli(self, argv, behaviours=None, tools=None, **setup):
        return cli.main(argv, make_backend=self.factory(behaviours, **setup), tools=tools or FakeTools(),
                        out=self.lines.append, poll_seconds=0.0)

    @property
    def text(self):
        return "\n".join(self.lines)


class DryRun(Fixture):
    def test_dry_run_prints_the_plan_and_creates_nothing(self):
        code = self.run_cli(["diagnose", str(self.spec_path), "--dry-run", "--runs-root", str(self.runs)])
        self.assertEqual(code, 0)
        self.assertIn("Planned Jobs", self.text)
        self.assertIn("worst case", self.text)
        self.assertIn("nothing was created", self.text)
        self.assertFalse(self.runs.exists())
        self.assertEqual(len(self.backends), 1, "the backend is constructed to validate the spec")
        backend = self.backends[0]
        self.assertEqual((backend.prepared, backend.submitted, backend.finished), (0, [], 0))

    def test_dry_run_survives_a_missing_backends_package(self):
        def missing(spec):
            raise ImportError("robot_debug.backends")
        code = cli.main(["diagnose", str(self.spec_path), "--dry-run"], make_backend=missing, tools=FakeTools(),
                        out=self.lines.append)
        self.assertEqual(code, 0)
        self.assertIn("Backend not checked", self.text)


class Diagnose(Fixture):
    def test_full_run_exit_code_and_summary(self):
        code = self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)], full_script())
        self.assertEqual(code, 0)
        folders = list(self.runs.iterdir())
        self.assertEqual(len(folders), 1)
        self.assertTrue(folders[0].name.startswith("soup-start-"))
        self.assertTrue((folders[0] / "report.md").is_file())
        self.assertIn("Completed", self.text)
        self.assertIn("Spent: US$", self.text)
        self.assertEqual(self.backends[0].finished, 1)
        self.assertEqual((folders[0] / "spec.yaml").read_text(encoding="utf-8"), SPEC)

    def test_stopped_run_exits_three(self):
        code = self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)],
                            [finished(lambda w: screen_summary(failing=False))])
        self.assertEqual(code, 3)
        self.assertIn("no_reproducible_failure", self.text)

    def test_no_llm_flag_reaches_the_orchestrator(self):
        tools = FakeTools()
        self.run_cli(["diagnose", str(self.spec_path), "--no-llm", "--runs-root", str(self.runs)],
                     full_script(), tools=tools)
        self.assertEqual(tools.explained, [])
        self.assertEqual(self.backends[0].workloads[self.backends[0].submitted[1]]["order_source"], "fixed_order")

    def test_env_file_is_passed_on_but_never_printed(self):
        tools = FakeTools()
        env = self.dir / "secrets.env"
        env.write_text("NEBIUS_API_KEY=SECRET-VALUE\n", encoding="utf-8")
        self.run_cli(["diagnose", str(self.spec_path), "--env-file", str(env), "--runs-root", str(self.runs)],
                     full_script(), tools=tools)
        self.assertEqual(tools.explained[0][2], env)
        self.assertNotIn("SECRET-VALUE", self.text)

    def test_invalid_spec_exits_two_and_names_the_key(self):
        self.spec_path.write_text(SPEC.replace("max_spend_usd: 10.0, ", ""), encoding="utf-8")
        code = self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)])
        self.assertEqual(code, 2)
        self.assertIn("max_spend_usd", self.text)
        self.assertFalse(self.runs.exists())
        self.assertEqual(self.backends, [])

    def test_usage_errors_exit_two(self):
        self.assertEqual(self.run_cli(["diagnose"]), 2)
        self.assertEqual(self.run_cli(["frobnicate"]), 2)
        self.assertEqual(self.run_cli([]), 2)

    def test_replay_spec_is_refused_by_diagnose(self):
        self.spec_path.write_text("faultline: 1\nname: r\nmode: replay\nbudget: {max_spend_usd: 1, max_hours: 1}\n"
                                  "backend: {kind: local, image: faultline:dev}\n", encoding="utf-8")
        self.assertEqual(self.run_cli(["diagnose", str(self.spec_path)]), 2)

    def test_unexpected_errors_are_one_clean_line_and_the_backend_is_finished(self):
        code = self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)], fail_prepare=True)
        self.assertEqual(code, 1)
        self.assertIn("error: BackendFailure", self.text)
        self.assertNotIn("Traceback", self.text)
        self.assertEqual(self.backends[0].finished, 1)

    def test_ctrl_c_exits_130_and_names_the_resume_command(self):
        code = self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)],
                            [finished(lambda w: screen_summary())], interrupt_at_wait=1)
        self.assertEqual(code, 130)
        self.assertIn("--resume", self.text)
        backend = self.backends[0]
        self.assertEqual(backend.cancelled, backend.submitted)
        self.assertEqual(backend.finished, 1)


class Resume(Fixture):
    def test_resume_continues_without_repeating_paid_jobs(self):
        first = self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)],
                             [finished(lambda w: screen_summary())], fail_submit_at=1)
        self.assertEqual(first, 3)
        run_dir = next(self.runs.iterdir())
        self.lines.clear()
        script = [finished(reduce_one(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True, reduced=True))]
        second = self.run_cli(["diagnose", "--resume", str(run_dir)], script)
        self.assertEqual(second, 0)
        self.assertEqual(len(self.backends[1].submitted), 1)
        self.assertEqual(len(list(self.runs.iterdir())), 1, "no new run folder")

    def test_resume_accepts_the_matching_spec_and_refuses_a_different_one(self):
        self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)],
                     [finished(lambda w: screen_summary())], fail_submit_at=1)
        run_dir = next(self.runs.iterdir())
        other = self.dir / "other.yaml"
        other.write_text(SPEC.replace("max_spend_usd: 10.0", "max_spend_usd: 99.0"), encoding="utf-8")
        self.assertEqual(self.run_cli(["diagnose", str(other), "--resume", str(run_dir)]), 2)
        self.assertIn("differs", self.text)

    def test_resume_of_something_that_is_not_a_run_folder(self):
        self.assertEqual(self.run_cli(["diagnose", "--resume", str(self.dir)]), 2)


class ReplayCommand(Fixture):
    class Tools(FakeTools):
        def replay_workload(self, case, run_id, attempts, inputs=None):
            return {"schema_version": 1, "mode": "scenario-replay", "run_id": run_id, "deadline_seconds": 1000}

        def replay_inputs(self, case_dir, case):
            return {"layout": {"fake": True}, "reference_candidate": None}

    def case_dir(self):
        folder = self.dir / "case"
        folder.mkdir()
        (folder / "case.json").write_text(json.dumps({"kind": "scenario_reduction", "case_id": "cd" * 32,
                                                        "suite": "libero_10"}), encoding="utf-8")
        return folder

    def test_replay_prints_whether_it_reproduces(self):
        case_dir = self.case_dir()
        for reproduces, words in ((True, "still reproduces"), (False, "no longer reproduces")):
            with self.subTest(reproduces=reproduces):
                self.lines.clear()
                code = self.run_cli(
                    ["replay", str(case_dir), "--spec", str(self.spec_path),
                     "--runs-root", str(self.runs / str(reproduces))],
                    [finished(lambda w, r=reproduces: {"verdict": "still_reproduces" if r else "no_longer_reproduces", "complete": True})],
                    tools=self.Tools())
                self.assertEqual(code, 0)
                self.assertIn(words, self.text)

    def test_replay_needs_a_spec(self):
        self.assertEqual(self.run_cli(["replay", str(self.dir)]), 2)


class ImageCommand(Fixture):
    class Module:
        def __init__(self):
            self.calls = []

        def build(self, tag):
            self.calls.append(("build", tag))
            return "built " + tag

        def push(self, registry):
            self.calls.append(("push", registry))
            return "pushed to " + registry

    def test_build_push_delegate_to_image_cmd(self):
        module = self.Module()
        self.assertEqual(cli.main(["image", "build", "--tag", "t:1"], image_module=module, out=self.lines.append), 0)
        self.assertEqual(cli.main(["image", "build", "--push", "reg.example.invalid/x"], image_module=module,
                                  out=self.lines.append), 0)
        self.assertEqual(cli.main(["image", "push", "reg.example.invalid/y"], image_module=module,
                                  out=self.lines.append), 0)
        self.assertEqual(module.calls, [("build", "t:1"), ("build", "faultline-serverless:local"),
                                        ("push", "reg.example.invalid/x"), ("push", "reg.example.invalid/y")])
        self.assertIn("built t:1", self.text)


class CasesCommand(Fixture):
    def test_cases_lists_run_folders(self):
        self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)], full_script())
        self.lines.clear()
        self.assertEqual(cli.main(["cases", "--runs-root", str(self.runs)], out=self.lines.append), 0)
        self.assertEqual(len(self.lines), 1)
        self.assertIn("completed", self.lines[0])
        self.assertIn("case ", self.lines[0])

    def test_cases_with_no_runs(self):
        self.assertEqual(cli.main(["cases", "--runs-root", str(self.runs)], out=self.lines.append), 0)
        self.assertIn("no runs", self.text)


class PackagingTests(unittest.TestCase):
    def test_pyproject_declares_the_script_and_the_cloud_extra(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('faultline = "robot_debug.cli:main"', text)
        self.assertIn('cloud = ["boto3", "truststore"]', text)


if __name__ == "__main__":
    unittest.main()
