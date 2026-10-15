"""The breadth pack's new audit families and suites are accepted by the spec and the Job validator."""

from __future__ import annotations

import copy
import unittest

from robot_debug import job_runtime as jr
from robot_debug import spec as sp
from tests.test_spec import audit_spec

NEW_FAMILIES = ("jpeg", "colour_cast", "motion_blur", "dead_pixels", "viewpoint", "lighting")
NEW_SUITES = ("libero_spatial", "libero_goal")
THRESHOLD = {
    "schema_version": 1, "mode": "m6-threshold", "run_id": "audit-1", "deadline_seconds": 2400,
    "families": ["darken"], "sweep": [0.2, 0.4, 0.6, 0.8, 1.0], "attempts": 5,
    "required_failures": 4, "bisection_steps": 4,
}


class SpecAcceptsTheBreadthPack(unittest.TestCase):
    def test_every_new_family_is_a_spec_family(self):
        for family in NEW_FAMILIES:
            with self.subTest(family=family):
                data = audit_spec()
                data["audit"]["families"] = [family]
                self.assertEqual((family,), sp.parse_spec(data).audit.families)

    def test_the_legacy_families_come_first_and_all_ten_are_distinct(self):
        self.assertEqual(("darken", "noise", "blur", "contrast"), sp.FAMILIES[:4])
        self.assertEqual(10, len(set(sp.FAMILIES)))
        data = audit_spec()
        data["audit"]["families"] = list(sp.FAMILIES)
        self.assertEqual(10, len(sp.parse_spec(data).audit.families))

    def test_new_suites_are_spec_suites(self):
        for suite in NEW_SUITES:
            with self.subTest(suite=suite):
                data = audit_spec()
                data["policy"] = {"suite": suite}
                self.assertEqual(suite, sp.parse_spec(data).suite)

    def test_unknown_names_are_still_refused(self):
        data = audit_spec()
        data["audit"]["families"] = ["sepia"]
        with self.assertRaises(sp.SpecError):
            sp.parse_spec(data)
        data = audit_spec()
        data["policy"] = {"suite": "libero_90"}
        with self.assertRaises(sp.SpecError):
            sp.parse_spec(data)


class JobValidatorAcceptsTheBreadthPack(unittest.TestCase):
    def test_the_recorded_m6_families_are_unchanged(self):
        self.assertEqual(("darken", "noise", "blur", "contrast"), jr.M6_FAMILIES)
        self.assertEqual(jr.M6_FAMILIES + NEW_FAMILIES, jr.AUDIT_FAMILIES)

    def test_threshold_workloads_may_name_new_families_and_suites(self):
        for family in NEW_FAMILIES:
            config = dict(THRESHOLD, families=[family], suite="libero_goal", task_id=2)
            self.assertEqual([family], jr.validate_workload_config(config)["families"])
        for suite in NEW_SUITES:
            self.assertEqual(suite, jr.validate_workload_config(dict(THRESHOLD, suite=suite))["suite"])

    def test_unknown_families_and_suites_are_refused(self):
        for changes in ({"families": ["sepia"]}, {"families": ["jpeg", "jpeg"]}, {"suite": "libero_90"}):
            with self.subTest(changes=changes), self.assertRaises(jr.JobRuntimeError):
                jr.validate_workload_config(dict(copy.deepcopy(THRESHOLD), **changes))

    def test_the_episode_bound_still_applies(self):
        with self.assertRaises(jr.JobRuntimeError):
            jr.validate_workload_config(dict(
                THRESHOLD, families=list(jr.AUDIT_FAMILIES), sweep=[0.1 * i for i in range(1, 9)],
                attempts=12, required_failures=10, bisection_steps=6))


if __name__ == "__main__":
    unittest.main()
