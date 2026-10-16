"""The faultline command line: dry run, diagnose, resume, replay, image, cases."""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import List

from robot_debug import cli
from robot_debug.orchestrator import request_stop as orch_stop
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

    def test_dry_run_shows_the_plan_even_when_the_backend_rejects_the_spec(self):
        from robot_debug.backends import BackendError

        def rejecting(spec):
            raise BackendError("backend.image must be pinned")
        code = cli.main(["diagnose", str(self.spec_path), "--dry-run"], make_backend=rejecting, tools=FakeTools(),
                        out=self.lines.append)
        self.assertEqual(code, 2)
        self.assertIn("Planned Jobs", self.text)
        self.assertIn("Worst case of the required Jobs", self.text)
        self.assertIn("Backend check failed: backend.image must be pinned", self.text)
        self.assertLess(self.text.index("Planned Jobs"), self.text.index("Backend check failed"))

    def test_dry_run_survives_a_missing_backends_package(self):
        def missing(spec):
            raise ImportError("robot_debug.backends")
        code = cli.main(["diagnose", str(self.spec_path), "--dry-run"], make_backend=missing, tools=FakeTools(),
                        out=self.lines.append)
        self.assertEqual(code, 0)
        self.assertIn("Backend not checked", self.text)


class CandidateBudget(Fixture):
    def test_a_budget_the_reduce_job_cannot_hold_is_a_spec_error_before_anything_exists(self):
        self.spec_path.write_text(SPEC.replace("max_candidates: 36", "max_candidates: 40"), encoding="utf-8")
        for extra in ([], ["--dry-run"]):
            with self.subTest(extra=extra):
                self.lines.clear()
                code = self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)] + extra)
                self.assertEqual(code, 2)
                self.assertIn("largest that fits is 36", self.text)
                self.assertIn("budget.max_candidates 40", self.text)
                self.assertNotIn("Planned Jobs", self.text)
                self.assertEqual(self.backends, [], "no backend was even constructed")
                self.assertFalse(self.runs.exists())

    def test_the_largest_fitting_budget_is_accepted(self):
        self.spec_path.write_text(SPEC.replace("max_candidates: 36", "max_candidates: 36"), encoding="utf-8")
        self.assertEqual(self.run_cli(["diagnose", str(self.spec_path), "--dry-run"]), 0)


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
        self.assertIn("sent and acknowledged", self.text)

    def test_ctrl_c_with_a_failing_cancel_does_not_claim_a_cancel(self):
        from tests.test_orchestrator import BackendFailure
        code = self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)],
                            [finished(lambda w: screen_summary())], interrupt_at_wait=1,
                            cancel_error=BackendFailure("api down"))
        self.assertEqual(code, 130)
        self.assertIn("could not be confirmed", self.text)
        self.assertNotIn("acknowledged", self.text)
        self.assertNotIn("released", self.text)


