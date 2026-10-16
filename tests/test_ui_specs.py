"""Spec templates, validation, dry runs, plan hashes and saved specs (ADR 0033, API contract version 1)."""

from __future__ import annotations

import datetime as dt
import json
import re
import tempfile
import unittest
from pathlib import Path

from robot_debug import orchestrator as orch
from robot_debug import spec as sp
from robot_debug.scenario_import import candidate_from_benchmark, write_scenario_candidate
from robot_debug.viewer import specs as vs
from robot_debug.viewer.security import ApiError
from tests.scenario_world import FakeSimulation
from tests.test_orchestrator import FakeTools

FAKE_IMAGE = "cr.example.invalid/fakeregistryid0001/faultline-serverless@sha256:" + "ab" * 32
LOCAL_SPEC = """\
faultline: 1
name: local-spec
mode: replay
budget: {max_spend_usd: 1.0, max_hours: 1}
backend:
  kind: nebius
  project: from-cli-profile
  platform: gpu-l40s-a
  preset: 1gpu-16vcpu-64gb
  image: %s
  hf_token_secret: fake-hf-secret
  hourly_usd: 1.7468
""" % FAKE_IMAGE
FIXED_NOW = dt.datetime(2026, 10, 17, 1, 2, 3, tzinfo=dt.timezone.utc)

SCENARIO = """\
faultline: 1
name: demo-start
mode: scenario
policy: {suite: libero_10}
scenario: {task: 3, start: 0}
budget: {max_spend_usd: 10.0, max_hours: 5, max_candidates: 36}
nemotron: {hypothesis: true, explain: true}
backend:
  kind: nebius
  image: cr.example.invalid/REGISTRY_ID/faultline-serverless@sha256:IMAGE_DIGEST
  hf_token_secret: faultline-hf-token
  hourly_usd: 1.8
"""
IMPORTING = SCENARIO.replace("scenario: {task: 3, start: 0}", "scenario: {task: 0, import: start.json}") \
    .replace("name: demo-start", "name: demo-import")


def candidate_text(suite="libero_10", task=0, index=9) -> str:
    state = FakeSimulation().state_for(index)
    candidate = candidate_from_benchmark(suite, task, index, state)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "c.json"
        write_scenario_candidate(path, candidate)
        return path.read_text(encoding="utf-8")


class ServiceCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "artifacts"
        self.root.mkdir()
        self.service = self.make()

    def make(self, **options):
        options.setdefault("tools", FakeTools())
        options.setdefault("clock", lambda: FIXED_NOW)
        return vs.SpecService(self.root, **options)

    def add_local_spec(self, text=LOCAL_SPEC, name="local.yaml"):
        path = self.root / "specs-local" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class TemplateTests(ServiceCase):
    def test_every_mode_has_a_template_that_validates(self):
        for mode in vs.TEMPLATE_FILES:
            with self.subTest(mode=mode):
                text = self.service.template(mode)["yaml"]
                result = self.service.validate(text)
                self.assertTrue(result["ok"], (mode, result["errors"]))
        self.assertEqual(self.service.validate(self.service.template("replay")["yaml"])["summary"]["mode"], "replay")
        self.assertEqual(self.service.validate(self.service.template("audit")["yaml"])["summary"]["mode"], "audit")

    def test_the_scenario_import_template_asks_for_a_file(self):
        summary = self.service.validate(self.service.template("scenario-import")["yaml"])["summary"]
        self.assertTrue(summary["needs_import"])

    def test_an_unknown_mode_is_a_plain_400(self):
        for bad in (None, "", "nonsense", "../scenario-start"):
            with self.subTest(bad=bad), self.assertRaises(ApiError) as caught:
                self.service.template(bad)
            self.assertEqual(caught.exception.status, 400)

    def test_missing_templates_are_a_404(self):
        service = self.make(repo_root=self.root / "nowhere")
        with self.assertRaises(ApiError) as caught:
            service.template("audit")
        self.assertEqual(caught.exception.status, 404)

    def test_the_local_backend_is_offered_without_its_ids(self):
        self.add_local_spec()
        text = self.service.template("scenario-start")["yaml"]
        self.assertIn("image: local", text)
        self.assertIn("hf_token_secret: fake-hf-secret", text)
        self.assertIn("hourly_usd: 1.7468", text)
        for secret in ("fakeregistryid0001", "ab" * 32, FAKE_IMAGE, "sha256:"):
            self.assertNotIn(secret, text)
        self.assertTrue(self.service.validate(text)["ok"])

    def test_without_a_local_spec_the_packaged_placeholders_stay(self):
        self.assertIn("REGISTRY_ID", self.service.template("audit")["yaml"])

    def test_a_local_spec_with_placeholders_is_not_a_pinned_image(self):
        self.add_local_spec(LOCAL_SPEC.replace(FAKE_IMAGE, "cr.example.invalid/REGISTRY_ID/x@sha256:IMAGE_DIGEST"))
        self.assertIsNone(self.service.local_backend())
        self.assertNotIn("image: local", self.service.template("audit")["yaml"])

    def test_the_newest_local_spec_wins_and_ids_never_enter_the_template(self):
        older = self.add_local_spec(LOCAL_SPEC.replace("fake-hf-secret", "old-secret"), "old.yaml")
        newer = self.add_local_spec(LOCAL_SPEC.replace("fake-hf-secret", "new-secret"), "new.yaml")
        import os
        os.utime(str(older), (1_000_000, 1_000_000))
        os.utime(str(newer), (2_000_000, 2_000_000))
        text = self.service.template("audit")["yaml"]
        self.assertIn("new-secret", text)
        self.assertNotIn("old-secret", text)

    def test_the_project_and_subnet_ids_of_the_local_spec_are_not_offered(self):
        local = LOCAL_SPEC.replace("project: from-cli-profile", "project: project-fakeproject0001") \
            .replace("  image:", "  subnet: vpcsubnet-fakesubnet0001\n  image:")
        self.add_local_spec(local)
        text = self.service.template("audit")["yaml"]
        self.assertNotIn("fakeproject0001", text)
        self.assertNotIn("fakesubnet0001", text)


class ValidateTests(ServiceCase):
    def test_a_good_spec_has_a_summary(self):
        result = self.service.validate(SCENARIO)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], {
            "name": "demo-start", "mode": "scenario", "suite": "libero_10", "backend": "nebius", "cap_usd": 10.0,
            "max_hours": 5.0, "needs_import": False, "uses_nemotron": True})

    def test_errors_are_paths_and_messages(self):
        cases = [
            (SCENARIO.replace("max_spend_usd: 10.0", "max_spend_usd: -1"), "budget.max_spend_usd"),
            (SCENARIO.replace("max_hours: 5", "max_hours: 99"), "budget.max_hours"),
            (SCENARIO.replace("task: 3", "task: 30"), "scenario.task"),
            (SCENARIO.replace("suite: libero_10", "suite: libero_99"), "policy.suite"),
            (SCENARIO.replace("hourly_usd: 1.8", "hourly_usd: 0"), "backend.hourly_usd"),
            (SCENARIO.replace("name: demo-start", "name: Demo Start"), "name"),
            (SCENARIO + "extra: 1\n", "spec"),
        ]
        for text, path in cases:
            with self.subTest(path=path):
                result = self.service.validate(text)
                self.assertFalse(result["ok"])
                self.assertIsNone(result["summary"])
                self.assertEqual(result["errors"][0]["path"], path)
                self.assertTrue(result["errors"][0]["message"])
                self.assertEqual(sorted(result["errors"][0]), ["message", "path"])

    def test_yaml_syntax_errors_name_the_line(self):
        result = self.service.validate("faultline: 1\nname: [unclosed\nmode: scenario\n")
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["path"], "spec")
        self.assertRegex(result["errors"][0]["message"], r"not valid YAML \(line \d+\)")

    def test_duplicate_keys_and_non_mappings_are_errors(self):
        self.assertFalse(self.service.validate("faultline: 1\nfaultline: 1\n")["ok"])
        self.assertFalse(self.service.validate("- a\n- b\n")["ok"])
        self.assertFalse(self.service.validate("just text")["ok"])

    def test_an_empty_or_oversize_spec_is_a_validation_result_for_validate_and_a_400_for_a_dry_run(self):
        for bad in (None, 5, "", "   \n", "x" * (vs.MAX_YAML_BYTES + 1)):
            with self.subTest(bad=bad if not isinstance(bad, str) else len(bad)):
                result = self.service.validate(bad)
                self.assertEqual((result["ok"], result["errors"][0]["path"]), (False, "yaml"))
                with self.assertRaises(ApiError) as caught:
                    self.service.dry_run(bad)
                self.assertEqual(caught.exception.status, 400)

    def test_the_local_image_resolves_when_a_local_spec_pins_one_and_fails_plainly_when_not(self):
        text = SCENARIO.replace("cr.example.invalid/REGISTRY_ID/faultline-serverless@sha256:IMAGE_DIGEST", "local")
        result = self.service.validate(text)
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["path"], "backend.image")
        self.add_local_spec()
        self.assertTrue(self.service.validate(text)["ok"])

    def test_validation_does_not_need_the_start_file_to_exist(self):
        result = self.service.validate(IMPORTING)
        self.assertTrue(result["ok"], result["errors"])
        self.assertTrue(result["summary"]["needs_import"])


