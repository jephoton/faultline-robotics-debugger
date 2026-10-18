"""The setup checklist: each check, caching, and that no secret or id ever leaves it."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import List

from robot_debug.viewer import environment as ev
from robot_debug.viewer.specs import SpecService
from tests.test_ui_specs import FAKE_IMAGE, LOCAL_SPEC

SECRET_VALUE = "FAKE-TOKEN-FACTORY-SECRET-VALUE-123"


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeRunner:
    def __init__(self, returncode=0, stdout="user: someone@example.invalid account-fake0001\n", stderr="", error=None):
        self.calls: List[list] = []
        self.timeouts: List[float] = []
        self.returncode, self.stdout, self.stderr, self.error = returncode, stdout, stderr, error

    def __call__(self, argv, cwd=None, timeout=None):
        self.calls.append(list(argv))
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


class FakeLauncher:
    def argv(self, args, cwd=None):
        return ["nebius"] + list(args)


class EnvironmentCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.artifacts = self.dir / "artifacts"
        self.artifacts.mkdir()
        self.env_file = self.dir / ".env"
        self.runner = FakeRunner()
        self.clock = Clock()

    def make(self, **options):
        specs = SpecService(self.artifacts)
        options.setdefault("env_file", self.env_file)
        options.setdefault("environ", {})
        options.setdefault("runner", self.runner)
        options.setdefault("which", lambda name: "/usr/bin/" + name)
        options.setdefault("launcher_factory", FakeLauncher)
        options.setdefault("clock", self.clock)
        return ev.Environment(specs, **options)

    def checks(self, **options):
        return {c["key"]: c for c in self.make(**options).check()["checks"]}

    def add_local_spec(self):
        path = self.artifacts / "specs-local" / "local.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(LOCAL_SPEC, encoding="utf-8")


class NebiusCliTests(EnvironmentCase):
    def test_signed_in(self):
        check = self.checks()["nebius_cli"]
        self.assertEqual((check["ok"], check["detail"]), (True, "signed in"))
        self.assertNotIn("fix", check)
        self.assertEqual(self.runner.calls, [["nebius", "iam", "whoami"]])
        self.assertEqual(self.runner.timeouts, [20.0])

    def test_the_identity_whoami_prints_is_never_returned(self):
        text = json.dumps(self.make().check())
        self.assertNotIn("someone@example.invalid", text)
        self.assertNotIn("account-fake0001", text)

    def test_not_signed_in(self):
        self.runner = FakeRunner(returncode=1, stderr="Unauthenticated: token expired acct-fake")
        check = self.checks()["nebius_cli"]
        self.assertFalse(check["ok"])
        self.assertIn("not signed in", check["detail"])
        self.assertIn("nebius iam whoami", check["fix"])
        self.assertNotIn("Unauthenticated", json.dumps(check), "raw CLI text does not reach the page")

    def test_a_cli_that_does_not_answer_in_time(self):
        self.runner = FakeRunner(error=subprocess.TimeoutExpired(["nebius"], 20))
        check = self.checks()["nebius_cli"]
        self.assertFalse(check["ok"])
        self.assertIn("20 seconds", check["detail"])

    def test_a_cli_that_cannot_start(self):
        self.runner = FakeRunner(error=FileNotFoundError("nebius"))
        self.assertFalse(self.checks()["nebius_cli"]["ok"])

    def test_a_missing_cli(self):
        from robot_debug.backends import BackendError

        def missing():
            raise BackendError("the nebius CLI was not found")

        check = self.checks(launcher_factory=missing)["nebius_cli"]
        self.assertEqual((check["ok"], check["detail"]), (False, "The nebius CLI was not found."))
        self.assertIn("https://docs.nebius.com/cli", check["fix"])
        self.assertEqual(self.runner.calls, [], "nothing is run when there is no CLI")

    def test_whoami_is_cached_for_sixty_seconds(self):
        environment = self.make()
        environment.check()
        self.clock.now += 59
        environment.check()
        self.assertEqual(len(self.runner.calls), 1)
        self.clock.now += 2
        environment.check()
        self.assertEqual(len(self.runner.calls), 2)


class KeyAndTemplateTests(EnvironmentCase):
    def test_the_token_factory_key_is_found_in_dotenv_and_never_returned(self):
        self.env_file.write_text("# comment\nOTHER=1\nNEBIUS_API_KEY={}\n".format(SECRET_VALUE), encoding="utf-8")
        report = self.make().check()
        check = {c["key"]: c for c in report["checks"]}["token_factory_key"]
        self.assertEqual((check["ok"], check["detail"]), (True, "NEBIUS_API_KEY found"))
        self.assertNotIn(SECRET_VALUE, json.dumps(report))

    def test_forms_of_assignment(self):
        for text, expected in (("NEBIUS_API_KEY=abc", True), ("export NEBIUS_API_KEY='abc'", True),
                               ('NEBIUS_API_KEY = "abc"  # key', True), ("NEBIUS_API_KEY=", False),
                               ('NEBIUS_API_KEY=""', False), ("# NEBIUS_API_KEY=abc", False),
                               ("NEBIUS_API_KEY_OLD=abc", False), ("", False)):
            with self.subTest(text=text):
                self.env_file.write_text(text, encoding="utf-8")
                self.assertEqual(ev.dotenv_has(self.env_file, "NEBIUS_API_KEY"), expected)

    def test_a_missing_key_says_what_to_do(self):
        check = self.checks()["token_factory_key"]
        self.assertEqual((check["ok"], check["detail"]), (False, "NEBIUS_API_KEY not found in .env"))
        self.assertIn(".env", check["fix"])
        self.assertNotIn("<", check["detail"])

    def test_the_key_may_come_from_the_environment(self):
        check = self.checks(environ={"NEBIUS_API_KEY": SECRET_VALUE})["token_factory_key"]
        self.assertTrue(check["ok"])
        self.assertNotIn(SECRET_VALUE, json.dumps(check))

    def test_the_spec_template_reports_names_never_ids(self):
        self.add_local_spec()
        report = self.make().check()
        check = {c["key"]: c for c in report["checks"]}["spec_template"]
        self.assertTrue(check["ok"])
        self.assertEqual(check["detail"], "Pinned image set; Hugging Face secret name: fake-hf-secret")
        text = json.dumps(report)
        for forbidden in ("fakeregistryid0001", "ab" * 32, FAKE_IMAGE):
            self.assertNotIn(forbidden, text)

    def test_without_a_local_spec_it_explains(self):
        check = self.checks()["spec_template"]
        self.assertFalse(check["ok"])
        self.assertIn("specs-local", check["fix"])


class DockerAndShapeTests(EnvironmentCase):
    def test_docker_is_optional(self):
        present = self.checks()["docker"]
        self.assertEqual((present["ok"], present["optional"]), (True, True))
        absent = self.checks(which=lambda name: None)["docker"]
        self.assertEqual((absent["ok"], absent["optional"]), (False, True))
        self.assertIn("simulator image", absent["fix"])

    def test_the_report_shape(self):
        report = self.make().check()
        self.assertEqual(list(report), ["checks"])
        self.assertEqual([c["key"] for c in report["checks"]], ["nebius_cli", "token_factory_key", "spec_template", "docker", "tavily_key"])
        for check in report["checks"]:
            self.assertTrue({"key", "ok", "detail"} <= set(check))
            self.assertIsInstance(check["ok"], bool)
            if not check["ok"]:
                self.assertTrue(check["fix"])


if __name__ == "__main__":
    unittest.main()
