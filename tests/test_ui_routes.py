"""The control-panel API end to end: a real server, real guard, fake Popen, fake Nebius CLI."""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path

from robot_debug import spec as sp
from robot_debug.viewer import launcher as lc
from robot_debug.viewer import processes
from robot_debug.viewer.environment import Environment
from robot_debug.viewer.library import Library
from robot_debug.viewer.specs import SpecService
from tests import ui_fixtures as fx
from tests.test_orchestrator import FakeTools
from tests.test_ui_environment import FakeLauncher, FakeRunner
from tests.test_ui_launcher import FakePopen, Ticker
from tests.test_ui_specs import IMPORTING, SCENARIO, candidate_text
from tests.ui_server import RunningServer

NOW = dt.datetime(2026, 10, 17, 1, 2, 3, tzinfo=dt.timezone.utc)


def alive_here(pid):
    return processes.ProcessInfo(pid == os.getpid(), None)


class RoutesCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.paths = fx.build(self.base)
        self.artifacts, self.runs = self.paths["artifacts"], self.paths["runs"]
        self.stamp = lambda: NOW
        self.specs = SpecService(self.artifacts, tools=FakeTools(), clock=self.stamp)
        self.ticker = Ticker()
        self.popen = FakePopen(self.runs, run_name="started-20261017T010203Z")
        self.launcher = lc.Launcher(
            self.artifacts, self.runs, self.specs, popen=self.popen, env={"PATH": "/bin"}, probe=alive_here,
            sleep=self.ticker.sleep, clock=self.ticker.clock, discover_seconds=5.0, win32=False,
            env_file=self.base / "none.env")
        self.environment = Environment(self.specs, env_file=self.base / "none.env", environ={}, runner=FakeRunner(),
                                       which=lambda name: None, launcher_factory=FakeLauncher)
        # the fixture's live run (scenario-live) has no process record: the server below should see no active run
        self.server = RunningServer(self.artifacts, runs_root=self.runs, specs=self.specs, launcher=self.launcher,
                                    environment=self.environment, app_root=self.base / "no-app")
        self.addCleanup(self.server.close)

    def get(self, path):
        status, headers, body = self.server.request("GET", path)
        return status, headers, body

    def get_json(self, path):
        status, headers, body = self.get(path)
        return status, json.loads(body)

    def drop_live_process(self):
        """Remove the fake child's process record so the next start is allowed."""

        for folder in self.runs.iterdir():
            (folder / "process.json").unlink(missing_ok=True)