class ProcessRecord(Fixture):
    """``process.json`` and ``--run-dir-file``: how the control panel finds a run and its folder."""

    def snapshot_during_wait(self, store):
        def look():
            folders = list(self.runs.iterdir())
            store["folder"] = folders[0]
            record = folders[0] / "process.json"
            store["process"] = json.loads(record.read_text(encoding="utf-8")) if record.is_file() else None
            file = store.get("file")
            store["launch"] = file.read_text(encoding="utf-8") if file is not None and file.is_file() else None
        return look

    def test_the_running_process_is_recorded_and_removed_when_the_run_ends(self):
        seen = {}
        code = self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)], full_script(),
                            on_wait=self.snapshot_during_wait(seen))
        self.assertEqual(code, 0)
        self.assertEqual(seen["process"]["pid"], os.getpid())
        self.assertEqual(seen["process"]["command"], "diagnose")
        self.assertRegex(seen["process"]["started_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$")
        self.assertEqual(sorted(seen["process"]), ["command", "pid", "started_at"])
        self.assertFalse((seen["folder"] / "process.json").exists())

    def test_the_record_is_removed_after_a_stop_a_crash_and_ctrl_c(self):
        from tests.test_orchestrator import BackendFailure
        cases = [("stopped", [finished(lambda w: screen_summary(failing=False))], {}, 3),
                 ("crash", [], {"fail_prepare": True}, 1),
                 ("ctrl-c", [finished(lambda w: screen_summary())], {"interrupt_at_wait": 1}, 130)]
        for label, script, setup, expected in cases:
            with self.subTest(label), tempfile.TemporaryDirectory() as root:
                runs = Path(root) / "runs"
                self.assertEqual(self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(runs)],
                                              script, **setup), expected)
                self.assertEqual([p.name for p in next(runs.iterdir()).glob("process.json")], [])

    def test_a_replay_records_its_own_command(self):
        seen = {}
        case_dir = ReplayCommand.case_dir(self)
        self.run_cli(["replay", str(case_dir), "--spec", str(self.spec_path), "--runs-root", str(self.runs)],
                     [finished(lambda w: {"verdict": "still_reproduces", "complete": True})],
                     tools=ReplayCommand.Tools(), on_wait=self.snapshot_during_wait(seen))
        self.assertEqual(seen["process"]["command"], "replay")
        self.assertFalse((seen["folder"] / "process.json").exists())

    def test_the_run_folder_is_written_to_the_run_dir_file_as_soon_as_it_exists(self):
        seen = {"file": self.dir / "launch" / "run-dir.txt"}
        self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs),
                      "--run-dir-file", str(seen["file"])], full_script(), on_wait=self.snapshot_during_wait(seen))
        self.assertEqual(Path(seen["launch"]).resolve(), seen["folder"].resolve())
        self.assertTrue(Path(seen["launch"]).is_absolute())
        self.assertTrue(seen["file"].is_file(), "the launcher can still read it after the run")

    def test_resume_writes_the_resumed_folder(self):
        self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)],
                     [finished(lambda w: screen_summary())], fail_submit_at=1)
        run_dir = next(self.runs.iterdir())
        target = self.dir / "resume-dir.txt"
        script = [finished(reduce_one(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True, reduced=True))]
        self.assertEqual(self.run_cli(["diagnose", "--resume", str(run_dir), "--run-dir-file", str(target)],
                                      script), 0)
        self.assertEqual(Path(target.read_text(encoding="utf-8")).resolve(), run_dir.resolve())
        self.assertFalse((run_dir / "process.json").exists())

    def test_a_dry_run_creates_no_record_and_no_launch_file(self):
        target = self.dir / "run-dir.txt"
        self.assertEqual(self.run_cli(["diagnose", str(self.spec_path), "--dry-run", "--runs-root", str(self.runs),
                                       "--run-dir-file", str(target)]), 0)
        self.assertFalse(target.exists())
        self.assertFalse(self.runs.exists())

    def test_the_option_is_hidden_from_the_help(self):
        self.assertNotIn("run-dir-file", cli._parser().format_help())
        for command in ("diagnose", "replay"):
            parser = cli._parser()._subparsers._group_actions[0].choices[command]
            self.assertNotIn("run-dir-file", parser.format_help())


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

    def test_resume_of_a_run_that_is_still_running_is_refused(self):
        self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)],
                     [finished(lambda w: screen_summary())], fail_submit_at=1)
        run_dir = next(self.runs.iterdir())
        started = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        other = {"pid": os.getppid(), "started_at": started, "command": "diagnose"}
        (run_dir / "process.json").write_text(json.dumps(other), encoding="utf-8")
        self.lines.clear()
        self.assertEqual(self.run_cli(["diagnose", "--resume", str(run_dir)]), 2)
        self.assertIn("already running", self.text)
        self.assertEqual(len(self.backends), 1, "no second backend was built")

    def test_resume_of_something_that_is_not_a_run_folder(self):
        self.assertEqual(self.run_cli(["diagnose", "--resume", str(self.dir)]), 2)