class DryRunTests(ServiceCase):
    def test_a_scenario_dry_run_lists_the_jobs_and_the_worst_case(self):
        plan = self.service.dry_run(SCENARIO)
        self.assertEqual(sorted(plan), ["cap_usd", "jobs", "lines", "max_hours", "plan_hash", "worst_case_total_usd"])
        self.assertEqual([j["name"] for j in plan["jobs"]], ["screen", "reduce", "reduce2", "reduce3", "reduce4"])
        self.assertEqual([j["optional"] for j in plan["jobs"]], [False, False, True, True, True])
        for job in plan["jobs"]:
            self.assertEqual(sorted(job), ["deadline_seconds", "name", "optional", "worst_case_usd"])
            self.assertGreater(job["deadline_seconds"], 0)
            self.assertGreater(job["worst_case_usd"], 0)
        required = sum(j["worst_case_usd"] for j in plan["jobs"] if not j["optional"])
        self.assertAlmostEqual(plan["worst_case_total_usd"], required, delta=0.02)
        self.assertEqual((plan["cap_usd"], plan["max_hours"]), (10.0, 5.0))
        self.assertTrue(plan["lines"][0].startswith("Planned Jobs (nebius backend"))
        self.assertRegex(plan["plan_hash"], r"^[0-9a-f]{64}$")

    def test_the_parsed_jobs_match_the_orchestrators_own_plan(self):
        spec = sp.parse_spec_text(SCENARIO)
        lines, required = orch.dry_run_lines(spec, FakeTools())
        jobs, total = vs.parse_plan(lines, required)
        self.assertEqual(len(jobs), 5, "the dry-run line format changed: update parse_plan")
        self.assertEqual(total, round(required, 2))

    def test_audit_paraphrase_and_replay_dry_runs(self):
        for mode, names in (("audit", ["audit"]), ("paraphrase", ["screen", "reduce"]), ("replay", ["replay"])):
            with self.subTest(mode=mode):
                text = self.service.template(mode)["yaml"]
                plan = self.service.dry_run(text)
                self.assertEqual([j["name"] for j in plan["jobs"]], names)
                self.assertGreater(plan["worst_case_total_usd"], 0)

    def test_a_spec_that_exceeds_its_cap_says_so_in_the_lines(self):
        plan = self.service.dry_run(SCENARIO.replace("max_spend_usd: 10.0", "max_spend_usd: 0.1"))
        self.assertTrue(any(line.startswith("WARNING: that exceeds the cap") for line in plan["lines"]))
        self.assertGreater(plan["worst_case_total_usd"], plan["cap_usd"])

    def test_the_plan_hash_follows_the_spec_not_its_formatting(self):
        base = self.service.dry_run(SCENARIO)["plan_hash"]
        self.assertEqual(self.service.dry_run(SCENARIO)["plan_hash"], base)
        reordered = "# a comment\n" + SCENARIO.replace("policy: {suite: libero_10}", "policy:\n  suite: libero_10")
        self.assertEqual(self.service.dry_run(reordered)["plan_hash"], base)
        for label, changed in (("cap", SCENARIO.replace("max_spend_usd: 10.0", "max_spend_usd: 9.0")),
                               ("task", SCENARIO.replace("task: 3", "task: 4")),
                               ("hours", SCENARIO.replace("max_hours: 5", "max_hours: 4")),
                               ("llm", SCENARIO.replace("hypothesis: true", "hypothesis: false")),
                               ("backend", SCENARIO.replace("hourly_usd: 1.8", "hourly_usd: 1.9")),
                               ("name", SCENARIO.replace("demo-start", "demo-other"))):
            with self.subTest(label):
                self.assertNotEqual(self.service.dry_run(changed)["plan_hash"], base, label)

    def test_the_backend_check_is_shown_but_does_not_change_the_hash(self):
        quiet = self.make(backend_check=lambda spec: None).dry_run(SCENARIO)
        noisy = self.make(backend_check=lambda spec: "Backend check failed: the CLI is missing").dry_run(SCENARIO)
        self.assertEqual(quiet["plan_hash"], noisy["plan_hash"])
        self.assertEqual(noisy["lines"][-1], "Backend check failed: the CLI is missing")
        self.assertNotIn("Backend check failed", "\n".join(quiet["lines"]))

    def test_a_dry_run_makes_no_backend_and_calls_no_cloud(self):
        calls = []
        service = self.make(backend_check=lambda spec: calls.append(spec.name))
        service.dry_run(SCENARIO)
        self.assertEqual(calls, ["demo-start"], "only the injected check ran; nothing built a backend")

    def test_the_local_image_is_resolved_for_the_plan_hash(self):
        text = SCENARIO.replace("cr.example.invalid/REGISTRY_ID/faultline-serverless@sha256:IMAGE_DIGEST", "local")
        self.add_local_spec()
        first = self.service.dry_run(text)["plan_hash"]
        self.add_local_spec(LOCAL_SPEC.replace("ab" * 32, "cd" * 32))
        self.assertNotEqual(self.service.dry_run(text)["plan_hash"], first, "a different pinned image is a different plan")
        self.assertNotIn("fakeregistryid0001", json.dumps(self.service.dry_run(text)))

    def test_a_candidate_budget_the_reduce_job_cannot_hold_is_a_field_error(self):
        with self.assertRaises(ApiError) as caught:
            self.service.dry_run(SCENARIO.replace("max_candidates: 36", "max_candidates: 40"))
        self.assertEqual((caught.exception.status, caught.exception.errors[0]["path"]), (400, "budget.max_candidates"))
        self.assertIn("largest that fits is 36", caught.exception.message)


