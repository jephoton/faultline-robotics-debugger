"""``faultline diagnose`` mode 1 with ``scenario.import``: a failing start the user brings."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from robot_debug import cli
from robot_debug import orchestrator as orch
from robot_debug import scenario_state as ss
from robot_debug import spec as sp
from robot_debug.scenario_import import build_candidate, write_scenario_candidate
from tests.scenario_fakes import base_state, synthetic_layout, with_object_pose
from tests.test_orchestrator import (
    BOTH, SOUP, SOUP_ONLY, BOWL, FakeBackend, FakeTools, finished, make_world, reduce_summary, screen_summary,
    spec_for)

FAIL_SOURCE = {"kind": "benchmark", "init_state_index": 31}


def failing_state():
    base = base_state(synthetic_layout())
    return with_object_pose(with_object_pose(base, SOUP, dxyz=(0.05, 0, 0)), BOWL, dxyz=(0, 0.04, 0))


def imported_reduce(**kwargs):
    """The reduce Job's summary, with the imported provenance the real Job copies into the plan."""

    def build(workload):
        summary = reduce_summary(workload, **kwargs)
        failing = workload["failing"]
        if failing["start_index"] is None:
            summary["plan"]["failing_source"] = failing["source"]
            summary["plan"]["failing_import"] = failing["import"]
        return summary
    return build


def all_failing_screen():
    summary = screen_summary()
    for record in summary["tasks"]["3"]["starts"].values():
        record["outcomes"] = ["policy_failure"] * 5
        record["decision"] = "reproduces"
    return summary


class Fixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)

    def candidate_file(self, suite="libero_10", task=3, state=None, name="failing.candidate.json"):
        candidate = build_candidate(suite, task, failing_state() if state is None else state, FAIL_SOURCE)
        path = self.dir / name
        write_scenario_candidate(path, candidate)
        return path, candidate

    def spec(self, path, **scenario):
        return spec_for(scenario=dict({"task": 3, "import": str(path)}, **scenario))

    def world(self, spec, behaviours, **options):
        temp, runner, backend, tools, ledger, lines = make_world(spec, behaviours, **options)
        self.addCleanup(temp.cleanup)
        return runner, backend, tools, ledger, lines


