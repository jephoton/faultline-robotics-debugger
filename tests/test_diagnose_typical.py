"""The typical cost and time model of the dry run, against the measured references it is built from."""

from __future__ import annotations

import unittest

import yaml

from robot_debug import orchestrator as orch
from robot_debug import pipeline as pl
from robot_debug import spec as sp
from robot_debug.viewer import specs as vs
from tests.test_orchestrator import FakeTools

RATE = 1.7468


class Model(unittest.TestCase):
    def test_the_check_matches_its_measured_run(self):
        minutes = pl.typical_container_minutes("check")
        self.assertEqual(minutes, 10.6)
        self.assertAlmostEqual(pl.typical_cost(minutes, RATE), 0.43, delta=0.01)       # measured US$0.43

    def test_an_audit_is_eight_minutes_plus_four_per_family(self):
        self.assertEqual(pl.typical_container_minutes("probe", 1), 12.0)
        self.assertEqual(pl.typical_container_minutes("probe", 4), 24.0)
        # Four families measured 20.4 min, four image families on LIBERO-Spatial 24.3, viewpoint+lighting 9.6:
        # the model is within a few minutes of each and errs towards longer.
        for families, measured in ((4, 20.4), (4, 24.3), (2, 9.6)):
            self.assertGreaterEqual(pl.typical_container_minutes("probe", families), measured - 0.5)
            self.assertLessEqual(pl.typical_container_minutes("probe", families) - measured, 7.0)

    def test_the_other_jobs_use_the_middle_of_their_measured_ranges(self):
        self.assertEqual(pl.typical_container_minutes("layout"), 19.5)            # measured 18-21
        self.assertEqual(pl.typical_container_minutes("rewording-screen"), 7.5)   # measured 7-8
        self.assertEqual(pl.typical_container_minutes("replay"), 10.2)
        self.assertAlmostEqual(pl.typical_cost(19.5, RATE), 0.68, delta=0.04)      # measured US$0.65-0.72
        self.assertAlmostEqual(pl.typical_cost(7.5, RATE), 0.33, delta=0.03)       # measured US$0.31-0.35
        self.assertAlmostEqual(pl.typical_cost(10.2, RATE), 0.41, delta=0.02)      # measured US$0.41

    def test_longer_episodes_stretch_the_testing_part_of_a_job(self):
        # The references were measured on LIBERO-Object; LIBERO-10's episodes are about three times longer.
        for kind, families in (("check", 0), ("probe", 4), ("rewording-screen", 0)):
            object_minutes = pl.typical_container_minutes(kind, families)
            long_minutes = pl.typical_container_minutes(kind, families, suite="libero_10")
            self.assertGreater(long_minutes, object_minutes, kind)
            self.assertLess(long_minutes, object_minutes * 3.0, "the start-up does not stretch")
        for suite in ("libero_object", "libero_spatial", "an-unknown-suite"):
            self.assertEqual(pl.typical_container_minutes("probe", 4, suite=suite),
                             pl.typical_container_minutes("probe", 4))

    def test_a_job_never_takes_longer_than_its_deadline(self):
        self.assertEqual(pl.typical_container_minutes("probe", 4, deadline_seconds=600), 10.0)
        self.assertEqual(pl.typical_container_minutes("check", deadline_seconds=3000), 10.6)

    def test_end_to_end_adds_the_submit_and_download_time(self):
        self.assertEqual(pl.typical_total_minutes(10.6), 15.6)

    def test_the_cost_includes_the_four_minute_start_allowance(self):
        self.assertAlmostEqual(pl.typical_cost(0.0, 60.0), 4.0)
        self.assertAlmostEqual(pl.typical_cost(56.0, 60.0), 60.0)


def plan_of(suite=None, **diagnose):
    with open("configs/specs/diagnose.yaml", encoding="utf-8") as handle:
        mapping = yaml.safe_load(handle)
    mapping["diagnose"].update(diagnose)
    if suite is not None:
        mapping["policy"]["suite"] = suite
    lines, required = orch.dry_run_lines(sp.parse_spec(mapping), FakeTools())
    return lines, vs.parse_plan_branches(lines, required)[2]


class DryRunFigures(unittest.TestCase):
    def test_every_branch_has_typical_dollars_and_minutes(self):
        _lines, branches = plan_of()
        by = {b["branch"]: b for b in branches}
        self.assertEqual(set(by), {"check", "layout", "probes"})
        for branch in branches:
            self.assertGreater(branch["typical_usd"], 0)
            self.assertIsInstance(branch["typical_minutes"], int)
        self.assertEqual(by["check"]["typical_minutes"], 16)                    # 10.6 + 5, rounded
        self.assertAlmostEqual(by["check"]["typical_usd"], 0.43, delta=0.01)
        self.assertEqual(by["probes"]["typical_minutes"], 29)                    # 8 + 4 x 4 = 24, + 5
        self.assertAlmostEqual(by["probes"]["typical_usd"], (24 + 4) / 60 * RATE, delta=0.01)
        self.assertEqual(by["layout"]["typical_minutes"], 25)                    # 19.5 + 5, rounded

    def test_optional_jobs_are_not_in_the_typical_figures(self):
        _lines, with_reduce = plan_of(probes={"families": [], "rewordings": 4})
        by = {b["branch"]: b for b in with_reduce}
        self.assertEqual(by["probes"]["typical_minutes"], 13)                    # the screen only: 7.5 + 5
        _lines, continuations = plan_of()
        self.assertEqual({b["branch"]: b for b in continuations}["layout"]["typical_minutes"], 25)

    def test_a_libero_10_plan_is_slower_and_dearer_than_the_same_plan_on_libero_object(self):
        _lines, quick = plan_of()
        _lines, slow = plan_of(suite="libero_10")
        quick, slow = {b["branch"]: b for b in quick}, {b["branch"]: b for b in slow}
        for branch in ("check", "probes"):
            self.assertGreater(slow[branch]["typical_minutes"], quick[branch]["typical_minutes"], branch)
            self.assertGreater(slow[branch]["typical_usd"], quick[branch]["typical_usd"], branch)
            self.assertLessEqual(slow[branch]["typical_usd"], slow[branch]["worst_case_usd"], branch)

    def test_more_families_cost_more_time_in_more_jobs(self):
        _lines, branches = plan_of(probes={"families": list(sp.FAMILIES), "rewordings": 0})
        probes = {b["branch"]: b for b in branches}["probes"]
        # image 4 + 4 and scene 2: (8+16) + (8+16) + (8+8) = 64 container min, + 5 per Job
        self.assertEqual(probes["typical_minutes"], 79)

    def test_the_line_format_is_what_the_panel_parses(self):
        lines, _branches = plan_of()
        self.assertTrue(any(line.startswith("Branch probes: worst case US$") and " in about 29 min." in line
                            for line in lines))


if __name__ == "__main__":
    unittest.main()
