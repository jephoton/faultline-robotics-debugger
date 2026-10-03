"""Contract tests for structural, deterministic case records."""

import copy
import unittest

from robot_debug.cases import CaseValidationError, case_identity, normalize_case, recipe_missing


def complete_case():
    return {
        "schema_version": 1,
        "source": {
            "adapter": "existing-m4-v1",
            "summary": {"path": "runs/summary.json", "sha256": "a" * 64},
            "replay": {"path": "runs/replay.json", "sha256": "b" * 64},
            "profile": None,
        },
        "task": {
            "suite": "libero-object", "task_id": 0, "reset_index": 0,
            "seed": 7, "env_seed": 7, "reset_strategy": "libero-init-state-index",
        },
        "policy": {
            "model_id": "example-policy", "checkpoint_revision": "example-revision",
            "provenance": {},
        },
        "runtime": {
            "project_revision": "example-project-revision",
            "upstream_harness_revision": "example-harness-revision",
            "simulator_image_digest": "sha256:" + "c" * 64,
            "provenance": {},
        },
        "perturbation": {
            "family": "agentview-opaque-rectangle",
            "rectangle": {"x": 0.625, "y": 0, "width": 0.375, "height": 0.375},
            "fill_value": 0,
        },
        "protocol": {
            "failures": 4, "max_attempts": 5, "reject_successes": 2,
            "nominal_controls": 5,
        },
        "evidence": {}, "measurements": {}, "capabilities": {}, "limitations": [],
    }