class ReadRoutes(RoutesCase):
    def test_the_library_list_and_detail(self):
        status, listing = self.get_json("/api/library")
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["items"]), 6)
        first = next(i for i in listing["items"] if i["id"] == "d-" + fx.SCENARIO_ID)
        status, detail = self.get_json("/api/library/" + first["id"])
        self.assertEqual((status, detail["fault_code"], detail["replayable"]), (200, first["fault_code"], True))
        self.assertEqual(detail["scenario"]["differences_count"], 4)

    def test_a_case_whose_evidence_cannot_be_read_is_a_503_sentence_not_a_crash(self):
        # the fixture's occlusion case is not real evidence: the case store refuses to revalidate it
        status, payload = self.get_json("/api/library/m-" + fx.OCCLUSION_ID)
        self.assertEqual((status, payload["error"]), (503, "This case's evidence is temporarily unavailable."))
        self.assertEqual(self.get_json("/api/library")[0], 200, "the list does not depend on it")

    def test_unknown_and_malformed_ids_are_a_plain_404(self):
        for path in ("/api/library/d-" + "0" * 64, "/api/library/x", "/api/library/..%2f..%2fsecret",
                     "/api/library/d-" + "0" * 64 + "/files/report.md", "/api/library/%00"):
            with self.subTest(path=path):
                status, payload = self.get_json(path)
                self.assertEqual(status, 404)
                self.assertEqual(set(payload), {"error", "errors"})

    def test_case_files_are_served_as_text_with_paths_removed(self):
        status, headers, body = self.get("/api/library/d-{}/files/report.md".format(fx.SCENARIO_ID))
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/markdown; charset=utf-8")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn(b"someone", body)
        status, headers, body = self.get("/api/library/d-{}/files/case.json".format(fx.SCENARIO_ID))
        self.assertEqual((status, headers["Content-Type"]), (200, "application/json; charset=utf-8"))
        self.assertEqual(json.loads(body)["case_id"], fx.SCENARIO_ID)
        for name in ("diagnosis.json", "steps.json", "backend-state.json", "..%2fx"):
            self.assertEqual(self.get("/api/library/d-{}/files/{}".format(fx.SCENARIO_ID, name))[0], 404, name)

    def test_no_run_is_active_until_a_live_process_is_recorded(self):
        self.assertEqual(self.get_json("/api/runs/active"), (200, {"runs": []}))
        folder = self.runs / fx.LIVE_RUN
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        (folder / "process.json").write_text(json.dumps({"pid": os.getpid(), "started_at": stamp, "command": "diagnose"}),
                                             encoding="utf-8")
        status, payload = self.get_json("/api/runs/active")
        self.assertEqual([r["run"] for r in payload["runs"]], [fx.LIVE_RUN])
        status, progress = self.get_json("/api/runs/{}/progress".format(fx.LIVE_RUN))
        self.assertEqual((status, progress["status"], progress["stoppable"]), (200, "running", True))

    def test_progress_of_a_finished_run_and_of_nothing(self):
        status, progress = self.get_json("/api/runs/{}/progress".format(fx.SCENARIO_RUN))
        self.assertEqual((status, progress["status"], progress["library_id"]), (200, "stopped", "d-" + fx.SCENARIO_ID))
        self.assertEqual(progress["stop_text"], "Stopped at the candidate budget; this is the smallest cause found so far.")
        for bad in ("nothing-20261017T000000Z", "..%2f", "a%2fb"):
            self.assertEqual(self.get_json("/api/runs/{}/progress".format(bad))[0], 404, bad)
        text = json.dumps(progress)
        for private in (fx.FAKE_JOB_ID, fx.FAKE_PROJECT, fx.FAKE_BUCKET, str(self.base)):
            self.assertNotIn(private, text)

    def test_environment(self):
        status, payload = self.get_json("/api/environment")
        self.assertEqual(status, 200)
        self.assertEqual([c["key"] for c in payload["checks"]], ["nebius_cli", "token_factory_key", "spec_template", "docker", "tavily_key"])

    def test_templates_need_no_token(self):
        status, payload = self.get_json("/api/specs/template?mode=audit")
        self.assertEqual(status, 200)
        self.assertIn("mode: audit", payload["yaml"])
        self.assertEqual(self.get_json("/api/specs/template?mode=nonsense")[0], 400)
        self.assertEqual(self.get_json("/api/specs/template")[0], 400)

    def test_evidence_and_the_old_endpoints_still_work(self):
        self.assertEqual(self.get("/api/evidence")[0], 200)
        self.assertEqual(self.get("/api/runs")[0], 200)
        self.assertEqual(self.get("/api/diagnoses")[0], 200)
        self.assertEqual(self.get("/api/health")[0], 200)

    def test_diagnosis_videos_are_served_from_the_media_route(self):
        status, detail = self.get_json("/api/library/d-" + fx.SCENARIO_ID)
        url = detail["videos"][0]["url"]
        status, headers, body = self.get(url)
        self.assertEqual((status, body), (200, b"fake mp4 original"))
        self.assertEqual(headers["Content-Type"], "video/mp4")


