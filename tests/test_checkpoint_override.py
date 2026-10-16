"""The optional policy checkpoint override: ``policy.checkpoint`` of a spec down to the Job's model server."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from robot_debug import checkpoint_override as co
from robot_debug import job_entry
from robot_debug import job_runtime as jr
from robot_debug import spec as sp
from robot_debug import workloads
from robot_debug.job_entry import ImageLayout, model_server_argv, prefetch_command

ID = "acme-lab/gr00t17-finetune_goal-v2"
REV = "0123456789abcdef0123456789abcdef01234567"
OTHER = "f" * 40
ROOT = Path(__file__).resolve().parents[1]
BACKEND = {"kind": "nebius", "image": "cr.example.invalid/REGISTRY_ID/faultline@sha256:IMAGE_DIGEST",
           "hf_token_secret": "faultline-hf-token", "hourly_usd": 1.8}


def spec_data(mode="scenario", checkpoint=None, **extra):
    policy = {"suite": "libero_10"}
    if checkpoint is not None:
        policy["checkpoint"] = checkpoint
    data = {"faultline": 1, "name": "ck-test", "mode": mode, "policy": policy,
            "budget": {"max_spend_usd": 5.0, "max_hours": 2}, "backend": dict(BACKEND)}
    if mode == "scenario":
        data["scenario"] = {"task": 3, "start": 0}
    elif mode == "audit":
        data["audit"] = {"task": 0, "start": 0, "families": ["blur"]}
    data.update(extra)
    return data


class PairValidation(unittest.TestCase):
    def test_good_ids_and_revisions(self):
        for good in (ID, "nvidia/gr00t17-lerobot-libero_10-640", "A1/b.c_d-e"):
            self.assertEqual((good, REV), co.validate_pair(good, REV))

    def test_bad_ids_are_refused(self):
        for bad in ("gr00t", "/name", "org/", "org/name/extra", "org/na me", "org/na;me", "../x/y", "org/..", "-org/name",
                    "org/-name", "a" * 97 + "/b", "", None, 5, ["a/b"]):
            with self.subTest(bad=bad), self.assertRaises(co.CheckpointOverrideError):
                co.validate_pair(bad, REV)

    def test_the_separately_pinned_models_cannot_be_replaced(self):
        for reserved in co.RESERVED_IDS:
            with self.subTest(reserved=reserved), self.assertRaises(co.CheckpointOverrideError):
                co.validate_pair(reserved, REV)

    def test_the_revision_must_be_a_full_lowercase_commit(self):
        for bad in ("main", REV[:39], REV + "0", REV.upper(), "g" * 40, "", None, 12):
            with self.subTest(bad=bad), self.assertRaises(co.CheckpointOverrideError):
                co.validate_pair(ID, bad)

    def test_from_config_wants_both_fields_or_neither(self):
        self.assertIsNone(co.from_config({"mode": "x"}))
        self.assertEqual((ID, REV), co.from_config({"checkpoint_id": ID, "checkpoint_revision": REV}))
        with self.assertRaises(co.CheckpointOverrideError):
            co.from_config({"checkpoint_id": ID})
        with self.assertRaises(co.CheckpointOverrideError):
            co.from_config({"checkpoint_revision": REV})

    def test_as_fields(self):
        self.assertEqual({}, co.as_fields(None))
        self.assertEqual({"checkpoint_id": ID, "checkpoint_revision": REV}, co.as_fields((ID, REV)))

    def test_the_module_is_job_safe(self):
        import ast

        path = ROOT / "src" / "robot_debug" / "checkpoint_override.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 8))
        loaded = {node.module if isinstance(node, ast.ImportFrom) else alias.name
                  for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
                  for alias in (getattr(node, "names", None) or [None])}
        self.assertEqual({"__future__", "re", "typing"}, loaded)


class SpecSection(unittest.TestCase):
    def test_no_checkpoint_by_default(self):
        self.assertIsNone(sp.parse_spec(spec_data()).checkpoint)

    def test_a_checkpoint_is_parsed_in_every_mode(self):
        for mode in ("scenario", "audit"):
            with self.subTest(mode=mode):
                spec = sp.parse_spec(spec_data(mode, {"id": ID, "revision": REV}))
                self.assertEqual((ID, REV), spec.checkpoint.pair)
                self.assertEqual({"id": ID, "revision": REV}, spec.raw["policy"]["checkpoint"])

    def test_a_replay_spec_may_name_only_a_checkpoint(self):
        data = spec_data("replay")
        data["policy"] = {"checkpoint": {"id": ID, "revision": REV}}
        spec = sp.parse_spec(data)
        self.assertEqual((None, (ID, REV)), (spec.suite, spec.checkpoint.pair))
        data["policy"] = {"suite": "libero_10", "checkpoint": {"id": ID, "revision": REV}}
        self.assertEqual("libero_10", sp.parse_spec(data).suite)

    def test_other_modes_still_need_the_suite(self):
        data = spec_data()
        data["policy"] = {"checkpoint": {"id": ID, "revision": REV}}
        with self.assertRaises(sp.SpecError) as caught:
            sp.parse_spec(data)
        self.assertIn("suite", str(caught.exception))

    def test_a_revision_is_required_with_an_id(self):
        with self.assertRaises(sp.SpecError) as caught:
            sp.parse_spec(spec_data(checkpoint={"id": ID}))
        self.assertIn("policy.checkpoint.revision", str(caught.exception))
        self.assertIn("required when id is given", str(caught.exception))

    def test_an_id_is_required_with_a_revision(self):
        with self.assertRaises(sp.SpecError) as caught:
            sp.parse_spec(spec_data(checkpoint={"revision": REV}))
        self.assertIn("id", str(caught.exception))

    def test_bad_values_name_their_path(self):
        cases = ((dict(id="not-an-id", revision=REV), "policy.checkpoint.id"),
                 (dict(id=ID, revision="main"), "policy.checkpoint.revision"),
                 (dict(id=ID, revision=REV.upper()), "policy.checkpoint.revision"),
                 (dict(id="nvidia/GR00T-N1.7-3B", revision=REV), "policy.checkpoint.id"),
                 (dict(id=ID, revision=REV, extra=1), "policy.checkpoint"),
                 ("nvidia/x", "policy.checkpoint"), ({}, "policy.checkpoint"))
        for value, path in cases:
            with self.subTest(value=value), self.assertRaises(sp.SpecError) as caught:
                sp.parse_spec(spec_data(checkpoint=value))
            self.assertIn(path, str(caught.exception))


class WorkloadValidation(unittest.TestCase):
    def screen(self, **extra):
        return dict({"schema_version": 1, "mode": "scenario-screen", "run_id": "r1", "deadline_seconds": 1500,
                     "suite": "libero_10", "task_ids": [3], "start_indices": [0, 1]}, **extra)

    def test_the_fields_are_accepted_and_returned_for_the_modes_that_run_the_model(self):
        accepted = jr.validate_workload_config(self.screen(checkpoint_id=ID, checkpoint_revision=REV))
        self.assertEqual((ID, REV), (accepted["checkpoint_id"], accepted["checkpoint_revision"]))
        m6 = {"schema_version": 1, "mode": "m6-threshold", "run_id": "r2", "deadline_seconds": 2000,
              "families": ["blur"], "sweep": [0.5, 1.0], "attempts": 2, "required_failures": 2,
              "bisection_steps": 1, "suite": "libero_object", "task_id": 0, "init_state_index": 0}
        self.assertNotIn("checkpoint_id", jr.validate_workload_config(m6))
        accepted = jr.validate_workload_config(dict(m6, checkpoint_id=ID, checkpoint_revision=REV))
        self.assertEqual((ID, REV), (accepted["checkpoint_id"], accepted["checkpoint_revision"]))

    def test_without_the_fields_the_validated_workload_is_unchanged(self):
        accepted = jr.validate_workload_config(self.screen())
        self.assertNotIn("checkpoint_id", accepted)
        self.assertNotIn("checkpoint_revision", accepted)

    def test_half_or_malformed_overrides_are_rejected(self):
        for extra in ({"checkpoint_id": ID}, {"checkpoint_revision": REV},
                      {"checkpoint_id": ID, "checkpoint_revision": "main"},
                      {"checkpoint_id": "x", "checkpoint_revision": REV},
                      {"checkpoint_id": "nvidia/Cosmos-Reason2-2B", "checkpoint_revision": REV}):
            with self.subTest(extra=extra), self.assertRaises(jr.JobRuntimeError):
                jr.validate_workload_config(self.screen(**extra))

    def test_modes_that_never_take_one_still_reject_the_keys(self):
        pilot = {"schema_version": 1, "mode": "pilot", "run_id": "r3", "deadline_seconds": 2400}
        with self.assertRaises(jr.JobRuntimeError):
            jr.validate_workload_config(dict(pilot, checkpoint_id=ID, checkpoint_revision=REV))

    def test_paraphrase_workloads_accept_them(self):
        from robot_debug import language_experiment as le

        workload = le.build_screen_workload(run_id="r4", suite="libero_object", task_id=0, start=0,
                                            original="pick up the alphabet soup and place it in the basket",
                                            paraphrases=["grab the alphabet soup and put it in the basket"])
        accepted = jr.validate_workload_config(dict(workload, checkpoint_id=ID, checkpoint_revision=REV))
        self.assertEqual(ID, accepted["checkpoint_id"])


class ModelServerArguments(unittest.TestCase):
    def test_the_default_argv_is_unchanged(self):
        layout = ImageLayout()
        self.assertEqual(model_server_argv(layout, server="faultline", max_batch_size=12, suite="libero_10"),
                         model_server_argv(layout, server="faultline", max_batch_size=12, suite="libero_10",
                                           checkpoint=None))

    def test_an_override_changes_only_the_checkpoint_flag(self):
        layout = ImageLayout()
        base = model_server_argv(layout, server="faultline", max_batch_size=12, suite="libero_10")
        other = model_server_argv(layout, server="faultline", max_batch_size=12, suite="libero_10",
                                  checkpoint=(ID, REV))
        self.assertIn("--args.checkpoint=nvidia/gr00t17-lerobot-libero_10-640", base)
        self.assertEqual([item for item in base if not item.startswith("--args.checkpoint=")],
                         [item for item in other if not item.startswith("--args.checkpoint=")])
        self.assertIn("--args.checkpoint=" + ID, other)

    def test_scripts_get_the_same_flags(self):
        flags = job_entry.model_flags_for_scripts(ImageLayout(), 12, "libero_10", (ID, REV))
        self.assertIn("--args.checkpoint=" + ID, flags)

    def test_a_malformed_override_is_refused(self):
        with self.assertRaises(ValueError):
            model_server_argv(ImageLayout(), checkpoint=("bad", REV))

    def test_the_prefetch_command_names_the_checkpoint_only_with_an_override(self):
        layout = ImageLayout()
        out = Path("/tmp/out.json")
        plain = prefetch_command(layout, out, suite="libero_10")
        self.assertNotIn("--checkpoint-id", plain)
        over = prefetch_command(layout, out, suite="libero_10", checkpoint=(ID, REV))
        self.assertEqual(plain + ["--checkpoint-id", ID, "--checkpoint-revision", REV], over)

    def test_the_factory_serves_the_override_and_prefetches_it(self):
        import sys
        import time
        from unittest import mock

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("project", "upstream", "work", "hf", "export"):
                (root / name).mkdir()
            layout = ImageLayout(project_root=root / "project", upstream_root=root / "upstream",
                                 simulator_source=root / "src", model_python=Path(sys.executable),
                                 evaluator=root / "vla-eval", work_root=root / "work", hf_home=root / "hf",
                                 export_root=root / "export")
            factory = job_entry.ProductionModelFactory(
                layout, base_env={}, deadline=time.monotonic() + 2400, suite="libero_10", checkpoint=(ID, REV))
            with mock.patch.object(job_entry, "prefetch_models",
                                   return_value={"repositories": {}}) as prefetch, \
                    mock.patch.object(job_entry, "write_provenance"):
                model = factory(log_root=root / "work" / "run" / "logs", server="faultline", max_batch_size=4)
            self.assertIn("--args.checkpoint=" + ID, model._argv)
            self.assertEqual((ID, REV), tuple(prefetch.call_args.kwargs["checkpoint"]))
            self.assertEqual("libero_10", prefetch.call_args.kwargs["suite"])

    def test_the_default_factory_prefetches_without_a_checkpoint_argument(self):
        import sys
        import time
        from unittest import mock

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("project", "upstream", "work", "hf", "export"):
                (root / name).mkdir()
            layout = ImageLayout(project_root=root / "project", upstream_root=root / "upstream",
                                 simulator_source=root / "src", model_python=Path(sys.executable),
                                 evaluator=root / "vla-eval", work_root=root / "work", hf_home=root / "hf",
                                 export_root=root / "export")
            factory = job_entry.ProductionModelFactory(
                layout, base_env={}, deadline=time.monotonic() + 2400, suite="libero_10")
            with mock.patch.object(job_entry, "prefetch_models", return_value={"repositories": {}}) as prefetch, \
                    mock.patch.object(job_entry, "write_provenance"):
                factory(log_root=root / "work" / "run" / "logs", server="faultline", max_batch_size=4)
            self.assertNotIn("checkpoint", prefetch.call_args.kwargs)


class SummaryRecord(unittest.TestCase):
    def test_the_summary_names_the_override_and_its_resolved_commit(self):
        from robot_debug import scenario_experiment as se

        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            (run_root / "model-resolution.json").write_text(json.dumps(
                {"schema_version": 1, "repositories": {ID: {"revision": REV, "pinned": True}}}), encoding="utf-8")
            self.assertEqual({"id": ID, "revision": REV, "pinned": True},
                             se.checkpoint_record("libero_10", run_root, ID))
            default = se.checkpoint_record("libero_10", run_root)
            self.assertEqual(("nvidia/gr00t17-lerobot-libero_10-640", None), (default["id"], default["revision"]))


class AuditWorkload(unittest.TestCase):
    def test_audit_workload_carries_the_spec_checkpoint(self):
        plain = workloads.audit_workload(sp.parse_spec(spec_data("audit")).raw, "run-a")
        self.assertNotIn("checkpoint_id", plain)
        over = workloads.audit_workload(sp.parse_spec(spec_data("audit", {"id": ID, "revision": REV})).raw, "run-a")
        self.assertEqual((ID, REV), (over["checkpoint_id"], over["checkpoint_revision"]))
        stripped = {key: value for key, value in over.items() if not key.startswith("checkpoint_")}
        self.assertEqual(plain, stripped, "nothing else changes")

    def test_a_malformed_spec_checkpoint_is_a_workload_error(self):
        raw = copy.deepcopy(dict(sp.parse_spec(spec_data("audit")).raw))
        raw["policy"]["checkpoint"] = {"id": "bad", "revision": REV}
        with self.assertRaises(workloads.WorkloadError):
            workloads.audit_workload(raw, "run-a")


class ScenarioRun(unittest.TestCase):
    def run_scenario(self, checkpoint):
        from tests.test_orchestrator import full_script, make_world, spec_for

        policy = {"suite": "libero_10"}
        if checkpoint is not None:
            policy["checkpoint"] = checkpoint
        temp, runner, backend, *_ = make_world(spec_for(policy=policy), full_script())
        self.addCleanup(temp.cleanup)
        result = runner.diagnose()
        self.assertEqual("completed", result.status)
        return runner, backend

    def test_every_job_of_the_run_serves_the_override(self):
        runner, backend = self.run_scenario({"id": ID, "revision": REV})
        self.assertEqual(3, len(backend.submitted), "screen, reduce, one continuation")
        for name in backend.submitted:
            workload = backend.workloads[name]
            self.assertEqual((ID, REV), (workload["checkpoint_id"], workload["checkpoint_revision"]), name)
            jr.validate_workload_config(workload)

    def test_without_an_override_no_workload_mentions_a_checkpoint(self):
        runner, backend = self.run_scenario(None)
        for name in backend.submitted:
            self.assertFalse([key for key in backend.workloads[name] if key.startswith("checkpoint")], name)

    def test_the_override_adds_exactly_two_fields_to_each_workload(self):
        _r1, plain = self.run_scenario(None)
        _r2, over = self.run_scenario({"id": ID, "revision": REV})
        for left, right in zip(plain.submitted, over.submitted):
            kept = {key: value for key, value in over.workloads[right].items() if not key.startswith("checkpoint_")}
            self.assertEqual(dict(plain.workloads[left], run_id=right), kept)


class ParaphraseRun(unittest.TestCase):
    def test_both_jobs_carry_the_override_and_a_plain_run_carries_none(self):
        from tests.test_orchestrator import make_world
        from tests.test_paraphrase_pipeline import (
            ParaphraseTools, paraphrase_spec, reduce_step, screen_step)

        for checkpoint in (None, {"id": ID, "revision": REV}):
            with self.subTest(checkpoint=checkpoint):
                raw = dict(paraphrase_spec().raw)
                if checkpoint is not None:
                    raw["policy"] = {"suite": "libero_object", "checkpoint": checkpoint}
                temp, runner, backend, *_ = make_world(sp.parse_spec(raw), [screen_step(), reduce_step()],
                                                       tools=ParaphraseTools())
                self.addCleanup(temp.cleanup)
                self.assertEqual("completed", runner.diagnose().status)
                self.assertEqual(2, len(backend.submitted))
                for name in backend.submitted:
                    workload = backend.workloads[name]
                    if checkpoint is None:
                        self.assertNotIn("checkpoint_id", workload)
                    else:
                        self.assertEqual((ID, REV), (workload["checkpoint_id"], workload["checkpoint_revision"]))
                        jr.validate_workload_config(workload)


class AuditRun(unittest.TestCase):
    def test_the_audit_case_names_the_checkpoint_only_with_an_override(self):
        from tests.test_orchestrator import Mode2AndReplay, finished, make_world, spec_for

        for checkpoint in (None, {"id": ID, "revision": REV}):
            with self.subTest(checkpoint=checkpoint):
                policy = {"suite": "libero_10"}
                if checkpoint is not None:
                    policy["checkpoint"] = checkpoint
                summary = {"mode": "m6-threshold", "complete": True, "stop_reason": None, "families": {}}
                temp, runner, backend, *_ = make_world(
                    spec_for(mode="audit", policy=policy), [finished(lambda w: summary, name="m6_summary.json")],
                    tools=Mode2AndReplay.AuditTools())
                self.addCleanup(temp.cleanup)
                self.assertEqual("completed", runner.diagnose().status)
                case = json.loads((runner.run_dir / "case.json").read_text())
                if checkpoint is None:
                    self.assertNotIn("checkpoint", case)
                else:
                    self.assertEqual({"id": ID, "revision": REV, "pinned": True}, case["checkpoint"])


class ReplayRun(unittest.TestCase):
    def replay(self, spec_policy, case_checkpoint=None):
        from tests.test_orchestrator import FakeTools, finished, make_world, spec_for

        recorded = {}

        class Tools(FakeTools):
            def replay_workload(self, case, run_id, attempts, inputs=None):
                recorded["inputs"] = dict(inputs or {})
                return {"schema_version": 1, "mode": "scenario-replay", "run_id": run_id, "deadline_seconds": 1000}

            def replay_inputs(self, case_dir, case):
                return {"layout": {"fake": True}, "reference_candidate": None}

        case = {"kind": "scenario_reduction", "case_id": "ab" * 32, "suite": "libero_10",
                "replay": {"candidate": {"x": 1}}}
        if case_checkpoint is not None:
            case["checkpoint"] = case_checkpoint
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        (Path(directory.name) / "case.json").write_text(json.dumps(case), encoding="utf-8")
        data = dict(spec_for(mode="replay").raw)
        if spec_policy is not None:
            data["policy"] = spec_policy
        script = [finished(lambda w: {"verdict": "still_reproduces", "complete": True,
                                      "checkpoint": {"id": "seen-by-the-job"}})]
        temp, runner, backend, tools, ledger, lines = make_world(sp.parse_spec(data), script, tools=Tools())
        self.addCleanup(temp.cleanup)
        result = runner.replay(Path(directory.name))
        self.assertEqual("completed", result.status)
        return recorded["inputs"], runner, lines

    def test_a_replay_spec_can_test_a_case_against_a_changed_policy(self):
        inputs, runner, lines = self.replay({"checkpoint": {"id": ID, "revision": REV}})
        self.assertEqual((ID, REV), tuple(inputs["checkpoint"]))
        saved = json.loads((runner.run_dir / "replay-result.json").read_text())
        self.assertEqual({"id": "seen-by-the-job"}, saved["checkpoint"], "the result names what the Job served")
        self.assertTrue(any("using the spec's checkpoint" in line for line in lines))

    def test_without_an_override_a_default_case_replays_on_the_suite_checkpoint(self):
        default = {"id": "nvidia/gr00t17-lerobot-libero_10-640", "revision": "5" * 40, "pinned": True}
        for case_checkpoint in (None, default):
            with self.subTest(case_checkpoint=case_checkpoint):
                inputs, runner, _lines = self.replay(None, case_checkpoint)
                self.assertNotIn("checkpoint", inputs)
                saved = json.loads((runner.run_dir / "replay-result.json").read_text())
                self.assertNotIn("checkpoint", saved)

    def test_a_case_found_with_an_override_replays_on_it_unless_the_spec_says_otherwise(self):
        found = {"id": ID, "revision": REV, "pinned": True}
        inputs, _runner, lines = self.replay(None, found)
        self.assertEqual((ID, REV), tuple(inputs["checkpoint"]))
        self.assertTrue(any("the case was found with checkpoint" in line for line in lines))
        inputs, _runner, _lines = self.replay({"checkpoint": {"id": ID, "revision": OTHER}}, found)
        self.assertEqual((ID, OTHER), tuple(inputs["checkpoint"]), "the spec wins")

    def test_a_case_without_a_recorded_revision_is_not_guessed(self):
        inputs, _runner, _lines = self.replay(None, {"id": ID, "revision": None, "pinned": None})
        self.assertNotIn("checkpoint", inputs)


class ReplayWorkloadBuilder(unittest.TestCase):
    def test_the_real_builder_adds_the_checkpoint_and_nothing_else(self):
        from tests.test_workloads import case_record, reduce_workload

        case = case_record()
        inputs = workloads.reference_inputs(reduce_workload(), case)
        plain = workloads.replay_workload(case, "diag-replay-1", **inputs)
        over = workloads.replay_workload(case, "diag-replay-1", checkpoint=(ID, REV), **inputs)
        self.assertEqual((ID, REV), (over["checkpoint_id"], over["checkpoint_revision"]))
        self.assertEqual(plain, {key: value for key, value in over.items() if not key.startswith("checkpoint_")})
        self.assertFalse([key for key in plain if key.startswith("checkpoint")])
        jr.validate_workload_config(over)

    def test_a_bad_checkpoint_is_refused(self):
        from tests.test_workloads import case_record, reduce_workload

        case = case_record()
        inputs = workloads.reference_inputs(reduce_workload(), case)
        with self.assertRaises(workloads.WorkloadError):
            workloads.replay_workload(case, "a", checkpoint=("bad", REV), **inputs)


class PrefetchOverride(unittest.TestCase):
    def fetch(self, *extra):
        import io
        from contextlib import redirect_stderr
        from scripts import serverless_prefetch as pf
        from tests.test_job_entry import _FakeHub

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hub = _FakeHub(root / "hub", {})
            output = root / "resolution.json"
            with redirect_stderr(io.StringIO()):
                code = pf.main(["--output", str(output), "--suite", "libero_10", *extra], hub=hub)
            repositories = json.loads(output.read_text(encoding="utf-8"))["repositories"]
            offline = {repo: Path(hub.snapshot_download(repo_id=repo, local_files_only=True)).name
                       for repo in repositories}
            return code, repositories, offline

    def test_the_override_replaces_only_the_suite_checkpoint(self):
        code, repositories, offline = self.fetch("--checkpoint-id", ID, "--checkpoint-revision", REV)
        self.assertEqual(0, code)
        self.assertEqual({ID, "nvidia/GR00T-N1.7-3B", "nvidia/Cosmos-Reason2-2B"}, set(repositories))
        self.assertEqual({"revision": REV, "pinned": True}, repositories[ID])
        self.assertEqual(REV, offline[ID], "the private cache's main points at the requested commit")
        self.assertEqual("2fc962b973bccdd5d8ce4f67cc63b264d6886495", repositories["nvidia/GR00T-N1.7-3B"]["revision"])
        self.assertEqual("9ce19a195e423419c349abfc86fd07178b230561", repositories["nvidia/Cosmos-Reason2-2B"]["revision"])

    def test_without_the_override_the_suite_checkpoint_is_fetched(self):
        _code, repositories, _offline = self.fetch()
        self.assertIn("nvidia/gr00t17-lerobot-libero_10-640", repositories)

    def test_half_or_malformed_overrides_exit_with_a_usage_error(self):
        for args in (("--checkpoint-id", ID), ("--checkpoint-revision", REV),
                     ("--checkpoint-id", ID, "--checkpoint-revision", "main"),
                     ("--checkpoint-id", "nope", "--checkpoint-revision", REV),
                     ("--checkpoint-id", "nvidia/GR00T-N1.7-3B", "--checkpoint-revision", REV),
                     ("--checkpoint-id", "nvidia/Cosmos-Reason2-2B", "--checkpoint-revision", REV)):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                self.fetch(*args)

    def test_the_command_names_the_override_the_script_understands(self):
        argv = prefetch_command(ImageLayout(), Path("/tmp/out.json"), suite="libero_10", checkpoint=(ID, REV))
        self.assertEqual(["--checkpoint-id", ID, "--checkpoint-revision", REV], argv[-4:])


if __name__ == "__main__":
    unittest.main()
