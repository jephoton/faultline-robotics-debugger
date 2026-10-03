"""Offline M4 import contract tests."""
import json
import tempfile
import unittest
from pathlib import Path

from robot_debug.case_io import SanitizedCaseValidationError, import_m4


PARENT = {"x": .5, "y": 0, "width": .5, "height": .5}
FINAL = {"x": .5, "y": 0, "width": .5, "height": .375}


def fixture(root: Path, *, linked=True):
    session = root / "failure-reduction"
    session.mkdir()
    stages = []
    def add(name, rect, outcome):
        stage = {"stage": name, "rectangle": rect, "results": [{"outcome": outcome, "episode_index": 0}], "status": "completed", "physical_episode_count": 1}
        stages.append(stage)
        run = session / "runs" / name
        run.mkdir(parents=True)
        mask = {"enabled": False} if rect is None else {"enabled": True, **rect, "color": [0, 0, 0], "opacity": 1.0}
        raw = {"task_id": 0, "episode_idx": 0, "metrics": {"success": outcome == "success"}, "steps": 4, "elapsed_sec": 1.25, "name": "safe task"}
        agg = {"benchmark": "libero", "config": {"benchmark": "robot_debug.libero:DiagnosticLIBEROBenchmark", "params": {"suite": "libero_object", "task_id": 0, "seed": 7, "env_seed": 7, "agentview_occlusion": mask}}, "tasks": [{"episodes": [raw]}]}
        if linked: agg["server_info"] = {"model_identity": "opaque-model"}
        (run / "run_aggregate.json").write_text(json.dumps(agg), encoding="utf-8")
    add("nominal-sentinel", None, "success")
    for i in range(4): add(f"parent-attempt-{i+1:02d}", PARENT, "policy_failure")
    for i in range(4): add(f"delta-0125-bottom-attempt-{i+1:02d}", FINAL, "policy_failure")
    for i in range(5): add(f"nominal-control-attempt-{i+1:02d}", None, "success")
    summary = {"schema_version": 1, "model_identity": "opaque-model", "repository_revision": "revision", "planned": {"model_identity": "opaque-model"}, "completed": {"stages": stages, "sentinel_outcome": "success", "control_outcomes": ["success"] * 5, "decisions": [{"label": "parent", "decision": "pass", "rectangle": PARENT, "outcomes": ["policy_failure"] * 4}, {"label": "candidate", "decision": "pass", "rectangle": FINAL, "outcomes": ["policy_failure"] * 4}]}, "geometry": {"parent": PARENT, "current": FINAL, "final": FINAL}, "certified_rectangle": FINAL, "lineage": [{"edge": "bottom", "delta": .125, "rectangle": FINAL}], "stop_reason": "reduced_failure_with_nominal_controls", "elapsed_seconds": 42.0, "physical_episode_count": 14, "valid_episode_count": 14}
    replay = {"schema_version": 1, "task_id": 0, "episode_index": 0, "seed": 7, "expected_outcome": "policy_failure", "acceptance_rule": {"failures": 4, "attempts": 5}, "rectangle": FINAL, "model_identity": "opaque-model", "repository_revision": "revision", "replay_command": "private --token secret"}
    (session / "session_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (session / "replay_case.json").write_text(json.dumps(replay), encoding="utf-8")
    return session, summary, replay


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.session, self.summary, self.replay = fixture(self.root)

    def tearDown(self): self.tmp.cleanup()

    def test_complete_evidence_is_historical_but_fresh_replay_unverified(self):
        case = import_m4(self.root)
        self.assertEqual(case["task"]["task_id"], 0)
        self.assertEqual(case["capabilities"]["historical_failure"]["status"], "confirmed")
        self.assertEqual(case["capabilities"]["exercised_replay"]["status"], "unverified")
        self.assertEqual(case["capabilities"]["replay_recipe"]["status"], "incomplete")
        self.assertEqual(len(case["evidence"]["episodes"]), 14)
        self.assertNotIn("secret", json.dumps(case))
        self.assertNotIn("replay_command", json.dumps(case))

    def test_unlinked_policy_never_confirms_history(self):
        for p in self.session.glob("runs/*/*_aggregate.json"):
            data = json.loads(p.read_text()); data.pop("server_info", None); p.write_text(json.dumps(data))
        case = import_m4(self.root)
        self.assertEqual(case["capabilities"]["historical_failure"]["status"], "not-established")

    def test_summary_raw_contradiction_is_conflicting(self):
        p = next(self.session.glob("runs/parent*/*_aggregate.json"))
        data = json.loads(p.read_text()); data["tasks"][0]["episodes"][0]["metrics"]["success"] = True; p.write_text(json.dumps(data))
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "conflicting")

    def test_missing_aggregate_is_insufficient(self):
        next(self.session.glob("runs/parent*/*_aggregate.json")).unlink()
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "not-established")

    def test_missing_control_aggregate_is_insufficient(self):
        next(self.session.glob("runs/nominal-control*/*_aggregate.json")).unlink()
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "not-established")

    def test_escape_is_rejected_without_leaking_path(self):
        with self.assertRaises(SanitizedCaseValidationError) as caught:
            import_m4(self.root, summary="../private.json")
        self.assertNotIn(str(self.root), str(caught.exception))

    def test_duplicate_aggregate_conflicts(self):
        p = next(self.session.glob("runs/parent*/*_aggregate.json"))
        p.with_name("second_aggregate.json").write_bytes(p.read_bytes())
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "conflicting")

    def test_wrong_mask_conflicts(self):
        p = next(self.session.glob("runs/parent*/*_aggregate.json"))
        data = json.loads(p.read_text()); data["config"]["params"]["agentview_occlusion"]["opacity"] = .5; p.write_text(json.dumps(data))
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "conflicting")

    def test_nonfinite_and_duplicate_keys_rejected(self):
        p = self.session / "replay_case.json"
        p.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaises(SanitizedCaseValidationError): import_m4(self.root)

    def test_bool_version_and_numeric_string_rectangle_are_rejected(self):
        p = self.session / "replay_case.json"
        data = json.loads(p.read_text()); data["schema_version"] = True; p.write_text(json.dumps(data))
        with self.assertRaises(SanitizedCaseValidationError): import_m4(self.root)
        data["schema_version"] = 1; data["rectangle"]["x"] = "0.5"; p.write_text(json.dumps(data))
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "conflicting")
        p.write_text('{"schema_version":1,"seed":NaN}')
        with self.assertRaises(SanitizedCaseValidationError): import_m4(self.root)

    def test_profile_pins_complete_recipe_but_fresh_replay_stays_unverified(self):
        proof = self.session / "proof.txt"; proof.write_text("source evidence")
        import hashlib
        ref = {"path": "failure-reduction/proof.txt", "sha256": hashlib.sha256(proof.read_bytes()).hexdigest()}
        data = {"schema_version": 1, "policy": {"model_id": "opaque-model", "checkpoint_revision": "checkpoint"}, "runtime": {"project_revision": "revision", "upstream_harness_revision": "upstream", "simulator_image_digest": "sha256:" + "a" * 64}, "provenance": {key: ref for key in ("policy.model_id", "policy.checkpoint_revision", "runtime.project_revision", "runtime.upstream_harness_revision", "runtime.simulator_image_digest")}}
        (self.session / "profile.json").write_text(json.dumps(data))
        case = import_m4(self.root, profile="failure-reduction/profile.json")
        self.assertEqual(case["capabilities"]["replay_recipe"]["status"], "complete")
        self.assertEqual(case["capabilities"]["exercised_replay"]["status"], "unverified")

    def test_raw_instruction_is_not_copied_to_public_metadata(self):
        p = next(self.session.glob("runs/parent*/*_aggregate.json"))
        data = json.loads(p.read_text()); data["tasks"][0]["episodes"][0]["name"] = "private endpoint token-do-not-copy"; p.write_text(json.dumps(data))
        self.assertNotIn("token-do-not-copy", json.dumps(import_m4(self.root)))

    def test_media_is_referenced_and_counted_without_copying_bytes(self):
        run = next(self.session.glob("runs/parent*"))
        (run / "task0000_ep0000_clip.mp4").write_bytes(b"video")
        case = import_m4(self.root)
        self.assertEqual(case["evidence"]["media_counts"]["videos"], 1)
        self.assertTrue(any("video" in item for item in case["evidence"]["episodes"]))

    def test_source_identity_is_kept_without_inventing_checkpoint(self):
        case = import_m4(self.root)
        self.assertEqual(case["policy"]["model_id"], "opaque-model")
        self.assertIsNone(case["policy"]["checkpoint_revision"])
        self.assertEqual(case["runtime"]["project_revision"], "revision")
        self.assertEqual(len(case["evidence"]["episodes"][0]["episode_id"]), 16)

    def test_task_reset_and_gray_fill_derive_from_source(self):
        for p in self.session.glob("runs/*/*_aggregate.json"):
            data = json.loads(p.read_text()); data["config"]["params"]["task_id"] = 2
            raw = data["tasks"][0]["episodes"][0]; raw["task_id"] = 2; raw["episode_idx"] = 3
            mask = data["config"]["params"]["agentview_occlusion"]
            if mask["enabled"]: mask["color"] = [17, 17, 17]
            p.write_text(json.dumps(data))
        summary = json.loads((self.session / "session_summary.json").read_text())
        for stage in summary["completed"]["stages"]: stage["results"][0]["episode_index"] = 3
        (self.session / "session_summary.json").write_text(json.dumps(summary))
        replay = json.loads((self.session / "replay_case.json").read_text()); replay["task_id"] = 2; replay["episode_index"] = 3
        (self.session / "replay_case.json").write_text(json.dumps(replay))
        case = import_m4(self.root)
        self.assertEqual((case["task"]["task_id"], case["task"]["reset_index"], case["perturbation"]["fill_value"]), (2, 3, 17))
        self.assertEqual(case["capabilities"]["historical_failure"]["status"], "confirmed")

    def test_timeout_keeps_raw_category_separate_from_gate_policy_failure(self):
        p = next(self.session.glob("runs/parent*/*_aggregate.json"))
        data = json.loads(p.read_text()); data["tasks"][0]["episodes"][0]["failure_reason"] = "timeout"; p.write_text(json.dumps(data))
        case = import_m4(self.root)
        episode = next(x for x in case["evidence"]["episodes"] if x["stage"] == p.parent.name)
        self.assertEqual((episode["raw_outcome"], episode["gate_outcome"]), ("episode_timeout", "policy_failure"))

    def test_parent_decision_must_match_raw_gate_sequence(self):
        p = self.session / "session_summary.json"; data = json.loads(p.read_text())
        data["completed"]["decisions"][0]["outcomes"] = ["success"] * 4; p.write_text(json.dumps(data))
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "conflicting")

    def test_parent_stage_geometry_must_match_declared_parent(self):
        other = {"x": .25, "y": 0, "width": .5, "height": .5}
        p = self.session / "session_summary.json"; summary = json.loads(p.read_text())
        for stage in summary["completed"]["stages"]:
            if stage["stage"].startswith("parent-"): stage["rectangle"] = other
        p.write_text(json.dumps(summary))
        for aggregate in self.session.glob("runs/parent*/*_aggregate.json"):
            data = json.loads(aggregate.read_text()); data["config"]["params"]["agentview_occlusion"].update(other)
            aggregate.write_text(json.dumps(data))
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "conflicting")

    def test_lineage_never_copies_untrusted_edge_or_delta_payload(self):
        p = self.session / "session_summary.json"; data = json.loads(p.read_text())
        data["lineage"][0]["edge"] = "private_command=token-do-not-copy"
        data["lineage"][0]["delta"] = "https://private.invalid/secret"
        p.write_text(json.dumps(data))
        case = import_m4(self.root)
        self.assertNotIn("token-do-not-copy", json.dumps(case))
        self.assertNotIn("private.invalid", json.dumps(case))
        self.assertEqual(case["capabilities"]["historical_failure"]["status"], "conflicting")

    def test_unhashable_lineage_edge_and_huge_delta_are_sanitized(self):
        p = self.session / "session_summary.json"; data = json.loads(p.read_text())
        data["lineage"][0]["edge"] = {"private_command": "token-do-not-copy"}
        data["lineage"][0]["delta"] = 10 ** 1000
        p.write_text(json.dumps(data))
        case = import_m4(self.root)
        self.assertNotIn("token-do-not-copy", json.dumps(case))
        self.assertEqual(case["capabilities"]["historical_failure"]["status"], "conflicting")

    def test_bool_aggregate_seed_and_result_count_cannot_confirm_history(self):
        p = next(self.session.glob("runs/parent*/*_aggregate.json"))
        data = json.loads(p.read_text()); data["config"]["params"]["seed"] = True; p.write_text(json.dumps(data))
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "conflicting")
        data["config"]["params"]["seed"] = 7; p.write_text(json.dumps(data))
        summary_path = self.session / "session_summary.json"; summary = json.loads(summary_path.read_text())
        summary["completed"]["stages"][1]["physical_episode_count"] = True; summary_path.write_text(json.dumps(summary))
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "conflicting")

    def test_arbitrary_reported_count_is_not_copied(self):
        p = self.session / "session_summary.json"; data = json.loads(p.read_text())
        data["physical_episode_count"] = {"private_command": "token-do-not-copy"}; p.write_text(json.dumps(data))
        case = import_m4(self.root)
        self.assertNotIn("token-do-not-copy", json.dumps(case))
        self.assertIsNone(case["measurements"]["physical_episode_count"])
        self.assertEqual(case["capabilities"]["historical_failure"]["status"], "conflicting")

    def test_explicit_wrong_server_policy_is_conflicting(self):
        p = next(self.session.glob("runs/parent*/*_aggregate.json"))
        data = json.loads(p.read_text()); data["server_info"]["model_identity"] = "other-model"; p.write_text(json.dumps(data))
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "conflicting")

    def test_no_selected_aggregates_means_inspection_unavailable(self):
        for p in self.session.glob("runs/*/*_aggregate.json"): p.unlink()
        case = import_m4(self.root)
        self.assertEqual(case["capabilities"]["inspection"]["status"], "unavailable")

    def test_accepted_count_must_be_supported_by_raw_reduced_episodes(self):
        p = self.session / "session_summary.json"; data = json.loads(p.read_text())
        removed = next(stage for stage in data["completed"]["stages"] if stage["stage"].startswith("delta-"))
        data["completed"]["stages"].remove(removed)
        data["valid_episode_count"] = 13; data["physical_episode_count"] = 13
        p.write_text(json.dumps(data))
        case = import_m4(self.root)
        self.assertNotEqual(case["capabilities"]["historical_failure"]["status"], "confirmed")

    def test_stage_result_episode_index_mismatch_conflicts(self):
        p = self.session / "session_summary.json"; data = json.loads(p.read_text())
        data["completed"]["stages"][2]["results"][0]["episode_index"] = 1; p.write_text(json.dumps(data))
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "conflicting")

    def test_nominal_sentinel_raw_failure_conflicts(self):
        p = next(self.session.glob("runs/nominal-sentinel/*_aggregate.json"))
        data = json.loads(p.read_text()); data["tasks"][0]["episodes"][0]["metrics"]["success"] = False; p.write_text(json.dumps(data))
        self.assertEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "conflicting")

    def test_invalid_final_geometry_refused(self):
        p = self.session / "session_summary.json"; data = json.loads(p.read_text())
        data["geometry"]["final"] = None; p.write_text(json.dumps(data))
        with self.assertRaises(SanitizedCaseValidationError): import_m4(self.root)

    def test_oversize_json_and_escaping_symlink_are_rejected(self):
        p = self.session / "replay_case.json"
        p.write_bytes(b" " * (8 * 1024 * 1024 + 1))
        with self.assertRaises(SanitizedCaseValidationError): import_m4(self.root)
        outside = self.root.parent / (self.root.name + "-outside.json")
        outside.write_text("{}")
        p.unlink()
        try:
            p.symlink_to(outside)
        except OSError:
            outside.unlink(); self.skipTest("symlinks unavailable")
        try:
            with self.assertRaises(SanitizedCaseValidationError): import_m4(self.root)
        finally: outside.unlink()

    def test_profile_conflicting_pin_and_bad_hash_refused(self):
        proof = self.session / "proof.txt"; proof.write_text("proof")
        ref = {"path": "failure-reduction/proof.txt", "sha256": "0" * 64}
        data = {"schema_version": 1, "policy": {"model_id": "opaque-model"}, "runtime": {}, "provenance": {"policy.model_id": ref}}
        p = self.session / "profile.json"; p.write_text(json.dumps(data))
        with self.assertRaises(SanitizedCaseValidationError): import_m4(self.root, profile="failure-reduction/profile.json")
        import hashlib
        ref["sha256"] = hashlib.sha256(proof.read_bytes()).hexdigest(); data["policy"]["model_id"] = "other"; p.write_text(json.dumps(data))
        with self.assertRaises(SanitizedCaseValidationError): import_m4(self.root, profile="failure-reduction/profile.json")

    def test_infrastructure_episode_cannot_confirm_history(self):
        p = next(self.session.glob("runs/parent*/*_aggregate.json"))
        data = json.loads(p.read_text()); data["tasks"][0]["episodes"][0]["failure_reason"] = "exception"; p.write_text(json.dumps(data))
        self.assertNotEqual(import_m4(self.root)["capabilities"]["historical_failure"]["status"], "confirmed")

    def test_summary_parent_controls_run_lookup(self):
        import shutil
        target = self.root / "other-session"
        shutil.move(str(self.session), target)
        case = import_m4(self.root, summary="other-session/session_summary.json", replay="other-session/replay_case.json")
        self.assertEqual(case["capabilities"]["historical_failure"]["status"], "confirmed")


if __name__ == "__main__": unittest.main()