class ControlRoutes(RoutesCase):
    def test_validate(self):
        status, payload = self.server.post_json("/api/specs/validate", {"yaml": SCENARIO})
        self.assertEqual((status, payload["ok"], payload["errors"], payload["summary"]["name"]), (200, True, [], "demo-start"))
        status, payload = self.server.post_json("/api/specs/validate", {"yaml": SCENARIO.replace("task: 3", "task: 99")})
        self.assertEqual((status, payload["ok"], payload["errors"][0]["path"]), (200, False, "scenario.task"))
        status, payload = self.server.post_json("/api/specs/validate", {})
        self.assertEqual((status, payload["ok"]), (200, False))

    def dry_run(self, text=SCENARIO, **extra):
        status, payload = self.server.post_json("/api/specs/dry-run", dict({"yaml": text}, **extra))
        self.assertEqual(status, 200, payload)
        return payload

    def test_dry_run(self):
        plan = self.dry_run()
        self.assertEqual([j["name"] for j in plan["jobs"]][:2], ["screen", "reduce"])
        self.assertRegex(plan["plan_hash"], r"^[0-9a-f]{64}$")
        status, payload = self.server.post_json("/api/specs/dry-run", {"yaml": SCENARIO.replace("max_candidates: 36", "max_candidates: 40")})
        self.assertEqual((status, payload["errors"][0]["path"]), (400, "budget.max_candidates"))

    def start(self, text=SCENARIO, plan=None, **extra):
        plan = plan or self.dry_run(text, **{k: v for k, v in extra.items() if k == "import_file"})
        return self.server.post_json("/api/runs", dict({"yaml": text, "plan_hash": plan["plan_hash"]}, **extra))

    def test_start_runs_the_confirmed_plan_in_a_detached_process(self):
        status, payload = self.start()
        self.assertEqual((status, payload), (202, {"run": "started-20261017T010203Z", "library_id": None}))
        argv = self.popen.calls[0]["argv"]
        self.assertEqual(argv[3], "diagnose")
        saved = Path(argv[4])
        self.assertEqual(saved.parent.parent, self.artifacts / "specs-ui")
        self.assertEqual(sp.load_spec(saved).name, "demo-start", "the run can be repeated from a terminal")
        self.assertEqual(payload["run"], "started-20261017T010203Z")

    def test_a_second_start_is_a_409_while_the_first_runs(self):
        self.assertEqual(self.start()[0], 202)
        status, payload = self.start(SCENARIO.replace("demo-start", "demo-second"))
        self.assertEqual(status, 409)
        self.assertIn("Another run is active", payload["error"])
        self.assertEqual(len(self.popen.calls), 1)

    def test_the_plan_hash_is_checked_against_a_fresh_dry_run(self):
        plan = self.dry_run()
        changed = SCENARIO.replace("max_spend_usd: 10.0", "max_spend_usd: 9.0")
        status, payload = self.server.post_json("/api/runs", {"yaml": changed, "plan_hash": plan["plan_hash"]})
        self.assertEqual(status, 412)
        self.assertIn("plan changed", payload["error"])
        for bad in (None, "", "0" * 64):
            status, payload = self.server.post_json("/api/runs", {"yaml": SCENARIO, "plan_hash": bad})
            self.assertEqual(status, 412, bad)
        status, payload = self.server.post_json("/api/runs", {"yaml": SCENARIO})
        self.assertEqual(status, 412)
        self.assertEqual(self.popen.calls, [])

    def test_a_replay_spec_cannot_start_a_diagnosis_and_no_llm_cannot_start_a_paraphrase(self):
        replay = self.specs_template("replay")
        plan = self.dry_run(replay)
        status, payload = self.server.post_json("/api/runs", {"yaml": replay, "plan_hash": plan["plan_hash"]})
        self.assertEqual(status, 400)
        paraphrase = self.specs_template("paraphrase")
        plan = self.dry_run(paraphrase)
        status, payload = self.server.post_json("/api/runs", {"yaml": paraphrase, "plan_hash": plan["plan_hash"], "no_llm": True})
        self.assertEqual((status, "Nemotron" in payload["error"]), (400, True))
        status, payload = self.server.post_json("/api/runs", {"yaml": paraphrase, "plan_hash": plan["plan_hash"], "no_llm": "yes"})
        self.assertEqual(status, 400)
        self.assertEqual(self.popen.calls, [])

    def specs_template(self, mode):
        return self.get_json("/api/specs/template?mode=" + mode)[1]["yaml"]

    def test_a_start_file_travels_with_the_request_and_is_saved_beside_the_spec(self):
        file = {"name": "start.json", "content": candidate_text()}
        plan = self.dry_run(IMPORTING, import_file=file)
        status, payload = self.server.post_json("/api/runs", {"yaml": IMPORTING, "plan_hash": plan["plan_hash"], "import_file": file})
        self.assertEqual(status, 202, payload)
        saved = sp.load_spec(Path(self.popen.calls[0]["argv"][4]))
        self.assertEqual(Path(saved.scenario.import_path).read_text(encoding="utf-8"), file["content"])
        other = {"name": "start.json", "content": candidate_text(index=11)}
        self.drop_live_process()
        status, payload = self.server.post_json("/api/runs", {"yaml": IMPORTING, "plan_hash": plan["plan_hash"], "import_file": other})
        self.assertEqual(status, 412, "a different start file is a different plan")

    def test_stop_and_resume(self):
        self.assertEqual(self.start()[0], 202)
        run = "started-20261017T010203Z"
        status, payload = self.server.post_json("/api/runs/{}/stop".format(run), {})
        self.assertEqual((status, payload), (202, {"status": "stopping"}))
        self.assertTrue((self.runs / run / "stop-request.json").is_file())
        status, payload = self.server.post_json("/api/runs/{}/resume".format(run), {})
        self.assertEqual(status, 409, "still running")
        self.drop_live_process()
        (self.runs / run / "stop-request.json").unlink()
        (self.runs / run / "steps.json").write_text(json.dumps(fx.steps_document("started", "scenario", {}, {
            "status": "stopped", "reason": "stopped_by_user"})), encoding="utf-8")
        self.popen.run_name = run
        status, payload = self.server.post_json("/api/runs/{}/resume".format(run), {})
        self.assertEqual((status, payload), (202, {"run": run}))
        self.assertEqual(self.popen.calls[-1]["argv"][3:5], ["diagnose", "--resume"])

    def test_resume_with_larger_limits_and_with_bad_ones(self):
        self.assertEqual(self.start()[0], 202)
        run = "started-20261017T010203Z"
        self.drop_live_process()
        (self.runs / run / "steps.json").write_text(json.dumps(fx.steps_document("started", "scenario", {}, {
            "status": "stopped", "reason": "spend_cap"})), encoding="utf-8")
        (self.runs / run / "spec.yaml").write_text(fx.spec_text("started", "scenario"), encoding="utf-8")
        calls = len(self.popen.calls)
        for body in ({"max_spend_usd": "9"}, {"max_hours": True}, {"max_spend_usd": 1}):
            status, payload = self.server.post_json("/api/runs/{}/resume".format(run), body)
            self.assertEqual(status, 400, body)
        self.assertEqual(len(self.popen.calls), calls, "a bad request starts nothing")
        self.popen.run_name = run
        status, payload = self.server.post_json("/api/runs/{}/resume".format(run),
                                                {"max_spend_usd": 25, "max_hours": 8})
        self.assertEqual((status, payload), (202, {"run": run}))
        spec = (self.runs / run / "spec.yaml").read_text(encoding="utf-8")
        self.assertIn("max_spend_usd: 25", spec)
        self.assertIn("max_hours: 8", spec)

    def test_stop_and_resume_of_unknown_or_idle_runs(self):
        for action in ("stop", "resume"):
            status, payload = self.server.post_json("/api/runs/nothing-20261017T000000Z/{}".format(action), {})
            self.assertEqual(status, 404, action)
        status, payload = self.server.post_json("/api/runs/{}/stop".format(fx.SCENARIO_RUN), {})
        self.assertEqual(status, 409)

    def replay_spec(self, suite=None):
        text = self.specs_template("replay")
        return text if suite is None else text.replace("mode: replay\n", "mode: replay\npolicy: {{suite: {}}}\n".format(suite))

    def test_replay_a_case(self):
        text = self.replay_spec()
        plan = self.dry_run(text)
        body = {"yaml": text, "plan_hash": plan["plan_hash"], "expect": "fixed"}
        self.popen.run_name = "replay-started-20261017T010203Z"
        status, payload = self.server.post_json("/api/library/d-{}/replay".format(fx.SCENARIO_ID), body)
        self.assertEqual((status, payload), (202, {"run": "replay-started-20261017T010203Z"}))
        argv = self.popen.calls[0]["argv"]
        self.assertEqual(argv[3], "replay")
        self.assertEqual(Path(argv[4]), self.paths["diagnoses"] / fx.SCENARIO_ID)
        self.assertEqual(argv[argv.index("--expect") + 1], "fixed")

    def test_replay_refusals(self):
        text = self.replay_spec()
        plan = self.dry_run(text)
        body = {"yaml": text, "plan_hash": plan["plan_hash"]}
        post = lambda item, payload: self.server.post_json("/api/library/{}/replay".format(item), payload)  # noqa: E731
        self.assertEqual(post("d-" + "0" * 64, body)[0], 404)
        self.assertEqual(post("d-" + fx.SCENARIO_ID_TWIN, body)[0], 409, "no replay inputs")
        self.assertEqual(post("d-" + fx.AUDIT_ID, body)[0], 409, "not a scenario case")
        self.assertEqual(post("d-" + fx.SCENARIO_ID, dict(body, expect="maybe"))[0], 400)
        self.assertEqual(post("d-" + fx.SCENARIO_ID, dict(body, plan_hash="0" * 64))[0], 412)
        self.assertEqual(post("d-" + fx.SCENARIO_ID, dict(body, plan_hash=None))[0], 412)
        scenario_plan = self.dry_run(SCENARIO)
        status, payload = post("d-" + fx.SCENARIO_ID, {"yaml": SCENARIO, "plan_hash": scenario_plan["plan_hash"]})
        self.assertEqual(status, 400)
        other = self.replay_spec("libero_object")
        other_plan = self.dry_run(other)
        status, payload = post("d-" + fx.SCENARIO_ID, {"yaml": other, "plan_hash": other_plan["plan_hash"]})
        self.assertEqual((status, payload["errors"][0]["path"]), (400, "policy.suite"))
        self.assertEqual(self.popen.calls, [])

    def test_a_replay_is_refused_while_a_run_is_active(self):
        self.assertEqual(self.start()[0], 202)
        text = self.replay_spec()
        plan = self.dry_run(text)
        status, payload = self.server.post_json("/api/library/d-{}/replay".format(fx.SCENARIO_ID),
                                                {"yaml": text, "plan_hash": plan["plan_hash"]})
        self.assertEqual(status, 409)

    def test_every_control_refuses_a_request_without_the_session_token(self):
        for path in ("/api/specs/validate", "/api/specs/dry-run", "/api/runs", "/api/runs/x/stop", "/api/runs/x/resume",
                     "/api/library/d-{}/replay".format(fx.SCENARIO_ID)):
            with self.subTest(path=path):
                status, headers, body = self.server.request("POST", path, {"yaml": SCENARIO},
                                                            {"Origin": self.server.origin})
                self.assertEqual(status, 403)
        self.assertEqual(self.popen.calls, [])
        self.assertFalse((self.artifacts / "specs-ui").exists())

    def test_a_remote_page_cannot_start_a_run_even_with_a_guessed_plan(self):
        plan = self.dry_run()
        status, headers, body = self.server.request(
            "POST", "/api/runs", {"yaml": SCENARIO, "plan_hash": plan["plan_hash"]},
            {"Origin": "http://evil.example", "X-Faultline-Token": self.server.guard.token})
        self.assertEqual(status, 403)
        self.assertEqual(self.popen.calls, [])


