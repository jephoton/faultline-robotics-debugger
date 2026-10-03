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
    summary = {"schema_version": 1, "model_identity": "opaque-model", "repository_revision": "revision", "planned": {"model_identity": "opaque-model"}, "completed": {"stages": stages, "sentinel_outcome": "success", "control_outcomes": ["success"] * 5, "decisions": [{"label": "candidate", "decision": "pass", "rectangle": FINAL, "outcomes": ["policy_failure"] * 4}]}, "geometry": {"parent": PARENT, "current": FINAL, "final": FINAL}, "certified_rectangle": FINAL, "lineage": [{"edge": "bottom", "delta": .125, "rectangle": FINAL}], "stop_reason": "reduced_failure_with_nominal_controls", "elapsed_seconds": 42.0, "physical_episode_count": 14, "valid_episode_count": 14}
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


if __name__ == "__main__": unittest.main()
