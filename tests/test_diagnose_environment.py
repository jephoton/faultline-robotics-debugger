"""The optional Tavily key check: presence only, never the value."""

from __future__ import annotations

import json

from tests.test_ui_environment import EnvironmentCase

KEY = "tvly-FAKEFAKEFAKE0001"


class TavilyCheck(EnvironmentCase):
    def check(self, **options):
        report = self.make(**options).check()
        return {c["key"]: c for c in report["checks"]}["tavily_key"], report

    def test_a_missing_key_is_optional_and_says_what_to_do(self):
        check, _report = self.check()
        self.assertEqual((check["ok"], check["optional"], check["detail"]),
                         (False, True, "TAVILY_API_KEY not found in .env"))
        self.assertIn("skipped", check["fix"])

    def test_the_key_in_dotenv_is_found_and_never_returned(self):
        self.env_file.write_text("TAVILY_API_KEY={}\n".format(KEY), encoding="utf-8")
        check, report = self.check()
        self.assertEqual((check["ok"], check["detail"]), (True, "TAVILY_API_KEY found"))
        self.assertNotIn(KEY, json.dumps(report))
        self.assertNotIn("fix", check)

    def test_the_key_may_come_from_the_environment(self):
        check, report = self.check(environ={"TAVILY_API_KEY": KEY})
        self.assertTrue(check["ok"])
        self.assertNotIn(KEY, json.dumps(report))

    def test_an_empty_assignment_does_not_count(self):
        self.env_file.write_text("TAVILY_API_KEY=\n", encoding="utf-8")
        self.assertFalse(self.check()[0]["ok"])
