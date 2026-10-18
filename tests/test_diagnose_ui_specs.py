"""The diagnose mode in the control panel's spec service: template, validation, imported start files."""

from __future__ import annotations

import yaml

from robot_debug import spec as sp
from tests.test_ui_specs import ServiceCase, candidate_text


def template_mapping(service):
    return yaml.safe_load(service.template("diagnose")["yaml"])


class DiagnoseTemplate(ServiceCase):
    def test_the_template_validates_with_the_four_default_families(self):
        text = self.service.template("diagnose")["yaml"]
        result = self.service.validate(text)
        self.assertTrue(result["ok"], result["errors"])
        summary = result["summary"]
        self.assertEqual((summary["mode"], summary["needs_import"], summary["uses_nemotron"]),
                         ("diagnose", False, True))
        mapping = yaml.safe_load(text)
        self.assertEqual(mapping["diagnose"]["probes"]["families"], ["blur", "noise", "darken", "contrast"])
        self.assertIs(mapping["research"], True)
        self.assertEqual(mapping["diagnose"]["probes"]["rewordings"], 0)

    def test_validation_errors_name_the_diagnose_paths(self):
        mapping = template_mapping(self.service)
        mapping["diagnose"]["probes"]["families"] = ["blur", "sparkle"]
        result = self.service.validate(yaml.safe_dump(mapping))
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["path"], "diagnose.probes.families")
        mapping = template_mapping(self.service)
        del mapping["diagnose"]["start"]
        mapping["diagnose"]["screen"] = {"starts": "10-19"}
        result = self.service.validate(yaml.safe_dump(mapping))
        self.assertEqual(result["errors"][0]["path"], "diagnose.probes")
        self.assertIn("only", result["errors"][0]["message"])

    def test_a_probe_only_spec_without_probes_is_refused(self):
        mapping = template_mapping(self.service)
        mapping["diagnose"]["layout"] = False
        mapping["diagnose"]["probes"]["enabled"] = False
        result = self.service.validate(yaml.safe_dump(mapping))
        self.assertEqual(result["errors"][0]["path"], "diagnose.layout")


class DiagnoseImport(ServiceCase):
    def spec_text(self):
        mapping = template_mapping(self.service)
        del mapping["diagnose"]["start"]
        mapping["diagnose"]["import"] = "start.json"
        mapping["diagnose"]["probes"] = {"enabled": False}
        mapping["policy"]["suite"] = "libero_10"
        return yaml.safe_dump(mapping, sort_keys=False)

    def test_an_imported_start_is_needed_and_travels_with_the_request(self):
        text = self.spec_text()
        self.assertTrue(self.service.validate(text)["summary"]["needs_import"])
        with self.assertRaises(Exception) as caught:
            self.service.prepare(text)
        self.assertEqual(caught.exception.errors[0]["path"], "diagnose.import")
        prepared = self.service.prepare(text, {"name": "start.json", "content": candidate_text()})
        self.assertIsNotNone(prepared.import_sha256)
        self.assertIn("sha256:" + prepared.import_sha256, prepared.canonical())

    def test_the_saved_spec_names_the_saved_import_file(self):
        prepared = self.service.prepare(self.spec_text(), {"name": "start.json", "content": candidate_text()})
        directory, spec_path = self.service.persist(prepared)
        saved = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        self.assertTrue(saved["diagnose"]["import"].endswith("import.json"))
        self.assertTrue((directory / "import.json").is_file())
        self.assertEqual(sp.load_spec(spec_path).scenario.import_path, saved["diagnose"]["import"])
