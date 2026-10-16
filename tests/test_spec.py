"""The faultline spec: exact keys, types and bounds, fail closed."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from robot_debug import spec as sp

ROOT = Path(__file__).parents[1]

BACKEND = {"kind": "nebius", "image": "cr.example.invalid/REGISTRY_ID/faultline@sha256:abc",
           "hf_token_secret": "faultline-hf-token", "hourly_usd": 1.7468}


def scenario_spec(**scenario):
    return {
        "faultline": 1, "name": "soup-start14", "mode": "scenario",
        "policy": {"suite": "libero_10"},
        "scenario": dict({"task": 0, "start": 14, "reference": "auto"}, **scenario),
        "budget": {"max_spend_usd": 3.0, "max_hours": 2, "max_candidates": 36},
        "nemotron": {"hypothesis": True, "explain": True},
        "backend": dict(BACKEND),
    }


def audit_spec():
    return {
        "faultline": 1, "name": "audit-task0", "mode": "audit", "policy": {"suite": "libero_object"},
        "audit": {"task": 0, "start": 0, "families": ["blur", "noise", "darken", "contrast"]},
        "budget": {"max_spend_usd": 2.0, "max_hours": 1},
        "backend": dict(BACKEND),
    }


class ValidSpecs(unittest.TestCase):
    def test_scenario_start_spec(self):
        spec = sp.parse_spec(scenario_spec())
        self.assertEqual(spec.mode, "scenario")
        self.assertEqual(spec.suite, "libero_10")
        self.assertEqual(spec.scenario.start, 14)
        self.assertEqual(spec.scenario.reference, "auto")
        self.assertEqual(spec.budget.max_candidates, 36)
        self.assertTrue(spec.nemotron.explain)
        self.assertEqual(spec.backend.hourly_usd, 1.7468)
        self.assertEqual(spec.backend.platform, "gpu-l40s-a")

    def test_screen_spec_parses_ranges(self):
        data = scenario_spec()
        del data["scenario"]["start"]
        data["scenario"]["screen"] = {"starts": "10-12,20", "confirm": 4}
        spec = sp.parse_spec(data)
        self.assertEqual(spec.scenario.screen_starts, (10, 11, 12, 20))
        self.assertEqual(spec.scenario.confirm, 4)
        self.assertIsNone(spec.scenario.start)

    def test_import_spec(self):
        data = scenario_spec()
        del data["scenario"]["start"]
        data["scenario"]["import"] = "candidate.json"
        self.assertEqual(sp.parse_spec(data).scenario.import_path, "candidate.json")

    def test_audit_spec_and_defaults(self):
        spec = sp.parse_spec(audit_spec())
        self.assertEqual(spec.audit.families, ("blur", "noise", "darken", "contrast"))
        self.assertEqual(spec.budget.max_candidates, sp.DEFAULT_CANDIDATES)
        self.assertFalse(spec.nemotron.hypothesis)
        self.assertFalse(spec.nemotron.explain)

    def test_replay_spec_needs_no_policy_or_scenario(self):
        data = {"faultline": 1, "name": "replay-soup", "mode": "replay",
                "budget": {"max_spend_usd": 1.0, "max_hours": 1}, "backend": dict(BACKEND)}
        spec = sp.parse_spec(data)
        self.assertEqual(spec.mode, "replay")
        self.assertIsNone(spec.suite)

    def test_local_backend_needs_only_an_image(self):
        data = scenario_spec()
        data["backend"] = {"kind": "local", "image": "faultline-serverless:dev"}
        spec = sp.parse_spec(data)
        self.assertEqual(spec.backend.hourly_usd, 0.0)

    def test_pinned_reference_must_be_screened(self):
        data = scenario_spec()
        del data["scenario"]["start"]
        data["scenario"].update(screen={"starts": "10-20"}, reference=28)
        self.assertRaises(sp.SpecError, sp.parse_spec, data)
        data["scenario"]["reference"] = 15
        self.assertEqual(sp.parse_spec(data).scenario.reference, 15)

    def test_example_specs_load(self):
        for name in ("scenario-start.yaml", "scenario-screen.yaml", "scenario-import.yaml", "audit.yaml",
                     "replay.yaml"):
            with self.subTest(name=name):
                spec = sp.load_spec(ROOT / "configs" / "specs" / name)
                self.assertIn(spec.mode, sp.MODES)


class Refusals(unittest.TestCase):
    def assertRefused(self, data, fragment=None):
        with self.assertRaises(sp.SpecError) as caught:
            sp.parse_spec(data)
        if fragment is not None:
            self.assertIn(fragment, str(caught.exception))

    def test_budget_is_required_and_positive(self):
        for key in ("max_spend_usd", "max_hours"):
            data = scenario_spec()
            del data["budget"][key]
            self.assertRefused(data, key)
        for bad in (0, -1, float("nan"), float("inf"), True, "3", None, 10_000):
            data = scenario_spec()
            data["budget"]["max_spend_usd"] = bad
            self.assertRefused(data, "max_spend_usd")
        data = scenario_spec()
        data["budget"]["max_hours"] = 0
        self.assertRefused(data, "max_hours")
        data = scenario_spec()
        del data["budget"]
        self.assertRefused(data, "budget")

    def test_unknown_and_missing_keys(self):
        data = scenario_spec()
        data["extra"] = 1
        self.assertRefused(data, "extra")
        data = scenario_spec()
        data["backend"]["secret_token"] = "x"
        self.assertRefused(data, "secret_token")
        data = scenario_spec()
        del data["policy"]
        self.assertRefused(data, "policy")
        data = scenario_spec()
        del data["backend"]["hf_token_secret"]
        self.assertRefused(data, "hf_token_secret")

    def test_version_name_mode(self):
        for version in (0, 2, "1", True, None):
            data = scenario_spec()
            data["faultline"] = version
            self.assertRefused(data, "faultline")
        for name in ("", "Upper", "-lead", "trail-", "has space", "x" * 41, "a_b", 5):
            data = scenario_spec()
            data["name"] = name
            self.assertRefused(data, "name")
        data = scenario_spec()
        data["name"] = "x" * 40
        sp.parse_spec(data)
        data["mode"] = "banana"
        self.assertRefused(data, "mode")

    def test_wrong_section_for_mode(self):
        data = scenario_spec()
        data["audit"] = audit_spec()["audit"]
        self.assertRefused(data, "audit")
        data = audit_spec()
        data["scenario"] = {"task": 0, "start": 1}
        self.assertRefused(data, "scenario")
        data = scenario_spec()
        del data["scenario"]
        self.assertRefused(data, "scenario")

    def test_suite_task_start_bounds(self):
        data = scenario_spec()
        data["policy"]["suite"] = "libero_90"
        self.assertRefused(data, "suite")
        for task in (-1, 10, True, "0", 1.0):
            data = scenario_spec(task=task)
            self.assertRefused(data, "task")
        for start in (-1, 50, True, "3"):
            self.assertRefused(scenario_spec(start=start), "start")

    def test_scenario_needs_exactly_one_source(self):
        data = scenario_spec()
        data["scenario"]["screen"] = {"starts": "0-9"}
        self.assertRefused(data, "exactly one")
        data = scenario_spec()
        del data["scenario"]["start"]
        self.assertRefused(data, "exactly one")
        data = scenario_spec()
        data["scenario"]["import"] = "x.json"
        self.assertRefused(data, "exactly one")

    def test_screen_bounds(self):
        for starts in ("", "10-", "a-b", "5-2", "0-50", "1,1", "0,-3", 7, None, "10-49,10"):
            data = scenario_spec()
            del data["scenario"]["start"]
            data["scenario"]["screen"] = {"starts": starts}
            self.assertRefused(data, "starts")
        data = scenario_spec()
        del data["scenario"]["start"]
        data["scenario"]["screen"] = {"starts": "0-49", "confirm": 3}
        self.assertRefused(data, "confirm")
        data["scenario"]["screen"] = {"starts": "0-49", "confirm": 9}
        self.assertRefused(data, "confirm")
        data["scenario"]["screen"] = {"starts": "0-49", "confirm": 8}
        self.assertEqual(sp.parse_spec(data).scenario.confirm, 8)

    def test_reference_must_differ_from_start(self):
        self.assertRefused(scenario_spec(reference=14), "reference")
        self.assertRefused(scenario_spec(reference="nearest"), "reference")

    def test_audit_families(self):
        for families in ([], ["blur", "blur"], ["sepia"], "blur", [1]):
            data = audit_spec()
            data["audit"]["families"] = families
            self.assertRefused(data, "families")

    def test_candidates_bounds(self):
        for count in (0, 61, 1.5, True):
            data = scenario_spec()
            data["budget"]["max_candidates"] = count
            self.assertRefused(data, "max_candidates")

    def test_backend_validation(self):
        for patch in ({"kind": "aws"}, {"hourly_usd": 0}, {"hourly_usd": -2}, {"image": "has space"},
                      {"hf_token_secret": "hf_abc def"}, {"project": "somebody"}, {"platform": "A B"}):
            data = scenario_spec()
            data["backend"].update(patch)
            self.assertRefused(data)

    def test_the_optional_backend_keys_the_backends_read_are_accepted(self):
        data = scenario_spec()
        data["backend"].update({
            "region": "eu-north1", "subnet": "vpcsubnet-e00fakesubnet00001", "profile": "work",
            "nebius_executable": ["wsl.exe", "-e", "nebius"], "image_digest": "sha256:" + "ab" * 32,
            "registry": "registry-e00fakeregistry001"})
        spec = sp.parse_spec(data)
        self.assertEqual(spec.raw["backend"]["region"], "eu-north1")
        data["backend"]["nebius_executable"] = "/opt/nebius"
        sp.parse_spec(data)
        local = scenario_spec()
        local["backend"] = {"kind": "local", "image": "faultline-serverless:dev", "docker_executable": "podman"}
        sp.parse_spec(local)

    def test_backend_keys_are_checked_and_belong_to_their_backend(self):
        for patch in ({"region": "EU North"}, {"subnet": "subnet-1"}, {"image_digest": "sha256:123"},
                      {"registry": "reg istry"}, {"profile": "has space"}, {"nebius_executable": []},
                      {"nebius_executable": [1]}, {"nebius_executable": ""}, {"docker_executable": "docker"}):
            with self.subTest(patch=patch):
                data = scenario_spec()
                data["backend"].update(patch)
                self.assertRefused(data)
        local = scenario_spec()
        local["backend"] = {"kind": "local", "image": "faultline-serverless:dev", "region": "eu-north1"}
        self.assertRefused(local)

    def test_nemotron_flags_must_be_bool(self):
        data = scenario_spec()
        data["nemotron"] = {"hypothesis": "yes"}
        self.assertRefused(data, "nemotron.hypothesis")
        data["nemotron"] = {"judge": True}
        self.assertRefused(data, "judge")

    def test_not_a_mapping(self):
        for data in (None, [], "text", 3):
            self.assertRefused(data)


class YamlLoading(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
        self.addCleanup(lambda: Path(handle.name).unlink())
        handle.write(text)
        handle.close()
        return handle.name

    def test_duplicate_keys_are_refused(self):
        text = "faultline: 1\nname: a\nname: b\n"
        with self.assertRaises(sp.SpecError) as caught:
            sp.load_spec(self.write(text))
        self.assertIn("duplicate", str(caught.exception))

    def test_invalid_yaml_and_missing_file(self):
        self.assertRaises(sp.SpecError, sp.load_spec, self.write("a: [unclosed"))
        self.assertRaises(sp.SpecError, sp.load_spec, Path("no-such-spec.yaml"))

    def test_unsafe_yaml_tags_are_refused(self):
        self.assertRaises(sp.SpecError, sp.load_spec, self.write("a: !!python/object/apply:os.system ['x']\n"))

    def test_raw_is_kept_and_not_shared(self):
        data = scenario_spec()
        spec = sp.parse_spec(copy.deepcopy(data))
        self.assertEqual(spec.raw["name"], "soup-start14")


if __name__ == "__main__":
    unittest.main()


class PoolTests(unittest.TestCase):
    def test_import_mode_takes_a_pool_and_a_pinned_reference(self):
        from robot_debug import spec as sp
        scenario = sp._scenario({"task": 0, "import": "f.json"})
        self.assertEqual(("f.json", "0-19", "auto"), (scenario.import_path, scenario.pool_text, scenario.reference))
        scenario = sp._scenario({"task": 0, "import": "f.json", "pool": "20 - 29", "reference": 22})
        self.assertEqual(("20-29", 22), (scenario.pool_text, scenario.reference))
        with self.assertRaises(sp.SpecError):
            sp._scenario({"task": 0, "import": "f.json", "pool": "20-99"})


    def test_start_mode_takes_an_optional_pool(self):
        from robot_debug import spec as sp
        self.assertEqual(sp._scenario({"task": 0, "start": 14}).pool_text, "0-19")
        scenario = sp._scenario({"task": 0, "start": 14, "pool": "20-29"})
        self.assertEqual(scenario.pool_text, "20-29")
        with self.assertRaises(sp.SpecError):
            sp._scenario({"task": 0, "screen": {"starts": "0-9"}, "pool": "0-9"})