class ImportTests(ServiceCase):
    def test_a_start_file_is_required_when_the_spec_imports_one(self):
        with self.assertRaises(ApiError) as caught:
            self.service.dry_run(IMPORTING)
        self.assertEqual(caught.exception.errors[0]["path"], "scenario.import")

    def test_a_start_file_makes_a_plan_without_screening_the_imported_start(self):
        plan = self.service.dry_run(IMPORTING, {"name": "my start.json", "content": candidate_text()})
        self.assertEqual([j["name"] for j in plan["jobs"]][:2], ["screen", "reduce"])
        self.assertTrue(any("imported start is validated on this machine" in line for line in plan["lines"]))

    def test_staging_files_are_removed(self):
        self.service.dry_run(IMPORTING, {"name": "start.json", "content": candidate_text()})
        leftovers = [p for p in (self.root / "specs-ui").glob("*")] if (self.root / "specs-ui").exists() else []
        self.assertEqual(leftovers, [])

    def test_the_start_file_is_part_of_the_plan_hash(self):
        one = self.service.dry_run(IMPORTING, {"name": "a.json", "content": candidate_text(index=9)})["plan_hash"]
        same = self.service.dry_run(IMPORTING, {"name": "renamed.json", "content": candidate_text(index=9)})["plan_hash"]
        other = self.service.dry_run(IMPORTING, {"name": "a.json", "content": candidate_text(index=11)})["plan_hash"]
        self.assertEqual(one, same, "the file's name is not part of the plan")
        self.assertNotEqual(one, other)

    def test_a_start_for_another_task_or_a_bad_file_is_refused_with_a_field_error(self):
        for content in (candidate_text(task=5), "not json", "{}"):
            with self.subTest(content=content[:20]), self.assertRaises(ApiError) as caught:
                self.service.dry_run(IMPORTING, {"name": "start.json", "content": content})
            self.assertEqual(caught.exception.status, 400)
            self.assertEqual(caught.exception.errors[0]["path"], "scenario.import")

    def test_a_file_for_a_spec_that_does_not_import_is_refused(self):
        with self.assertRaises(ApiError) as caught:
            self.service.dry_run(SCENARIO, {"name": "start.json", "content": candidate_text()})
        self.assertEqual(caught.exception.errors[0]["path"], "import_file")

    def test_malformed_and_oversize_files_are_refused(self):
        for bad in ("text", {"name": "x"}, {"name": "x", "content": 5}, {"name": "x", "content": ""},
                    {"name": "x", "content": "x" * (vs.MAX_IMPORT_BYTES + 1)}):
            with self.subTest(bad=str(bad)[:30]), self.assertRaises(ApiError) as caught:
                self.service.dry_run(IMPORTING, bad)
            self.assertEqual(caught.exception.errors[0]["path"], "import_file")


