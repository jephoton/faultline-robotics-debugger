"""The ``diagnose`` spec mode (ADR 0035): one diagnosis that routes on the untouched result."""

from __future__ import annotations

import unittest
from pathlib import Path

from robot_debug import spec as sp

ROOT = Path(__file__).parents[1]

BACKEND = {"kind": "nebius", "image": "cr.example.invalid/REGISTRY_ID/faultline@sha256:abc",
           "hf_token_secret": "faultline-hf-token", "hourly_usd": 1.7468}


def diagnose_spec(**diagnose):
    return {
        "faultline": 1, "name": "diag-object", "mode": "diagnose", "policy": {"suite": "libero_object"},
        "diagnose": dict({"task": 0, "start": 0,
                          "probes": {"families": ["blur", "noise"], "rewordings": 10}}, **diagnose),
        "budget": {"max_spend_usd": 9.0, "max_hours": 5}, "nemotron": {"hypothesis": True},
        "backend": dict(BACKEND),
    }


class DiagnoseMode(unittest.TestCase):
    def refused(self, data, fragment):
        with self.assertRaises(sp.SpecError) as caught:
            sp.parse_spec(data)
        self.assertIn(fragment, str(caught.exception))

    def test_a_start_with_probes_parses_and_derives_the_existing_sections(self):
        spec = sp.parse_spec(diagnose_spec())
        self.assertEqual(spec.mode, "diagnose")
        self.assertEqual(spec.mode_label, "diagnosis")
        self.assertEqual((spec.diagnose.task, spec.diagnose.layout), (0, True))
        self.assertEqual(spec.diagnose.probes.families, ("blur", "noise"))
        self.assertEqual(spec.diagnose.probes.rewordings, 10)
        self.assertTrue(spec.diagnose.probes.active)
        self.assertEqual((spec.scenario.task, spec.scenario.start, spec.scenario.pool_text), (0, 0, "0-19"))
        self.assertEqual((spec.paraphrase.start, spec.paraphrase.count), (0, 10))
        self.assertIn("alphabet soup", spec.paraphrase.instruction)

    def test_no_probes_means_the_layout_diagnosis_alone(self):
        data = diagnose_spec()
        del data["diagnose"]["probes"]
        spec = sp.parse_spec(data)
        self.assertFalse(spec.diagnose.probes.active)
        self.assertIsNone(spec.paraphrase)

    def test_a_range_and_an_import_are_layout_only(self):
        for key, value in (("screen", {"starts": "10-12"}), ("import", "start.json")):
            with self.subTest(key=key):
                data = diagnose_spec()
                del data["diagnose"]["start"]
                data["diagnose"][key] = value
                self.refused(data, "diagnose.probes")           # the template's default probes are refused
                data["diagnose"]["probes"] = {"enabled": False}
                spec = sp.parse_spec(data)
                self.assertIsNone(spec.scenario.start)
                data["diagnose"]["probes"] = {"families": [], "rewordings": 0}
                sp.parse_spec(data)
                data["diagnose"]["layout"] = False
                self.refused(data, "diagnose.layout")

    def test_probe_only_needs_something_to_probe(self):
        data = diagnose_spec(layout=False)
        self.assertFalse(sp.parse_spec(data).diagnose.layout)
        data["diagnose"]["probes"]["enabled"] = False
        self.refused(data, "diagnose.layout")
        data["diagnose"]["probes"] = {"families": [], "rewordings": 0}
        self.refused(data, "diagnose.layout")

    def test_unknown_and_repeated_families_and_bad_counts(self):
        for probes, fragment in (({"families": ["blur", "sparkle"]}, "unknown family"),
                                 ({"families": ["blur", "blur"]}, "repeat"),
                                 ({"families": "blur"}, "list"),
                                 ({"rewordings": 13}, "rewordings"),
                                 ({"rewordings": -1}, "rewordings"),
                                 ({"enabled": "yes"}, "enabled"),
                                 ({"turbo": 1}, "turbo")):
            with self.subTest(probes=probes):
                data = diagnose_spec()
                data["diagnose"]["probes"] = probes
                self.refused(data, fragment)

    def test_exactly_one_way_to_name_the_start(self):
        data = diagnose_spec()
        data["diagnose"]["import"] = "x.json"
        self.refused(data, "exactly one of start, screen or import")

    def test_the_instruction_is_optional_and_read_from_the_screen_for_unknown_tasks(self):
        data = diagnose_spec(task=3)
        self.assertIsNone(sp.parse_spec(data).paraphrase.instruction)       # the run reads it from the screen
        data["diagnose"]["probes"]["instruction"] = "put the bowl on the plate"
        self.assertEqual(sp.parse_spec(data).paraphrase.instruction, "put the bowl on the plate")
        data["diagnose"]["probes"]["instruction"] = ""
        self.refused(data, "diagnose.probes.instruction")
        data["diagnose"]["probes"]["rewordings"] = 0
        del data["diagnose"]["probes"]["instruction"]
        self.assertIsNone(sp.parse_spec(data).paraphrase)

    def test_reference_and_pool_are_the_scenario_options(self):
        spec = sp.parse_spec(diagnose_spec(reference=5, pool="0-9"))
        self.assertEqual((spec.scenario.reference, spec.scenario.pool_text), (5, "0-9"))
        self.refused(diagnose_spec(reference=0), "diagnose.reference")

    def test_the_template_loads_with_every_default(self):
        spec = sp.load_spec(ROOT / "configs" / "specs" / "diagnose.yaml")
        self.assertEqual(spec.mode, "diagnose")
        self.assertEqual(len(spec.diagnose.probes.families), len(sp.FAMILIES))
        self.assertEqual(spec.diagnose.probes.rewordings, 10)
        self.assertTrue(spec.diagnose.layout and spec.diagnose.probes.enabled)

    def test_research_is_an_optional_boolean_of_the_diagnose_mode_only(self):
        self.assertFalse(sp.parse_spec(diagnose_spec()).research)
        data = diagnose_spec()
        data["research"] = True
        self.assertTrue(sp.parse_spec(data).research)
        data["research"] = "yes"
        self.refused(data, "research")
        other = {"faultline": 1, "name": "a", "mode": "audit", "policy": {"suite": "libero_object"},
                 "audit": {"task": 0, "start": 0, "families": ["blur"]}, "research": True,
                 "budget": {"max_spend_usd": 2.0, "max_hours": 1}, "backend": dict(BACKEND)}
        self.refused(other, "research")

    def test_a_diagnose_spec_needs_its_section_and_a_policy(self):
        data = diagnose_spec()
        del data["diagnose"]
        self.refused(data, "diagnose")
        data = diagnose_spec()
        del data["policy"]
        self.refused(data, "policy")


if __name__ == "__main__":
    unittest.main()