class StopCommand(Fixture):
    def stopped_run(self):
        """A run folder whose first Job the user stopped (the stop request is written while it waits)."""

        def request():
            orch_stop(next(self.runs.iterdir()))
        code = self.run_cli(["diagnose", str(self.spec_path), "--runs-root", str(self.runs)],
                            [finished(lambda w: screen_summary())], on_wait=request,
                            stop_outcome=("CANCELLED", 300))
        return code, next(self.runs.iterdir())

    def run_folder(self, live=True):
        folder = self.runs / "soup-start-20261014T101530Z"
        folder.mkdir(parents=True)
        (folder / "steps.json").write_text("{}", encoding="utf-8")
        if live:                                     # this very process stands in for the running diagnosis
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            (folder / "process.json").write_text(json.dumps(
                {"pid": os.getpid(), "started_at": stamp, "command": "diagnose"}), encoding="utf-8")
        return folder

    def test_stop_writes_the_request_into_a_run_folder(self):
        folder = self.run_folder()
        self.assertEqual(self.run_cli(["stop", str(folder)]), 0)
        self.assertTrue((folder / "stop-request.json").is_file())
        self.assertIn("Stop requested", self.text)
        self.assertIn("--resume", self.text)

    def test_stop_finds_a_run_by_its_folder_name_under_the_runs_root(self):
        folder = self.run_folder()
        self.assertEqual(self.run_cli(["stop", folder.name, "--runs-root", str(self.runs)]), 0)
        self.assertTrue((folder / "stop-request.json").is_file())

    def test_stop_of_a_run_that_is_not_running_says_so_and_writes_nothing(self):
        folder = self.run_folder(live=False)
        self.assertEqual(self.run_cli(["stop", str(folder)]), 2)
        self.assertIn("nothing to stop", self.text)
        self.assertFalse((folder / "stop-request.json").exists())

    def test_stop_of_something_that_is_not_a_run_folder(self):
        self.assertEqual(self.run_cli(["stop", str(self.dir)]), 2)
        self.assertIn("is not a faultline run folder", self.text)
        self.assertFalse((self.dir / "stop-request.json").exists())
        self.assertEqual(self.run_cli(["stop"]), 2)

    def test_a_user_stop_exits_three_and_names_the_resume_command(self):
        code, folder = self.stopped_run()
        self.assertEqual(code, 3)
        self.assertIn("Stopped (stopped_by_user)", self.text)
        self.assertIn("Resume with: faultline diagnose --resume {}".format(folder), self.text)
        self.assertEqual(self.backends[0].finished, 1)
        self.assertFalse((folder / "process.json").exists())

    def test_resume_removes_the_stop_request_and_carries_on(self):
        code, folder = self.stopped_run()
        self.assertTrue((folder / "stop-request.json").is_file())
        self.lines.clear()
        script = [finished(lambda w: screen_summary(failing=False), seconds=500)]
        self.assertEqual(self.run_cli(["diagnose", "--resume", str(folder)], script), 3)
        self.assertFalse((folder / "stop-request.json").exists())
        self.assertIn("no_reproducible_failure", self.text, "it got past the screen on a fresh attempt")
        self.assertTrue(self.backends[1].submitted[0].endswith("-screen-a"))

    def test_a_dry_run_of_a_resume_leaves_the_request_alone(self):
        code, folder = self.stopped_run()
        self.assertEqual(self.run_cli(["diagnose", "--resume", str(folder), "--dry-run"]), 0)
        self.assertTrue((folder / "stop-request.json").is_file())


