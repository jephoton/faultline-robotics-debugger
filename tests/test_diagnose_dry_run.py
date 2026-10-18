"""The dry run of a diagnosis: branches, probe grouping, worst case = check + larger branch."""

from __future__ import annotations

import copy
import unittest

import yaml

from robot_debug import m6_experiment
from robot_debug import orchestrator as orch
from robot_debug import pipeline
from robot_debug import spec as sp
from robot_debug.viewer import specs as vs
from tests.test_diagnose_ui_specs import ServiceCase, template_mapping
from tests.test_orchestrator import FakeTools

ALL = list(sp.FAMILIES)


def template_file():
    with open("configs/specs/diagnose.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class ProbeGroups(unittest.TestCase):
    def test_ten_families_on_libero_object_split_into_images_4_and_4_and_the_scenes(self):
        groups = pipeline.probe_groups("libero_object", ALL)
        self.assertEqual([g.step for g in groups], ["probe-image-1", "probe-image-2", "probe-scene-1"])
        self.assertEqual([len(g.families) for g in groups], [4, 4, 2])
        self.assertEqual(groups[2].families, ("viewpoint", "lighting"))
        self.assertEqual(sorted(name for g in groups for name in g.families), sorted(ALL))

    def test_every_group_fits_the_deadline_cap_of_its_suite(self):
        for suite in m6_experiment.SUITES:
            with self.subTest(suite=suite):
                for group in pipeline.probe_groups(suite, ALL):
                    config = {"families": list(group.families), "sweep": [0.2, 0.4, 0.6, 0.8, 1.0], "attempts": 5,
                              "bisection_steps": 4, "suite": suite}
                    self.assertEqual(group.deadline_seconds,
                                     m6_experiment.recommended_deadline_seconds("m6-threshold", config))

    def test_libero_10_needs_more_and_smaller_groups(self):
        groups = pipeline.probe_groups("libero_10", ALL)
        self.assertGreater(len(groups), 3)
        self.assertTrue(all(len(g.families) <= 2 for g in groups))

    def test_a_few_families_stay_in_one_job_and_scenes_never_mix_with_images(self):
        groups = pipeline.probe_groups("libero_object", ["blur", "lighting"])
        self.assertEqual([(g.step, g.families) for g in groups],
                         [("probe-image-1", ("blur",)), ("probe-scene-1", ("lighting",))])
        self.assertEqual(pipeline.probe_groups("libero_object", []), [])

    def test_severity_text(self):
        self.assertEqual([pipeline.severity_text(v) for v in (0.5, 1, 0.4125, 0.0125, 0.2)],
                         ["0.50", "1.00", "0.4125", "0.0125", "0.20"])


def spec_of(**changes):
    mapping = template_file()
    for key, value in changes.items():
        mapping["diagnose"][key] = value
    return sp.parse_spec(mapping)


class DryRunLines(unittest.TestCase):
    def plan(self, spec):
        lines, required = orch.dry_run_lines(spec, FakeTools())
        return lines, required, vs.parse_plan_branches(lines, required)

    def test_the_template_lists_three_branches_and_counts_the_larger_one_once(self):
        lines, required, (jobs, total, branches) = self.plan(spec_of(probes={"families": ALL, "rewordings": 10}))
        self.assertEqual([j["name"] for j in jobs], [
            "screen", "reduce", "reduce2", "reduce3", "reduce4", "probe-image-1", "probe-image-2",
            "probe-scene-1", "rewording-screen", "rewording-reduce"])
        self.assertEqual({j["branch"] for j in jobs}, {"check", "layout", "probes"})
        by = {b["branch"]: b for b in branches}
        self.assertEqual(set(by), {"check", "layout", "probes"})
        self.assertGreater(by["layout"]["typical_usd"], 0)
        self.assertGreater(by["probes"]["typical_minutes"], by["check"]["typical_minutes"])
        self.assertAlmostEqual(total, by["check"]["worst_case_usd"] + max(
            by["layout"]["worst_case_usd"], by["probes"]["worst_case_usd"]), delta=0.02)
        self.assertAlmostEqual(total, required, delta=0.02)
        optional = {j["name"] for j in jobs if j["optional"]}
        self.assertEqual(optional, {"reduce2", "reduce3", "reduce4", "rewording-reduce"})

    def test_the_template_defaults_to_the_four_families_that_failed_before(self):
        spec = spec_of()
        self.assertEqual(spec.diagnose.probes.families, ("blur", "noise", "darken", "contrast"))
        self.assertEqual(spec.diagnose.probes.rewordings, 0)
        self.assertIsNone(spec.paraphrase)
        self.assertEqual((spec.budget.max_spend_usd, spec.budget.max_hours, spec.budget.max_candidates),
                         (2.5, 1.5, 36))
        self.assertTrue(spec.research)

    def test_the_template_cap_covers_the_typical_cost_of_either_branch(self):
        spec = spec_of()
        lines, required, (_jobs, _total, branches) = self.plan(spec)
        by = {b["branch"]: b for b in branches}
        typical_probe = by["check"]["typical_usd"] + by["probes"]["typical_usd"]
        self.assertLess(typical_probe, spec.budget.max_spend_usd)
        self.assertLess(by["check"]["typical_usd"] + by["layout"]["typical_usd"], spec.budget.max_spend_usd)
        self.assertTrue(any(line.startswith("WARNING") for line in lines), "the worst case is over the cap")
        self.assertEqual([j["name"] for j in _jobs if j["branch"] == "probes"], ["probe-image-1"])

    def test_a_range_or_an_import_has_no_probe_branch(self):
        spec = sp.parse_spec(dict(template_file(),
                                  diagnose={"task": 0, "screen": {"starts": "10-19"}}))
        _lines, _required, (jobs, _total, branches) = self.plan(spec)
        self.assertEqual({j["branch"] for j in jobs}, {"check", "layout"})
        self.assertEqual({b["branch"] for b in branches}, {"check", "layout"})

    def test_probe_only_has_no_layout_branch_and_says_so(self):
        lines, _required, (jobs, total, branches) = self.plan(spec_of(layout=False))
        self.assertEqual({j["branch"] for j in jobs}, {"check", "probes"})
        self.assertTrue(any(line.startswith("PROBES (probe only") for line in lines))
        by = {b["branch"]: b["worst_case_usd"] for b in branches}
        self.assertAlmostEqual(total, by["check"] + by["probes"], delta=0.02)

    def test_no_probes_is_the_check_and_the_layout(self):
        spec = spec_of(probes={"enabled": False})
        _lines, _required, (jobs, _total, branches) = self.plan(spec)
        self.assertEqual({j["branch"] for j in jobs}, {"check", "layout"})

    def test_families_only_or_rewordings_only(self):
        _l, _r, (jobs, _t, _b) = self.plan(spec_of(probes={"families": ["blur"], "rewordings": 0}))
        self.assertEqual([j["name"] for j in jobs if j["branch"] == "probes"], ["probe-image-1"])
        _l, _r, (jobs, _t, _b) = self.plan(spec_of(probes={"families": [], "rewordings": 4}))
        self.assertEqual([j["name"] for j in jobs if j["branch"] == "probes"],
                         ["rewording-screen", "rewording-reduce"])

    def test_the_cap_warning_names_the_exceeded_budget(self):
        mapping = template_file()
        mapping["budget"]["max_spend_usd"] = 2.0
        lines, _required = orch.dry_run_lines(sp.parse_spec(mapping), FakeTools())
        self.assertTrue(any(line.startswith("WARNING: that exceeds the cap") for line in lines))

    def test_existing_modes_keep_their_text_and_get_no_branch(self):
        from tests.test_orchestrator import spec_for

        lines, required = orch.dry_run_lines(spec_for(), FakeTools())
        jobs, total, branches = vs.parse_plan_branches(lines, required)
        self.assertEqual(branches, [])
        self.assertEqual({j["branch"] for j in jobs}, {None})


class DryRunApi(ServiceCase):
    def test_the_service_returns_branches_and_the_branch_of_every_job(self):
        plan = self.service.dry_run(self.service.template("diagnose")["yaml"])
        self.assertEqual({j["branch"] for j in plan["jobs"]}, {"check", "layout", "probes"})
        self.assertEqual([b["branch"] for b in plan["branches"]], ["check", "layout", "probes"])
        self.assertGreater(plan["branches"][1]["typical_minutes"], 0)
        self.assertGreater(plan["branches"][2]["typical_usd"], 0)
        self.assertGreater(plan["worst_case_total_usd"], plan["branches"][0]["worst_case_usd"])

    def test_other_modes_return_an_empty_branch_list(self):
        plan = self.service.dry_run(self.service.template("audit")["yaml"])
        self.assertEqual(plan["branches"], [])

    def test_libero_10_plans_more_probe_jobs(self):
        mapping = template_mapping(self.service)
        mapping["policy"]["suite"] = "libero_10"
        mapping["diagnose"]["probes"]["families"] = list(sp.FAMILIES)
        plan = self.service.dry_run(yaml.safe_dump(mapping))
        self.assertGreater(len([j for j in plan["jobs"] if j["name"].startswith("probe-")]), 3)

    def test_the_plan_hash_changes_with_the_probes(self):
        base = template_mapping(self.service)
        other = copy.deepcopy(base)
        other["diagnose"]["probes"]["families"] = ["blur"]
        first = self.service.dry_run(yaml.safe_dump(base))["plan_hash"]
        self.assertNotEqual(first, self.service.dry_run(yaml.safe_dump(other))["plan_hash"])


if __name__ == "__main__":
    unittest.main()