class CaseSchemaTests(unittest.TestCase):
    def test_numeric_geometry_forms_share_identity_without_mutation(self):
        raw = complete_case()
        variant = copy.deepcopy(raw)
        variant["perturbation"]["rectangle"]["y"] = 0.0
        before = copy.deepcopy(raw)
        normalized = normalize_case(raw)
        self.assertEqual(normalized["case_id"], case_identity(variant))
        self.assertEqual(recipe_missing(raw), [])
        self.assertEqual(raw, before)
        self.assertNotIn("case_id", raw)

    def test_identity_is_full_sha256_and_stored_id_must_match(self):
        raw = complete_case()
        case_id = case_identity(raw)
        self.assertEqual(len(case_id), 64)
        self.assertEqual(normalize_case({**raw, "case_id": case_id})["case_id"], case_id)
        wrong = {**raw, "case_id": "0" * 64}
        self.assertEqual(case_identity(wrong), case_id)
        with self.assertRaises(CaseValidationError):
            normalize_case(wrong)

    def test_nonidentity_metadata_does_not_change_identity(self):
        raw = complete_case()
        case_id = case_identity(raw)
        changed = copy.deepcopy(raw)
        changed["source"]["summary"] = {"path": "other/summary.json", "sha256": "d" * 64}
        changed["source"]["replay"] = {"path": "other/replay.json", "sha256": "e" * 64}
        changed["source"]["profile"] = {"path": "other/profile.json", "sha256": "f" * 64}
        changed["policy"]["provenance"] = {"upstream": ["a", {"score": 1.5}]}
        changed["runtime"]["provenance"] = {"build": "x"}
        changed["evidence"] = {"claimed_failure": True}
        changed["measurements"] = {"cost": 1.25}
        changed["capabilities"] = {"claimed_verified_replay": True}
        changed["limitations"] = ["untested"]
        self.assertEqual(case_identity(changed), case_id)
        self.assertEqual(normalize_case(changed)["capabilities"], changed["capabilities"])

    def test_identity_changes_for_replay_recipe_inputs(self):
        raw = complete_case()
        for path, replacement in [
            (("task", "task_id"), 1), (("task", "reset_index"), 1),
            (("task", "seed"), 8), (("task", "env_seed"), 8),
            (("runtime", "project_revision"), "new-project"),
            (("runtime", "upstream_harness_revision"), "new-harness"),
            (("runtime", "simulator_image_digest"), "sha256:" + "d" * 64),
            (("perturbation", "rectangle", "x"), 0.5),
            (("perturbation", "fill_value"), 1),
        ]:
            with self.subTest(path=path):
                changed = copy.deepcopy(raw)
                field = changed
                for key in path[:-1]:
                    field = field[key]
                field[path[-1]] = replacement
                self.assertNotEqual(case_identity(changed), case_identity(raw))

    def test_recipe_missing_lists_only_nullable_recipe_fields(self):
        raw = complete_case()
        expected = [
            "perturbation.fill_value", "policy.checkpoint_revision", "policy.model_id",
            "runtime.project_revision", "runtime.simulator_image_digest",
            "runtime.upstream_harness_revision", "task.env_seed", "task.seed",
        ]
        for dotted in expected:
            group, field = dotted.split(".")
            raw[group][field] = None
        raw["capabilities"]["verified_replay"] = True
        self.assertEqual(recipe_missing(raw), expected)

    def test_deep_copy_including_mutable_nonidentity_metadata(self):
        raw = complete_case()
        raw["evidence"] = {"nested": [{"ok": True}]}
        normalized = normalize_case(raw)
        normalized["evidence"]["nested"][0]["ok"] = False
        normalized["source"]["summary"]["path"] = "other.json"
        self.assertEqual(raw["evidence"]["nested"][0]["ok"], True)
        self.assertEqual(raw["source"]["summary"]["path"], "runs/summary.json")

    def test_rejects_invalid_values(self):
        invalid = [
            (("schema_version",), True), (("schema_version",), 2),
            (("task", "task_id"), True), (("task", "reset_index"), -1),
            (("task", "seed"), True), (("task", "suite"), "other"),
            (("task", "reset_strategy"), "other"),
            (("source", "adapter"), "other"),
            (("source", "summary", "path"), "../escape"),
            (("source", "summary", "path"), "C:/absolute"),
            (("source", "summary", "path"), "a\\b"),
            (("source", "summary", "path"), "a//b"),
            (("source", "summary", "path"), "a/./b"),
            (("source", "replay", "sha256"), "A" * 64),
            (("runtime", "simulator_image_digest"), "sha256:" + "G" * 64),
            (("perturbation", "family"), "other"),
            (("perturbation", "rectangle", "x"), True),
            (("perturbation", "rectangle", "x"), float("nan")),
            (("perturbation", "rectangle", "y"), float("inf")),
            (("perturbation", "rectangle", "width"), 0),
            (("perturbation", "rectangle", "height"), -0.1),
            (("perturbation", "rectangle", "x"), 0.9),
            (("perturbation", "fill_value"), True),
            (("perturbation", "fill_value"), 256),
            (("protocol", "failures"), True),
            (("protocol", "max_attempts"), 4),
            (("evidence",), {"bad": float("nan")}),
            (("measurements",), {"bad": (1, 2)}),
            (("capabilities",), {1: "bad"}),
            (("policy", "provenance"), {"bad": b"bytes"}),
            (("limitations",), [1]),
        ]
        for path, replacement in invalid:
            with self.subTest(path=path, replacement=replacement):
                raw = complete_case()
                field = raw
                for key in path[:-1]:
                    field = field[key]
                field[path[-1]] = replacement
                with self.assertRaises(CaseValidationError):
                    normalize_case(raw)

    def test_rejects_unknown_or_missing_structural_keys(self):
        for path in [("extra",), ("source", "extra"), ("task", "extra"),
                     ("policy", "extra"), ("runtime", "extra"),
                     ("perturbation", "extra"), ("perturbation", "rectangle", "extra"),
                     ("protocol", "extra"), ("source", "summary", "extra")]:
            with self.subTest(path=path):
                raw = complete_case()
                field = raw
                for key in path[:-1]:
                    field = field[key]
                field[path[-1]] = "unexpected"
                with self.assertRaises(CaseValidationError):
                    normalize_case(raw)

    def test_rejects_cyclic_metadata_and_unbounded_geometry(self):
        raw = complete_case()
        raw["evidence"]["cycle"] = raw["evidence"]
        with self.assertRaises(CaseValidationError):
            normalize_case(raw)
        raw = complete_case()
        raw["perturbation"]["rectangle"]["x"] = 10 ** 400
        with self.assertRaises(CaseValidationError):
            normalize_case(raw)
        for key in complete_case():
            with self.subTest(missing=key):
                raw = complete_case()
                del raw[key]
                with self.assertRaises(CaseValidationError):
                    normalize_case(raw)


if __name__ == "__main__":
    unittest.main()