class PersistTests(ServiceCase):
    def test_the_spec_is_saved_where_a_terminal_can_run_it(self):
        directory, spec_path = self.service.persist(self.service.prepare(SCENARIO))
        self.assertEqual(directory.parent, self.root / "specs-ui")
        self.assertEqual(directory.name, "20261017T010203Z-demo-start")
        self.assertEqual(sp.load_spec(spec_path).name, "demo-start")
        self.assertEqual(sp.load_spec(spec_path).raw, sp.parse_spec_text(SCENARIO).raw)

    def test_the_start_file_is_saved_beside_it_and_the_saved_spec_names_it(self):
        prepared = self.service.prepare(IMPORTING, {"name": "start.json", "content": candidate_text()})
        directory, spec_path = self.service.persist(prepared)
        saved = sp.load_spec(spec_path)
        self.assertEqual(Path(saved.scenario.import_path), (directory / "import.json").resolve())
        self.assertEqual((directory / "import.json").read_text(encoding="utf-8"), candidate_text())
        self.assertEqual(orch.check_import(saved, FakeTools())["candidate"]["task_id"], 0)

    def test_the_local_image_is_resolved_in_the_saved_spec_only(self):
        self.add_local_spec()
        text = SCENARIO.replace("cr.example.invalid/REGISTRY_ID/faultline-serverless@sha256:IMAGE_DIGEST", "local")
        _directory, spec_path = self.service.persist(self.service.prepare(text))
        self.assertEqual(sp.load_spec(spec_path).backend.image, FAKE_IMAGE)

    def test_two_saves_in_the_same_second_get_different_folders(self):
        first, _ = self.service.persist(self.service.prepare(SCENARIO))
        second, _ = self.service.persist(self.service.prepare(SCENARIO))
        self.assertNotEqual(first, second)
        self.assertTrue(second.name.endswith("-2"))

    def test_the_folder_name_is_a_safe_slug(self):
        directory, _ = self.service.persist(self.service.prepare(SCENARIO))
        self.assertRegex(directory.name, r"^\d{8}T\d{6}Z-[a-z0-9-]+(-\d+)?$")


if __name__ == "__main__":
    unittest.main()