class AppServingTests(RoutesCase):
    def setUp(self):
        super().setUp()
        self.app = self.base / "no-app"
        (self.app / "assets").mkdir(parents=True)
        (self.app / "fonts").mkdir()
        (self.app / "index.html").write_text("<!doctype html><title>Faultline</title>", encoding="utf-8")
        (self.app / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
        (self.app / "assets" / "index-abc123.css").write_text("body{}", encoding="utf-8")
        (self.app / "fonts" / "barlow.woff2").write_bytes(b"wOF2")
        (self.app / "favicon.svg").write_text("<svg/>", encoding="utf-8")
        (self.base / "secret.txt").write_text("secret", encoding="utf-8")

    def test_the_index_is_served_for_the_root_and_for_app_routes(self):
        for path in ("/", "/index.html", "/case/d-" + fx.SCENARIO_ID, "/new", "/run/some-run", "/setup", "/evidence"):
            with self.subTest(path=path):
                status, headers, body = self.get(path)
                self.assertEqual(status, 200)
                self.assertIn(b"<title>Faultline</title>", body)
                self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
                self.assertEqual(headers["Cache-Control"], "no-store")

    def test_hashed_assets_are_cached_for_a_year_and_typed(self):
        status, headers, body = self.get("/assets/index-abc123.js")
        self.assertEqual((status, body), (200, b"console.log(1)"))
        self.assertEqual(headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertEqual(headers["Content-Type"], "text/javascript; charset=utf-8")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.get("/assets/index-abc123.css")[1]["Content-Type"], "text/css; charset=utf-8")

    def test_other_bundle_files_are_not_cached_forever(self):
        status, headers, body = self.get("/fonts/barlow.woff2")
        self.assertEqual((status, headers["Content-Type"], headers["Cache-Control"]), (200, "font/woff2", "no-store"))
        self.assertEqual(self.get("/favicon.svg")[1]["Content-Type"], "image/svg+xml")

    def test_missing_files_and_non_app_paths_are_404_not_the_index(self):
        for path in ("/missing.js", "/assets/missing.js", "/fonts/none.woff2", "/api/nonsense", "/media/nothing.mp4",
                     "/data/library.json"):
            with self.subTest(path=path):
                status, headers, body = self.get(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"<title>", body)

    def test_the_bundle_cannot_be_escaped(self):
        for path in ("/../secret.txt", "/..%2fsecret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt",
                     "/assets/..%5c..%5csecret.txt", "/assets/%00"):
            with self.subTest(path=path):
                status, headers, body = self.get(path)
                self.assertNotIn(b"secret", body)
                self.assertIn(status, (200, 400, 404))

    def test_without_a_bundle_the_root_says_the_front_end_is_not_built(self):
        import shutil

        shutil.rmtree(str(self.app))
        for path in ("/", "/index.html"):
            with self.subTest(path=path):
                status, headers, body = self.get(path)
                self.assertEqual(status, 503)
                self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
                self.assertIn("npm --prefix web run build", json.loads(body)["error"])
        self.assertEqual(self.get("/diagnoses")[0], 404)
        self.assertEqual(self.get("/api/health")[0], 200)
        self.assertEqual(self.get("/case/anything")[0], 404)


class ReplayPlanRoutes(RoutesCase):
    """The replay's dry run is for the case being replayed (M3)."""

    AUDIT_ID = "ab" * 32
    WORDING_ID = "cd" * 32

    def setUp(self):
        super().setUp()
        from robot_debug.case_register import register_run

        audit = {"schema_version": 1, "kind": "audit", "case_id": self.AUDIT_ID, "suite": "libero_10", "task_id": 3,
                 "start_index": 0, "complete": True, "stop_reason": None,
                 "families": {"blur": {"threshold_severity": 0.4, "stop_reason": "threshold_found"},
                              "lighting": {"threshold_severity": 0.8, "stop_reason": "threshold_found"}},
                 "replay": {"kind": "audit", "attempts": 5, "required_failures": 4, "groups": [
                     {"step": "probe-image-1", "families": [{"family": "blur", "severity": 0.4}]},
                     {"step": "probe-scene-1", "families": [{"family": "lighting", "severity": 0.8}]}]}}
        run = fx.make_run(self.runs, "stress-20261017T010203Z", "audit", {"register": {"status": "done"}},
                          {"status": "completed"}, report="# r\n", case=audit, spec_name="stress")
        register_run(run, self.artifacts / "diagnoses")

    def replay_spec(self):
        return self.get_json("/api/specs/template?mode=replay")[1]["yaml"]

    def plan(self, item, **extra):
        status, payload = self.server.post_json("/api/specs/dry-run", dict({"yaml": self.replay_spec()}, **extra))
        self.assertEqual(status, 200, payload)
        return payload

    def test_the_dry_run_of_a_stress_test_replay_lists_its_jobs(self):
        plain = self.plan("d-" + self.AUDIT_ID)
        planned = self.plan("d-" + self.AUDIT_ID, case_id="d-" + self.AUDIT_ID)
        self.assertEqual([j["name"] for j in plain["jobs"]], ["replay"])
        self.assertEqual([j["name"] for j in planned["jobs"]], ["replay", "replay-2"])
        self.assertNotEqual(planned["plan_hash"], plain["plan_hash"])

    def test_a_replay_needs_the_plan_of_its_own_case(self):
        text = self.replay_spec()
        item = "/api/library/d-{}/replay".format(self.AUDIT_ID)
        generic = self.plan("x")["plan_hash"]
        status, payload = self.server.post_json(item, {"yaml": text, "plan_hash": generic})
        self.assertEqual(status, 412, "the case-less plan is not the plan of this case")
        right = self.plan("x", case_id="d-" + self.AUDIT_ID)["plan_hash"]
        self.popen.run_name = "replay-started-20261017T010203Z"
        status, payload = self.server.post_json(item, {"yaml": text, "plan_hash": right})
        self.assertEqual(status, 202, payload)

    def test_an_unknown_or_malformed_case_id_in_a_dry_run_is_a_404(self):
        for case_id in ("d-" + "0" * 64, "x", "d-../../etc", 5):
            with self.subTest(case_id=case_id):
                status, payload = self.server.post_json(
                    "/api/specs/dry-run", {"yaml": self.replay_spec(), "case_id": case_id})
                self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
