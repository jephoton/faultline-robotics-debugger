"""Process liveness, active runs and run progress for the control panel (ADR 0033).

Every run folder here is synthetic: fake names, fake Job names and obviously fake ids.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from robot_debug.viewer import processes as px
from robot_debug.viewer.stop_reasons import STOP_TEXTS, needs_attention, stop_text

FAKE_JOB_ID = "aijob-fakefakefake0001"
FAKE_JOB_NAME = "demo-2610170102-screen"
STARTED = "2026-10-17T01:02:03.000Z"
STARTED_EPOCH = px.parse_stamp(STARTED)
ALIVE, DEAD = 4242, 4343


def probe_for(alive=(ALIVE,), created=None):
    return lambda pid: px.ProcessInfo(pid in alive, created)


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")


class Folders(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "runs"
        self.root.mkdir()

    def make_run(self, name="demo-20261017T010203Z", mode="scenario", steps=None, run=None, pid=ALIVE,
                 ledger=None, started=STARTED, spec=None):
        folder = self.root / name
        data = {"schema_version": 1, "name": name.rsplit("-", 1)[0], "mode": mode, "steps": steps or {}}
        if run is not None:
            data["run"] = run
        write(folder / "steps.json", data)
        write(folder / "ledger.json", ledger or {
            "schema_version": 1, "cap_usd": 10.0, "max_hours": 5.0, "hourly_usd": 1.8, "elapsed_seconds": 100.0,
            "spent_usd": 0.5, "reserved_usd": 1.2, "jobs": {}})
        if spec is not None:
            write(folder / "spec.yaml", spec)
        if pid is not None:
            write(folder / "process.json", {"pid": pid, "started_at": started, "command": "diagnose"})
        return folder


class LivenessTests(unittest.TestCase):
    def record(self, pid=ALIVE, started=STARTED):
        return {"pid": pid, "started_at": started, "command": "diagnose"}

    def test_a_live_process_is_alive_and_a_dead_one_is_not(self):
        self.assertTrue(px.process_alive(self.record(), probe_for()))
        self.assertFalse(px.process_alive(self.record(pid=DEAD), probe_for()))

    def test_a_process_created_after_the_record_is_a_reused_process_id(self):
        later = STARTED_EPOCH + 3600
        self.assertFalse(px.process_alive(self.record(), probe_for(created=later)))
        near = STARTED_EPOCH + 1
        self.assertTrue(px.process_alive(self.record(), probe_for(created=near)), "creation precedes started_at")
        earlier = STARTED_EPOCH - 3
        self.assertTrue(px.process_alive(self.record(), probe_for(created=earlier)))

    def test_an_unknown_creation_time_does_not_hide_a_live_run(self):
        self.assertTrue(px.process_alive(self.record(), probe_for(created=None)))

    def test_a_malformed_record_is_not_a_live_run(self):
        for bad in (None, [], {}, {"pid": "12", "started_at": STARTED}, {"pid": ALIVE},
                    {"pid": ALIVE, "started_at": "yesterday"}, {"pid": True, "started_at": STARTED},
                    {"pid": -1, "started_at": STARTED}):
            with self.subTest(bad=bad):
                self.assertFalse(px.process_alive(bad, probe_for(alive=(ALIVE, -1, 1))))

    def test_the_operating_system_probe_knows_this_process_and_a_finished_one(self):
        info = px.default_probe(os.getpid())
        self.assertTrue(info.alive)
        if info.created is not None:
            self.assertLessEqual(info.created, time.time() + 1)
            self.assertGreater(info.created, time.time() - 86400 * 365)
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.assertFalse(px.default_probe(child.pid).alive)
        for pid in (0, -5, "x", None):
            self.assertFalse(px.default_probe(pid).alive)


class ActiveRunTests(Folders):
    def test_only_runs_with_a_live_process_are_active(self):
        self.make_run("live-20261017T010203Z", pid=ALIVE)
        self.make_run("crashed-20261017T010203Z", pid=DEAD)
        self.make_run("finished-20261017T010203Z", pid=None, run={"status": "completed"})
        (self.root / "stray-file.txt").write_text("x", encoding="utf-8")
        found = px.active_runs(self.root, probe_for())
        self.assertEqual([r["run"] for r in found], ["live-20261017T010203Z"])
        self.assertEqual(sorted(found[0]), ["attention", "cap_usd", "mode", "name", "run", "spent_usd", "status", "step"])
        self.assertEqual((found[0]["status"], found[0]["name"], found[0]["mode"]), ("running", "live", "scenario"))
        self.assertEqual((found[0]["spent_usd"], found[0]["cap_usd"]), (0.5, 10.0))

    def test_a_missing_runs_folder_has_no_active_runs(self):
        self.assertEqual(px.active_runs(self.root / "nowhere", probe_for()), [])

    def test_a_pending_stop_request_makes_the_run_stopping(self):
        folder = self.make_run()
        write(folder / "stop-request.json", {"requested_at": "2026-10-17T01:10:00Z"})
        [run] = px.active_runs(self.root, probe_for())
        self.assertEqual(run["status"], "stopping")
        progress = px.run_progress(self.root, folder.name, probe_for())
        self.assertEqual((progress["status"], progress["stoppable"]), ("stopping", False))

    def test_a_reused_process_id_hides_the_run(self):
        self.make_run()
        self.assertEqual(px.active_runs(self.root, probe_for(created=STARTED_EPOCH + 9999)), [])

    def test_the_current_step_is_the_first_one_not_done(self):
        steps = {"screen": {"status": "done"}, "plan": {"status": "done"}, "reduce": {"status": "running"}}
        self.make_run(steps=steps)
        [run] = px.active_runs(self.root, probe_for())
        self.assertEqual(run["step"], "Reduce the cause")


class ProgressTests(Folders):
    def progress(self, folder, **kwargs):
        return px.run_progress(self.root, folder.name, probe_for(), **kwargs)

    def scenario_steps(self, **extra):
        steps = {
            "screen": {"status": "done", "state": "COMPLETED", "cost_usd": 0.4, "job_name": "demo-2610170102-screen",
                       "job_id": FAKE_JOB_ID,
                       "attempts": [{"job_name": "demo-2610170102-screen", "job_id": FAKE_JOB_ID, "state": "settled"}]},
            "plan": {"status": "done"},
            "reduce": {"status": "running", "attempts": [
                {"job_name": "demo-2610170102-reduce", "job_id": FAKE_JOB_ID, "state": "submitted"}]},
        }
        steps.update(extra)
        return steps

    def test_a_run_whose_process_died_mid_job_reads_as_interrupted_and_resumable(self):
        # The header still says how the segment before the resume ended; process.json was left by a killed process.
        folder = self.make_run(steps=self.scenario_steps(), run={"status": "failed"}, pid=DEAD)
        progress = self.progress(folder)
        self.assertEqual(progress["status"], "interrupted")
        self.assertEqual(progress["stop_reason"], "process_ended")
        self.assertIn("Resume re-attaches", progress["stop_text"])
        self.assertTrue(progress["resumable"])
        self.assertTrue(progress["attention"])
        self.assertFalse(progress["stoppable"])

    def test_no_failure_found_is_a_finished_result_not_a_stop_to_resume(self):
        steps = {"paraphrase": {"status": "done"}, "screen": {"status": "done", "state": "COMPLETED", "attempts": []}}
        folder = self.make_run(mode="paraphrase", steps=steps, pid=None,
                               run={"status": "stopped", "reason": "no_reproducible_failure"})
        progress = self.progress(folder)
        self.assertEqual(progress["status"], "completed")
        self.assertFalse(progress["resumable"])
        self.assertFalse(progress["attention"])
        self.assertEqual(progress["library_id"], "r-" + folder.name)
        self.assertEqual(progress["stop_text"], "No failure repeated 4 of 5 times.")
        later = {row["key"]: row["status"] for row in progress["steps"]}
        self.assertEqual(later["reduce"], "skipped")

    def test_a_cleanly_finished_run_keeps_its_own_status(self):
        folder = self.make_run(steps=self.scenario_steps(), run={"status": "completed"}, pid=None)
        self.assertEqual(self.progress(folder)["status"], "completed")

    def test_the_timeline_lists_every_planned_step_in_order(self):
        folder = self.make_run(steps=self.scenario_steps())
        progress = self.progress(folder)
        self.assertEqual([s["key"] for s in progress["steps"]],
                         ["screen", "plan", "reduce", "report", "case", "explain", "register"])
        by_key = {s["key"]: s for s in progress["steps"]}
        self.assertEqual((by_key["screen"]["status"], by_key["screen"]["state"]), ("done", "COMPLETED"))
        self.assertEqual((by_key["reduce"]["status"], by_key["reduce"]["attempts"]), ("running", 1))
        self.assertEqual(by_key["report"]["status"], "pending")
        self.assertEqual(by_key["screen"]["label"], "Screen the starts")
        self.assertEqual(sorted(by_key["screen"]), ["attempts", "capacity_waits", "key", "label", "state", "status"])

    def test_continuations_and_an_imported_start_join_the_timeline(self):
        steps = self.scenario_steps(import_={}, reduce2={"status": "running"})
        steps["import"] = steps.pop("import_")
        steps["import"].update(status="done")
        folder = self.make_run(steps=steps)
        keys = [s["key"] for s in self.progress(folder)["steps"]]
        self.assertEqual(keys[:1], ["import"])
        self.assertEqual(keys[keys.index("reduce") + 1], "reduce2")
        labels = {s["key"]: s["label"] for s in self.progress(folder)["steps"]}
        self.assertEqual(labels["reduce2"], "Continue the reduction (2)")

    def test_the_other_modes_have_their_own_timelines(self):
        for mode, keys in (("paraphrase", ["paraphrase", "screen", "reduce", "report", "case", "register"]),
                           ("audit", ["audit", "report", "case", "register"]), ("replay", ["replay"])):
            with self.subTest(mode=mode):
                folder = self.make_run("{}-20261017T010203Z".format(mode), mode=mode)
                self.assertEqual([s["key"] for s in self.progress(folder)["steps"]], keys)

    def test_the_import_step_is_planned_when_the_spec_imports_a_start(self):
        spec = "scenario:\n  task: 3\n  import: starts/fake.json\nbudget: {max_spend_usd: 10, max_hours: 5}\n"
        folder = self.make_run(spec=spec)
        self.assertEqual(self.progress(folder)["steps"][0]["key"], "import")

    def test_money_time_and_the_cap_come_from_the_ledger(self):
        folder = self.make_run(steps=self.scenario_steps())
        progress = self.progress(folder, now=lambda: (folder / "ledger.json").stat().st_mtime + 30)
        self.assertEqual((progress["spent_usd"], progress["reserved_usd"], progress["cap_usd"]), (0.5, 1.2, 10.0))
        self.assertEqual(progress["max_hours"], 5.0)
        self.assertAlmostEqual(progress["elapsed_seconds"], 130.0, delta=0.5)
        self.assertEqual(progress["status"], "running")
        self.assertTrue(progress["stoppable"])
        self.assertFalse(progress["resumable"])

    def test_elapsed_time_of_a_finished_run_is_the_ledger_value(self):
        folder = self.make_run(pid=None, run={"status": "completed"})
        self.assertEqual(self.progress(folder, now=lambda: time.time() + 99999)["elapsed_seconds"], 100.0)

    def test_the_budget_comes_from_the_spec_until_the_ledger_exists(self):
        folder = self.make_run(spec="budget: {max_spend_usd: 7.5, max_hours: 2}\n")
        (folder / "ledger.json").unlink()
        progress = self.progress(folder)
        self.assertEqual((progress["cap_usd"], progress["max_hours"], progress["spent_usd"]), (7.5, 2.0, 0.0))

    def test_job_phases_follow_the_last_attempt(self):
        cases = [("submitting", False, "submitting"), ("submitted", False, "running"),
                 ("unconfirmed", False, "running"), ("submitted", True, "downloading"),
                 ("capacity", False, "waiting_for_gpu"), ("settled", False, "settled")]
        for state, has_result, phase in cases:
            with self.subTest(state=state, result=has_result):
                steps = {"screen": {"status": "running", "attempts": [{"job_name": FAKE_JOB_NAME, "state": state}]}}
                folder = self.make_run(steps=steps)
                if has_result:
                    write(folder / "jobs" / FAKE_JOB_NAME / "result.json", {})
                self.assertEqual(self.progress(folder)["job"], {"name": FAKE_JOB_NAME, "phase": phase})

    def test_capacity_waits_are_counted_and_need_attention(self):
        steps = {"screen": {"status": "running", "attempts": [
            {"job_name": "demo-2610170102-screen", "state": "capacity"},
            {"job_name": "demo-2610170102-screen-a", "state": "capacity"}]}}
        folder = self.make_run(steps=steps)
        progress = self.progress(folder)
        self.assertEqual(progress["steps"][0]["capacity_waits"], 2)
        self.assertEqual(progress["job"]["phase"], "waiting_for_gpu")
        self.assertTrue(progress["attention"])

    def test_a_run_with_a_job_running_needs_no_attention(self):
        self.assertFalse(self.progress(self.make_run(steps=self.scenario_steps()))["attention"])

    def test_a_finished_run_has_no_job_and_the_case_in_the_library(self):
        steps = self.scenario_steps()
        steps["reduce"]["status"] = "done"
        steps["register"] = {"status": "done", "case_id": "ab" * 32}
        folder = self.make_run(steps=steps, pid=None, run={"status": "completed", "reason": None})
        progress = self.progress(folder)
        self.assertEqual((progress["status"], progress["job"], progress["library_id"]), ("completed", None, "d-" + "ab" * 32))
        self.assertEqual((progress["resumable"], progress["stoppable"], progress["attention"]), (False, False, False))
        self.assertIsNone(progress["step"])
        self.assertEqual({s["status"] for s in progress["steps"] if s["key"] == "explain"}, {"skipped"})

    def test_a_stopped_run_says_why_in_plain_words_and_can_resume(self):
        folder = self.make_run(steps=self.scenario_steps(), pid=None,
                               run={"status": "stopped", "reason": "budget_exhausted", "detail": "raw detail"})
        progress = self.progress(folder)
        self.assertEqual(progress["status"], "stopped")
        self.assertEqual(progress["stop_reason"], "budget_exhausted")
        self.assertEqual(progress["stop_text"], STOP_TEXTS["budget_exhausted"])
        self.assertTrue(progress["resumable"])
        self.assertTrue(progress["attention"])
        self.assertNotIn("raw detail", json.dumps(progress))

    def test_a_clean_negative_result_is_not_an_alarm(self):
        folder = self.make_run(pid=None, run={"status": "stopped", "reason": "no_reproducible_failure"})
        self.assertFalse(self.progress(folder)["attention"])

    def test_an_expired_sign_in_reads_as_such(self):
        folder = self.make_run(pid=None, run={
            "status": "stopped", "reason": "backend_error",
            "detail": "waiting failed (BackendError: the nebius CLI sign-in has expired: run any nebius command)"})
        progress = self.progress(folder)
        self.assertEqual(progress["stop_text"], STOP_TEXTS["auth_expired"])
        self.assertEqual(progress["stop_reason"], "backend_error")

    def test_a_replay_cannot_be_resumed(self):
        folder = self.make_run(mode="replay", pid=None, run={"status": "stopped", "reason": "replay_inconclusive"})
        self.assertFalse(self.progress(folder)["resumable"])

    def test_a_run_that_died_without_a_final_status_is_interrupted_and_resumable(self):
        folder = self.make_run(steps=self.scenario_steps(), pid=DEAD)
        progress = self.progress(folder)
        self.assertEqual((progress["status"], progress["resumable"], progress["stoppable"]), ("interrupted", True, False))
        self.assertTrue(progress["attention"])

    def test_failed_and_interrupted_statuses_pass_through(self):
        for status in ("failed", "interrupted"):
            with self.subTest(status=status):
                folder = self.make_run("{}-20261017T010203Z".format(status), pid=None, run={"status": status})
                self.assertEqual(self.progress(folder)["status"], status)

    def test_a_resumed_run_shows_no_stop_from_its_earlier_segment(self):
        folder = self.make_run(steps=self.scenario_steps(), run={"status": "stopped", "reason": "stopped_by_user"})
        progress = self.progress(folder)
        self.assertEqual((progress["status"], progress["stop_reason"], progress["stop_text"]), ("running", None, None))

    def test_the_log_tail_is_the_last_forty_lines_with_ids_and_paths_removed(self):
        folder = self.make_run(steps=self.scenario_steps())
        lines = ["10:{:02d} screen ... line {}".format(i % 60, i) for i in range(80)]
        lines[-1] = "10:59 reduce ... re-attaching to demo-reduce {} in C:\\Users\\someone\\runs\\demo and /home/someone/x/y".format(
            FAKE_JOB_ID)
        write(folder / "run.log", "\n".join(lines) + "\n")
        tail = self.progress(folder)["log_tail"]
        self.assertEqual(len(tail), 40)
        self.assertEqual(tail[0], lines[40])
        self.assertIn("aijob-fake...", tail[-1])
        self.assertNotIn(FAKE_JOB_ID, tail[-1])
        self.assertNotIn("someone", tail[-1])
        self.assertIn("[local path omitted]", tail[-1])

    def test_the_log_is_found_through_the_launch_record_and_may_be_missing(self):
        folder = self.make_run(steps=self.scenario_steps())
        self.assertEqual(self.progress(folder)["log_tail"], [])
        elsewhere = self.root.parent / "launch" / "run.log"
        write(elsewhere, "hello\nworld\n")
        write(folder / "ui-launch.json", {"log": str(elsewhere)})
        self.assertEqual(self.progress(folder)["log_tail"], ["hello", "world"])

    def test_long_log_lines_are_cut(self):
        folder = self.make_run()
        write(folder / "run.log", "x" * 5000 + "\n")
        self.assertEqual(len(self.progress(folder)["log_tail"][0]), px.LOG_LINE_LIMIT)

    def test_nothing_secret_or_local_reaches_the_response(self):
        steps = self.scenario_steps()
        folder = self.make_run(steps=steps)
        write(folder / "backend-state.json", {"project_id": "project-fakeproject", "bucket_name": "fake-bucket-name"})
        text = json.dumps(self.progress(folder))
        for forbidden in (FAKE_JOB_ID, "project-fakeproject", "fake-bucket-name", str(self.root), "job_id"):
            self.assertNotIn(forbidden, text)

    def test_run_names_are_bare_folder_names(self):
        self.make_run()
        for bad in ("", "..", "../x", "a/b", "a\\b", "C:\\x", "x" * 300, None, 5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                px.run_progress(self.root, bad, probe_for())
        with self.assertRaises(FileNotFoundError):
            px.run_progress(self.root, "nothing-20261017T010203Z", probe_for())

    def test_a_broken_steps_file_is_not_found(self):
        folder = self.make_run()
        write(folder / "steps.json", "{not json")
        with self.assertRaises(FileNotFoundError):
            px.run_progress(self.root, folder.name, probe_for())


class StepLabelTests(unittest.TestCase):
    def test_a_paraphrase_run_screens_rewordings_not_starts(self):
        rows = {row["key"]: row["label"] for row in px.step_rows("paraphrase", {}, {}, None)}
        self.assertEqual(rows["screen"], "Screen the rewordings")
        self.assertEqual(rows["reduce"], "Reduce the wording")

    def test_a_scenario_run_keeps_the_start_wording(self):
        rows = {row["key"]: row["label"] for row in px.step_rows("scenario", {}, {}, None)}
        self.assertEqual(rows["screen"], "Screen the starts")


class ScrubTextTests(unittest.TestCase):
    """The text scrubber hides local paths without damaging URLs (review L3)."""

    OMITTED = "[local path omitted]"

    def test_https_urls_are_left_alone(self):
        for text in ("see https://example.invalid/docs/page", "http://example.invalid:8080/a/b", "ftp://host/x",
                     "fetched https://example.invalid/a/b.json ok", "file:///not-a-path"):
            with self.subTest(text=text):
                scrubbed = px.scrub_text(text)
                self.assertNotIn("local path", scrubbed)
                self.assertIn("//", scrubbed)

    def test_windows_paths_with_spaces_are_removed_whole(self):
        for text, hidden in (
                (r"Run folder: C:\Users\First Last\Documents\runs\demo", ("First", "Last", "Documents")),
                ("loaded D:/Work Files/Jane Doe/spec.yaml", ("Work", "Jane", "Doe", "spec.yaml")),
                (r"error in 'C:\Users\First Last\x.json' while", ("First", "Last")),
                (r'open "C:\Program Files\Faultline\a.log"', ("Program", "Faultline"))):
            with self.subTest(text=text):
                scrubbed = px.scrub_text(text)
                self.assertIn(self.OMITTED, scrubbed)
                for word in hidden:
                    self.assertNotIn(word, scrubbed)

    def test_text_around_a_quoted_path_survives(self):
        scrubbed = px.scrub_text(r"error in 'C:\Users\First Last\x.json' while loading")
        self.assertTrue(scrubbed.endswith("' while loading"), scrubbed)

    def test_posix_home_paths_are_removed(self):
        for text in ("saved to /home/someone/work/runs/demo", "at /Users/someone/Library/x.json done",
                     "log /tmp/pytest-of-someone/run1/log.txt"):
            with self.subTest(text=text):
                scrubbed = px.scrub_text(text)
                self.assertIn(self.OMITTED, scrubbed)
                self.assertNotIn("someone", scrubbed)

    def test_a_url_next_to_a_path_keeps_the_url(self):
        scrubbed = px.scrub_text("fetched https://example.invalid/a/b to /home/someone/x/y")
        self.assertIn("https://example.invalid/a/b", scrubbed)
        self.assertNotIn("someone", scrubbed)


class StopTextTests(unittest.TestCase):
    def test_the_table_has_the_contract_sentences(self):
        self.assertEqual(stop_text("budget_exhausted"),
                         "Stopped at the candidate budget; this is the smallest cause found so far.")
        self.assertEqual(stop_text("no_reproducible_failure"), "No failure repeated 4 of 5 times.")
        self.assertEqual(stop_text("stopped_by_user"), "Stopped from the control panel or `faultline stop`.")
        self.assertEqual(stop_text("something_new"), "Stopped: something_new.")
        self.assertIsNone(stop_text(None))
        self.assertEqual(len(STOP_TEXTS), 15)
        self.assertIn("Resume re-attaches", stop_text("process_ended"))

    def test_attention_excludes_only_a_clean_negative_result(self):
        self.assertFalse(needs_attention("no_reproducible_failure"))
        self.assertFalse(needs_attention(None))
        for reason in ("budget_exhausted", "nominal_controls_failed", "capacity_unavailable", "backend_error",
                       "stopped_by_user", "something_new"):
            self.assertTrue(needs_attention(reason), reason)


if __name__ == "__main__":
    unittest.main()