class EndToEnd(Fixture):
    def script(self):
        return [finished(lambda w: screen_summary()),
                finished(imported_reduce(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True,
                                         reduced=True))]

    def test_screen_the_pool_then_reduce_the_imported_start_and_record_where_it_came_from(self):
        path, candidate = self.candidate_file()
        runner, backend, tools, ledger, lines = self.world(self.spec(path), self.script())
        result = runner.diagnose()
        run_dir = runner.run_dir
        self.assertEqual((result.status, result.reason), ("completed", None))
        tag = runner.tag
        self.assertEqual(["soup-start-{}-screen".format(tag), "soup-start-{}-reduce".format(tag)], backend.submitted)

        screen, reduce_ = (backend.workloads[name] for name in backend.submitted)
        self.assertEqual(list(range(20)), screen["start_indices"], "the default pool, without any failing start")
        failing = reduce_["failing"]
        self.assertIsNone(failing["start_index"])
        self.assertEqual(candidate["state"], failing["state"])
        self.assertEqual(FAIL_SOURCE, failing["source"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual({"file_sha256": digest, "state_sha256": candidate["state_sha256"]}, failing["import"])
        self.assertEqual(1, reduce_["references"][0]["start_index"], "the nearest passing start of the pool")

        steps = json.loads((run_dir / "steps.json").read_text())["steps"]
        self.assertEqual((digest, candidate["state_sha256"], FAIL_SOURCE),
                         (steps["import"]["file_sha256"], steps["import"]["state_sha256"], steps["import"]["source"]))
        self.assertEqual(path.read_bytes(), (run_dir / "import" / "candidate.json").read_bytes())

        case = json.loads((run_dir / "case.json").read_text())
        self.assertIsNone(case["failing_start"])
        self.assertEqual({"file_sha256": digest, "state_sha256": candidate["state_sha256"], "source": FAIL_SOURCE},
                         case["failing_import"])
        self.assertEqual(1, case["reference_start"])
        self.assertEqual("hybrid", case["replay"]["candidate"]["source"]["kind"])
        self.assertIsNone(case["replay"]["candidate"]["source"]["failing"])
        report = (run_dir / "report.md").read_text()
        self.assertIn("imported (file sha256 {}".format(digest[:12]), report)
        self.assertEqual([run_dir], tools.registered)
        self.assertEqual(1, len(tools.explained))

    def test_a_replay_can_be_built_from_the_case_of_an_imported_start(self):
        path, _candidate = self.candidate_file()
        runner, *_ = self.world(self.spec(path), self.script())
        self.assertEqual("completed", runner.diagnose().status)
        case = json.loads((runner.run_dir / "case.json").read_text())
        inputs = FakeTools().replay_inputs(runner.run_dir, case)
        workload = FakeTools().replay_workload(case, "diag-replay-1", 5, inputs)
        self.assertEqual("scenario-replay", workload["mode"])
        self.assertEqual(["minimal", "reference"], [scene["name"] for scene in workload["scenes"]])

    def test_a_pool_and_a_pinned_reference_choose_what_is_screened(self):
        path, _ = self.candidate_file()
        runner, backend, *_ = self.world(self.spec(path, pool="0-9"), self.script())
        runner.diagnose()
        self.assertEqual(list(range(10)), backend.workloads[backend.submitted[0]]["start_indices"])
        path, _ = self.candidate_file(name="second.json")
        runner, backend, *_ = self.world(self.spec(path, reference=2), self.script())
        self.assertEqual("completed", runner.diagnose().status)
        self.assertEqual([2], backend.workloads[backend.submitted[0]]["start_indices"])
        self.assertEqual([2], [r["start_index"] for r in backend.workloads[backend.submitted[1]]["references"]])

    def test_a_continuation_keeps_the_imported_provenance(self):
        path, candidate = self.candidate_file()
        script = [finished(lambda w: screen_summary()),
                  finished(imported_reduce(stop_reason="budget_exhausted", selection=BOTH, entity_minimal=False),
                           state="FAILED", reason="ContainerFailed"),
                  finished(imported_reduce(stop_reason="reduced", selection=SOUP_ONLY, entity_minimal=True,
                                           reduced=True))]
        runner, backend, *_ = self.world(self.spec(path), script)
        self.assertEqual("completed", runner.diagnose().status)
        follow_up = backend.workloads[backend.submitted[2]]["failing"]
        self.assertIsNone(follow_up["start_index"])
        self.assertEqual(FAIL_SOURCE, follow_up["source"])
        self.assertEqual(candidate["state_sha256"], follow_up["import"]["state_sha256"])

    def test_resume_reads_the_copy_in_the_run_folder_and_never_resubmits(self):
        path, _ = self.candidate_file()
        spec = self.spec(path)
        runner, backend, *_ = self.world(spec, self.script())
        runner.diagnose()
        path.unlink()                                                    # the original has moved away
        backend2 = FakeBackend([])
        _t, runner2, backend2, *_rest = make_world(spec, [], backend=backend2, run_dir=runner.run_dir)
        self.addCleanup(_t.cleanup)
        self.assertEqual("completed", runner2.diagnose().status)
        self.assertEqual([], backend2.submitted)


class Refusals(Fixture):
    def assert_refused_before_anything(self, spec, reason):
        runner, backend, *_ = self.world(spec, [])
        result = runner.diagnose()
        self.assertEqual((result.status, result.reason), ("stopped", reason))
        self.assertEqual((backend.prepared, backend.submitted), (0, []))
        return result

    def test_a_missing_or_invalid_file_is_refused_before_any_job(self):
        self.assert_refused_before_anything(self.spec(self.dir / "nope.json"), "import_invalid")
        broken = self.dir / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        self.assert_refused_before_anything(self.spec(broken), "import_invalid")
        good, candidate = self.candidate_file()
        tampered = json.loads(good.read_text())
        tampered["state"][3] += 1.0                                      # the state no longer matches its digest
        bad = self.dir / "tampered.json"
        bad.write_text(json.dumps(tampered), encoding="utf-8")
        self.assert_refused_before_anything(self.spec(bad), "import_invalid")

    def test_another_suite_or_task_is_refused_before_any_job(self):
        path, _ = self.candidate_file(suite="libero_object")
        self.assert_refused_before_anything(self.spec(path), "import_mismatch")
        other_task, _ = self.candidate_file(task=4, name="task4.json")
        self.assert_refused_before_anything(self.spec(other_task), "import_mismatch")
        runner, *_ = self.world(self.spec(path), [])
        runner.diagnose()
        detail = runner.steps.data["run"]["detail"]
        self.assertIn("libero_object task 3", detail)
        self.assertIn("libero_10 task 3", detail)

    def test_the_command_line_makes_it_a_spec_error_and_a_dry_run_validates_it_too(self):
        path, _ = self.candidate_file(suite="libero_spatial")
        spec_path = self.dir / "spec.yaml"
        spec_path.write_text(
            "faultline: 1\nname: imp\nmode: scenario\npolicy: {suite: libero_10}\n"
            "scenario: {task: 3, import: " + json.dumps(str(path)) + "}\n"
            "budget: {max_spend_usd: 5, max_hours: 2}\nbackend:\n  kind: nebius\n"
            "  image: cr.example.invalid/REGISTRY_ID/faultline@sha256:IMAGE_DIGEST\n"
            "  hf_token_secret: faultline-hf-token\n  hourly_usd: 1.8\n", encoding="utf-8")
        for extra in ([], ["--dry-run"]):
            lines, backends = [], []
            code = cli.main(["diagnose", str(spec_path), "--runs-root", str(self.dir / "runs")] + extra,
                            make_backend=lambda spec: backends.append(spec), tools=FakeTools(), out=lines.append)
            self.assertEqual(2, code)
            self.assertIn("libero_spatial task 3", "\n".join(lines))
            self.assertEqual([], backends)
            self.assertFalse((self.dir / "runs").exists())

    def test_a_dry_run_of_a_good_import_lists_the_jobs(self):
        path, _ = self.candidate_file()
        lines, required = orch.dry_run_lines(self.spec(path), FakeTools())
        text = "\n".join(lines)
        self.assertIn("reduce the imported failing start", text)
        self.assertIn("not screened", text)
        self.assertIn("screen task 3 starts " + ",".join(str(i) for i in range(20)), text)
        self.assertGreater(required, 0)


class NoReference(Fixture):
    def test_a_pool_without_a_passing_start_stops_with_no_reference_and_a_screen_table(self):
        path, _ = self.candidate_file()
        runner, backend, tools, ledger, lines = self.world(
            self.spec(path), [finished(lambda w: all_failing_screen())])
        result = runner.diagnose()
        self.assertEqual((result.status, result.reason), ("stopped", "no_reference"))
        self.assertEqual(1, len(backend.submitted), "no reduce Job")
        self.assertFalse((runner.run_dir / "case.json").exists())
        self.assertTrue(any("start 0:" in line for line in lines))

    def test_a_pinned_reference_that_did_not_pass_stops(self):
        path, _ = self.candidate_file()
        runner, backend, *_ = self.world(
            self.spec(path, reference=0), [finished(lambda w: screen_summary())])      # start 0 fails
        result = runner.diagnose()
        self.assertEqual("reference_not_passing", result.reason)
        self.assertEqual(1, len(backend.submitted))

    def test_the_imported_start_failing_its_own_gate_ends_with_a_report_but_no_case(self):
        path, _ = self.candidate_file()
        script = [finished(lambda w: screen_summary()),
                  finished(imported_reduce(stop_reason="failing_not_reproducible", selection={},
                                           entity_minimal=False), state="FAILED", reason="ContainerFailed")]
        runner, backend, tools, *_ = self.world(self.spec(path), script)
        result = runner.diagnose()
        self.assertEqual((result.status, result.reason), ("stopped", "failing_not_reproducible"))
        self.assertTrue((runner.run_dir / "report.md").is_file())
        self.assertFalse((runner.run_dir / "case.json").exists())
        self.assertEqual([], tools.registered)

    def test_a_state_of_another_scene_stops_at_planning_with_a_clear_message(self):
        path, _ = self.candidate_file(state=failing_state()[:-3], name="short.json")
        runner, backend, *_ = self.world(self.spec(path), [finished(lambda w: screen_summary())])
        result = runner.diagnose()
        self.assertEqual("plan_failed", result.reason)
        self.assertIn("imported start", runner.steps.data["run"]["detail"])


if __name__ == "__main__":
    unittest.main()
