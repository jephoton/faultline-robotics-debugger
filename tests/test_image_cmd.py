"""Tests for the faultline image build and push helpers, using a fake docker."""

from __future__ import annotations

import subprocess
import unittest

from robot_debug import image_cmd
from robot_debug.image_cmd import ImageCommandError, build, push

IMAGE_ID = "sha256:" + "1" * 64
DIGEST = "sha256:" + "ab" * 32
PUSH_OUTPUT = (
    "The push refers to repository [cr.eu-north1.nebius.cloud/reg/faultline-serverless]\n"
    "5f70bf18a086: Pushed\n"
    "abc1234: digest: " + DIGEST + " size: 2412\n")


class FakeDocker:
    def __init__(self, *, build_code=0, push_code=0, push_output=PUSH_OUTPUT, sha="abc1234"):
        self.calls = []
        self.codes = {"build": build_code, "push": push_code}
        self.push_output = push_output
        self.sha = sha

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        self.assert_safe(argv, kwargs)
        if argv[0] == "git":
            code = 0 if self.sha else 128
            return subprocess.CompletedProcess(argv, code, (self.sha or "") + "\n", "")
        action = argv[1]
        if action == "build":
            return subprocess.CompletedProcess(argv, self.codes["build"], "built\n", "boom" if self.codes["build"] else "")
        if action == "image":
            return subprocess.CompletedProcess(argv, 0, IMAGE_ID + "\n", "")
        if action == "tag":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if action == "push":
            return subprocess.CompletedProcess(argv, self.codes["push"], self.push_output,
                                               "denied" if self.codes["push"] else "")
        raise AssertionError(argv)

    @staticmethod
    def assert_safe(argv, kwargs):
        assert isinstance(argv, list) and all(isinstance(item, str) for item in argv)
        assert not kwargs.get("shell")

    def docker_calls(self):
        return [argv for argv, _ in self.calls if argv[0] == "docker"]


class BuildTests(unittest.TestCase):
    def test_build_runs_docker_build_and_returns_the_image_id(self):
        fake = FakeDocker()
        self.assertEqual(IMAGE_ID, build("faultline-serverless:dev", run=fake))
        first = fake.docker_calls()[0]
        self.assertEqual(["docker", "build", "--file", "deploy/serverless/Dockerfile",
                          "--tag", "faultline-serverless:dev", "."], first)
        self.assertEqual(["docker", "image", "inspect", "--format", "{{.Id}}", "faultline-serverless:dev"],
                         fake.docker_calls()[1])

    def test_a_custom_dockerfile_and_context(self):
        fake = FakeDocker()
        build("t:1", "other/Dockerfile", context="ctx", run=fake)
        self.assertEqual(["docker", "build", "--file", "other/Dockerfile", "--tag", "t:1", "ctx"],
                         fake.docker_calls()[0])

    def test_a_failed_build_is_an_error(self):
        with self.assertRaisesRegex(ImageCommandError, "docker build failed"):
            build("t:1", run=FakeDocker(build_code=1))

    def test_missing_docker_is_an_error(self):
        def missing(argv, **kwargs):
            raise FileNotFoundError("docker")

        with self.assertRaisesRegex(ImageCommandError, "docker"):
            build("t:1", run=missing)

    def test_bad_tags_and_paths_are_refused_before_running_anything(self):
        fake = FakeDocker()
        for tag in ("", "-bad", "has space", "a;b", "a" * 300, "x\ny"):
            with self.subTest(tag=tag), self.assertRaises(ImageCommandError):
                build(tag, run=fake)
        with self.assertRaises(ImageCommandError):
            build("t:1", "--evil", run=fake)
        self.assertEqual([], fake.calls)


class PushTests(unittest.TestCase):
    REGISTRY = "cr.eu-north1.nebius.cloud/reg"

    def test_push_tags_with_the_git_short_sha_and_returns_the_digest_reference(self):
        fake = FakeDocker()
        reference = push("faultline-serverless:dev", self.REGISTRY, run=fake)
        self.assertEqual("cr.eu-north1.nebius.cloud/reg/faultline-serverless@" + DIGEST, reference)
        remote = "cr.eu-north1.nebius.cloud/reg/faultline-serverless:abc1234"
        self.assertEqual(["git", "rev-parse", "--short", "HEAD"], fake.calls[0][0])
        self.assertEqual(["docker", "tag", "faultline-serverless:dev", remote], fake.docker_calls()[0])
        self.assertEqual(["docker", "push", remote], fake.docker_calls()[1])

    def test_an_explicit_revision_skips_git(self):
        fake = FakeDocker()
        push("t:1", self.REGISTRY, revision="deadbee", run=fake)
        self.assertNotIn("git", [argv[0] for argv, _ in fake.calls])
        self.assertEqual("cr.eu-north1.nebius.cloud/reg/faultline-serverless:deadbee",
                         fake.docker_calls()[0][3])

    def test_a_failed_push_is_an_error(self):
        with self.assertRaisesRegex(ImageCommandError, "docker push failed"):
            push("t:1", self.REGISTRY, run=FakeDocker(push_code=1))

    def test_output_without_a_digest_is_an_error(self):
        with self.assertRaisesRegex(ImageCommandError, "digest"):
            push("t:1", self.REGISTRY, run=FakeDocker(push_output="Pushed\n"))

    def test_without_a_git_revision_it_asks_for_one(self):
        with self.assertRaisesRegex(ImageCommandError, "revision"):
            push("t:1", self.REGISTRY, run=FakeDocker(sha=""))

    def test_public_registries_are_refused(self):
        fake = FakeDocker()
        for registry in ("ghcr.io/someone", "docker.io/someone", "someone", "index.docker.io/x",
                         "registry-1.docker.io/x", "quay.io/x", "public.ecr.aws/x", "GHCR.IO/x"):
            with self.subTest(registry=registry), self.assertRaisesRegex(ImageCommandError, "public|registry"):
                push("t:1", registry, run=fake)
        self.assertEqual([], fake.calls)

    def test_malformed_registries_are_refused(self):
        fake = FakeDocker()
        for registry in ("", "-x.example/r", "reg.example/a b", "https://reg.example/r", "reg.example/r;rm",
                         "reg.example/", "reg.example//r", "reg.example/R"):
            with self.subTest(registry=registry), self.assertRaises(ImageCommandError):
                push("t:1", registry, run=fake)
        self.assertEqual([], fake.calls)

    def test_a_private_registry_with_a_port_is_accepted(self):
        reference = push("t:1", "localhost:5000/team", revision="abc1234", run=FakeDocker())
        self.assertTrue(reference.startswith("localhost:5000/team/faultline-serverless@sha256:"))

    def test_no_secret_or_path_appears_in_error_messages(self):
        try:
            push("t:1", self.REGISTRY, run=FakeDocker(push_code=1))
        except ImageCommandError as error:
            self.assertNotIn("\\", str(error))


class ModuleTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual("faultline-serverless", image_cmd.IMAGE_NAME)
        self.assertEqual("deploy/serverless/Dockerfile", image_cmd.DEFAULT_DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