class ReplayCommand(Fixture):
    class Tools(FakeTools):
        def replay_workload(self, case, run_id, attempts, inputs=None):
            return {"schema_version": 1, "mode": "scenario-replay", "run_id": run_id, "deadline_seconds": 1000}

        def replay_inputs(self, case_dir, case):
            return {"layout": {"fake": True}, "reference_candidate": None}

    def case_dir(self):
        folder = self.dir / "case"
        folder.mkdir(exist_ok=True)
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

    def test_replay_says_plainly_when_it_is_inconclusive(self):
        case_dir = self.case_dir()
        code = self.run_cli(
            ["replay", str(case_dir), "--spec", str(self.spec_path), "--runs-root", str(self.runs)],
            [finished(lambda w: {"verdict": "reference_fails", "complete": True})], tools=self.Tools())
        self.assertEqual(code, 3)
        self.assertIn("Inconclusive: the reference failed", self.text)
        self.assertNotIn("does not say", self.text)

    def test_replay_needs_a_spec(self):
        self.assertEqual(self.run_cli(["replay", str(self.dir)]), 2)

    def replay_expecting(self, verdict, expect, folder="runs"):
        argv = ["replay", str(self.case_dir()), "--spec", str(self.spec_path),
                "--runs-root", str(self.dir / folder)]
        if expect is not None:
            argv += ["--expect", expect]
        return self.run_cli(argv, [finished(lambda w: {"verdict": verdict, "complete": True})],
                            tools=self.Tools())

    def test_expect_exits_0_when_the_verdict_matches(self):
        self.assertEqual(self.replay_expecting("still_reproduces", "reproduces"), 0)
        self.assertIn("Expected 'reproduces': met", self.text)
        self.lines.clear()
        self.assertEqual(self.replay_expecting("no_longer_reproduces", "fixed", "runs2"), 0)
        self.assertIn("Expected 'fixed': met", self.text)

    def test_expect_exits_5_when_the_verdict_is_the_other_decided_one(self):
        self.assertEqual(self.replay_expecting("no_longer_reproduces", "reproduces"), 5)
        self.assertIn("NOT met", self.text)
        self.assertIn("no longer reproduces", self.text)
        self.assertEqual(self.replay_expecting("still_reproduces", "fixed", "runs2"), 5)

    def test_expect_exits_5_for_an_inconclusive_verdict_but_plain_replay_does_not_change(self):
        for verdict in ("reference_fails", "invalid_scene"):
            with self.subTest(verdict=verdict):
                self.lines.clear()
                self.assertEqual(self.replay_expecting(verdict, "reproduces", "with-" + verdict), 5)
                self.assertIn("NOT met", self.text)
                self.assertEqual(self.replay_expecting(verdict, None, "without-" + verdict), 3)

    def test_without_expect_a_decided_verdict_exits_0_whichever_it_is(self):
        self.assertEqual(self.replay_expecting("still_reproduces", None), 0)
        self.assertEqual(self.replay_expecting("no_longer_reproduces", None, "runs2"), 0)

    def test_expect_keeps_exit_3_when_the_replay_never_reached_a_verdict(self):
        code = self.run_cli(
            ["replay", str(self.case_dir()), "--spec", str(self.spec_path), "--runs-root", str(self.runs),
             "--expect", "reproduces"],
            [{"state": "FAILED", "reason": "ContainerFailed", "container_seconds": 100, "summary": None,
              "summary_name": "scenario_summary.json"}], tools=self.Tools())
        self.assertEqual(code, 3)
        self.assertNotIn("Expected", self.text)

    def test_expect_rejects_an_unknown_word_and_replay_accepts_env_file(self):
        self.assertEqual(self.run_cli(["replay", str(self.dir), "--spec", str(self.spec_path),
                                       "--expect", "passes"]), 2)
        self.lines.clear()
        code = self.run_cli(
            ["replay", str(self.case_dir()), "--spec", str(self.spec_path), "--runs-root", str(self.runs),
             "--env-file", str(self.dir / ".env")],
            [finished(lambda w: {"verdict": "still_reproduces", "complete": True})], tools=self.Tools())
        self.assertEqual(code, 0)


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
