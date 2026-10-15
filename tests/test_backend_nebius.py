import base64
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from robot_debug.backends import Backend, BackendError, JobHandle, make_backend
from robot_debug.backends.nebius import (
    Launcher,
    NebiusBackend,
    NebiusCli,
    parse_time,
    resolve_launcher,
    to_wsl_path,
)
from tests.fakes.backend_fakes import FakeClock, completed
from tests.fakes.fake_nebius import (
    DIGEST,
    IMAGE,
    IMAGE_NAME,
    PROJECT,
    SECRET,
    SUBNET,
    TAG,
    TENANT,
    FakeNebius,
    FakeS3,
    iso,
)


class NebiusCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run_dir = Path(self.temp.name) / "run"
        self.clock = FakeClock()
        self.cli = FakeNebius(self.clock)
        self.s3_calls = []
        self.s3 = FakeS3({})

    def s3_factory(self, endpoint, region, key_id, secret):
        self.s3_calls.append((endpoint, region, key_id, secret))
        return self.s3

    def make(self, run_dir=None, **overrides):
        kwargs = dict(
            project="from-cli-profile", platform="gpu-l40s-a", preset="1gpu-16vcpu-64gb",
            image=IMAGE, hf_token_secret="faultline-hf-token", hourly_usd=1.7468,
            executable=["nebius"], runner=self.cli, s3_factory=self.s3_factory,
            clock=self.clock, sleep=self.clock.sleep, suffix=lambda: "abc123",
        )
        kwargs.update(overrides)
        backend = NebiusBackend(**kwargs)
        backend._test_dir = Path(run_dir or self.run_dir)
        return backend

    def prepared(self, **overrides):
        backend = self.make(**overrides)
        backend.prepare(backend._test_dir, {"name": "soup-start14"})
        return backend

    def workload(self, name="soup-a"):
        return {"schema_version": 1, "mode": "pilot", "run_id": name, "deadline_seconds": 1800}


class LauncherTests(unittest.TestCase):
    def test_explicit_setting_wins(self):
        launcher = resolve_launcher("/opt/bin/nebius", which=lambda n: "/usr/bin/" + n, system=lambda: "Linux")
        self.assertEqual(launcher.argv(["iam", "x"]), ["/opt/bin/nebius", "iam", "x"])

    def test_path_lookup(self):
        launcher = resolve_launcher(None, which=lambda n: "/usr/bin/nebius", system=lambda: "Linux")
        self.assertEqual(launcher.argv(["a"]), ["/usr/bin/nebius", "a"])

    def test_windows_falls_back_to_wsl_and_encodes_the_command(self):
        launcher = resolve_launcher(
            None, which=lambda n: "wsl.exe" if n == "wsl.exe" else None, system=lambda: "Windows")
        self.assertTrue(launcher.wsl)
        policy = '[{"group_id":"g","paths":["*"]}]'
        argv = launcher.argv(["storage", "bucket", "create", "--bucket-policy-rules", policy],
                             Path("C:/Users/someone/run dir"))
        self.assertEqual(argv[:4], ["wsl.exe", "-e", "bash", "-lc"])
        encoded = re.fullmatch(r"echo ([A-Za-z0-9+/=]+)\|base64 -d\|bash", argv[4]).group(1)
        script = base64.b64decode(encoded).decode("utf-8")
        self.assertIn("cd '/mnt/c/Users/someone/run dir' && $HOME/.nebius/bin/nebius storage bucket create", script)
        self.assertIn("'" + policy + "'", script)

    def test_wsl_setting_forces_wsl(self):
        launcher = resolve_launcher("wsl", which=lambda n: None, system=lambda: "Linux")
        self.assertTrue(launcher.wsl)

    def test_missing_cli_is_a_clear_error(self):
        with self.assertRaises(BackendError) as caught:
            resolve_launcher(None, which=lambda n: None, system=lambda: "Linux")
        self.assertIn("nebius CLI", str(caught.exception))

    def test_wsl_path_conversion(self):
        self.assertEqual(to_wsl_path(Path("C:\\a\\b c")), "/mnt/c/a/b c")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()

    def cli(self, runner):
        return NebiusCli(Launcher(["nebius"]), runner, self.clock.sleep)

    def test_transient_errors_retry_then_succeed(self):
        answers = [completed([], 1, "", "rpc error: code = Unavailable"),
                   completed([], 1, "", "dial tcp: i/o timeout"),
                   completed([], 0, "{\"ok\": true}", "")]
        cli = self.cli(lambda argv, cwd=None, timeout=None: answers.pop(0))
        self.assertEqual(cli.json(["x", "y"]), {"ok": True})
        self.assertEqual(len(self.clock.sleeps), 2)

    def test_transient_gives_up_after_three_tries_with_a_clear_message(self):
        calls = []

        def runner(argv, cwd=None, timeout=None):
            calls.append(argv)
            return completed(argv, 1, "", "TLS handshake timeout")

        with self.assertRaises(BackendError) as caught:
            self.cli(runner).text(["ai", "job", "get", "aijob-e00fakejob00000001", "--format", "json"])
        self.assertEqual(len(calls), 3)
        self.assertIn("nebius ai job get failed", str(caught.exception))
        self.assertNotIn("3wmt53", str(caught.exception))

    def test_non_transient_error_is_not_retried_and_is_redacted(self):
        calls = []

        def runner(argv, cwd=None, timeout=None):
            calls.append(argv)
            return completed(argv, 1, "", "PermissionDenied: no access to tenant-e00faketenant0001")

        with self.assertRaises(BackendError) as caught:
            self.cli(runner).text(["iam", "group", "list"])
        self.assertEqual(len(calls), 1)
        self.assertIn("tenant-e00f...", str(caught.exception))
        self.assertNotIn("faketenant0001", str(caught.exception))

    def test_timeout_counts_as_transient(self):
        import subprocess
        attempts = []

        def runner(argv, cwd=None, timeout=None):
            attempts.append(timeout)
            raise subprocess.TimeoutExpired(argv, timeout)

        with self.assertRaises(BackendError):
            self.cli(runner).text(["ai", "job", "get", "x"])
        self.assertEqual(attempts, [60.0, 60.0, 60.0])

    def test_profile_is_passed_as_a_global_flag(self):
        seen = []
        cli = NebiusCli(Launcher(["nebius"]), lambda argv, cwd=None, timeout=None: (
            seen.append(argv) or completed(argv, 0, "{}", "")), self.clock.sleep, profile="work")
        cli.text(["config", "get", "parent-id"])
        self.assertEqual(seen[0], ["nebius", "--profile", "work", "config", "get", "parent-id"])


class SpecTests(NebiusCase):
    def test_make_backend_builds_from_spec(self):
        backend = make_backend({"name": "x", "backend": {
            "kind": "nebius", "platform": "gpu-l40s-a", "preset": "1gpu-16vcpu-64gb",
            "image": IMAGE, "hf_token_secret": "faultline-hf-token", "hourly_usd": 1.7468,
            "nebius_executable": "/opt/nebius"}})
        self.assertEqual(backend.kind, "nebius")
        self.assertIsInstance(backend, Backend)
        self.assertEqual(backend.price_per_hour(), 1.7468)

    def test_platform_preset_and_region_default_like_the_spec_does(self):
        minimal = {"kind": "nebius", "image": IMAGE, "hf_token_secret": "faultline-hf-token", "hourly_usd": 1.7,
                   "nebius_executable": "/opt/nebius"}
        backend = NebiusBackend.from_spec({"backend": minimal})
        self.assertEqual((backend.platform, backend.preset, backend.region),
                         ("gpu-l40s-a", "1gpu-16vcpu-64gb", "eu-north1"))

    def test_region_is_derived_from_the_image_host_unless_given(self):
        image = IMAGE.replace("cr.eu-north1.", "cr.us-central1.")
        base = {"kind": "nebius", "image": image, "hf_token_secret": "faultline-hf-token", "hourly_usd": 1.7,
                "nebius_executable": "/opt/nebius"}
        self.assertEqual(NebiusBackend.from_spec({"backend": base}).region, "us-central1")
        self.assertEqual(NebiusBackend.from_spec({"backend": dict(base, region="eu-west1")}).region, "eu-west1")

    def test_missing_fields_are_reported(self):
        with self.assertRaises(BackendError):
            NebiusBackend.from_spec({"backend": {"kind": "nebius"}})

    def test_image_must_be_pinned(self):
        with self.assertRaises(BackendError):
            self.make(image=IMAGE_NAME + ":latest")
        with self.assertRaises(BackendError):
            self.make(image=IMAGE_NAME)
        with self.assertRaises(BackendError):
            self.make(image=IMAGE_NAME + "@sha256:123")

    def test_tag_with_digest_setting_is_accepted(self):
        backend = self.make(image=IMAGE_NAME + ":" + TAG, image_digest=DIGEST)
        self.assertEqual(backend.price_per_hour(), 1.7468)

    def test_hourly_price_and_project_are_validated(self):
        with self.assertRaises(BackendError):
            self.make(hourly_usd=0)
        with self.assertRaises(BackendError):
            self.make(project="not-a-project")

    def test_parse_time_handles_nanoseconds_and_zero_values(self):
        self.assertEqual(parse_time("2026-10-13T11:14:18.627941123Z"), parse_time("2026-10-13T11:14:18.627941Z"))
        self.assertIsNone(parse_time("0001-01-01T00:00:00Z"))
        self.assertIsNone(parse_time(None))


class PrepareTests(NebiusCase):
    def test_creates_identity_bucket_and_key_with_the_proven_commands(self):
        backend = self.prepared()
        self.assertEqual(self.cli.groups.keys(), {"faultline-readers"})
        self.assertEqual(self.cli.service_accounts.keys(), {"faultline-reader"})
        self.assertEqual(len(self.cli.memberships), 1)
        self.assertEqual(list(self.cli.buckets), ["faultline-soup-start14-abc123"])
        bucket = self.cli.buckets["faultline-soup-start14-abc123"]
        self.assertEqual(bucket["max_size"], str(5 * 1024 ** 3))
        group_id = self.cli.groups["faultline-readers"]
        self.assertEqual(bucket["policy"], [{"group_id": group_id, "paths": ["*"], "roles": ["storage.viewer"]}])
        rule = bucket["lifecycle"][0]
        self.assertEqual(rule["expiration"], {"days": 1})
        self.assertEqual(rule["abort_incomplete_multipart_upload"], {"days_after_initiation": 1})
        self.assertEqual(len(self.cli.keys), 1)
        self.assertIn(["iam", "project", "get", PROJECT, "--format", "json"], self.cli.calls)
        self.assertIn(["iam", "group", "create", "--parent-id", TENANT, "--name", "faultline-readers",
                       "--format", "json"], self.cli.calls)
        self.assertTrue(backend._state["access_key_id"].startswith("accesskey-"))

    def test_state_file_holds_ids_only_and_never_the_secret(self):
        self.prepared()
        text = (self.run_dir / "backend-state.json").read_text(encoding="utf-8")
        state = json.loads(text)
        for key in ("project_id", "tenant_id", "group_id", "service_account_id", "bucket_id",
                    "bucket_name", "access_key_id", "subnet_id", "hf_secret_id", "image_tag"):
            self.assertIn(key, state)
        self.assertNotIn(self.cli.secret_value, text)
        self.assertNotIn("secret\"", text)
        self.assertEqual(state["hf_secret_id"], SECRET)
        self.assertEqual(state["subnet_id"], SUBNET)

    def test_project_comes_from_the_cli_profile_unless_given(self):
        self.prepared()
        self.assertIn(["config", "get", "parent-id"], self.cli.calls)
        other = Path(self.temp.name) / "run2"
        self.cli.calls.clear()
        self.prepared(run_dir=other, project="project-e00fakeexplicit001")
        self.assertNotIn(["config", "get", "parent-id"], self.cli.calls)

    def test_missing_profile_project_is_a_clear_error(self):
        self.cli.project_output = "\n"
        with self.assertRaises(BackendError) as caught:
            self.prepared()
        self.assertIn("project", str(caught.exception))
        self.assertEqual(self.cli.buckets, {})

    def test_identity_is_reused_across_diagnoses(self):
        self.prepared()
        second = Path(self.temp.name) / "run2"
        self.prepared(run_dir=second, suffix=lambda: "zzz999")
        self.assertEqual(len(self.cli.groups), 1)
        self.assertEqual(len(self.cli.service_accounts), 1)
        self.assertEqual(len(self.cli.memberships), 1)
        self.assertEqual(len(self.cli.buckets), 2)
        self.assertEqual(self.cli.count("iam", "group", "create"), 1)
        self.assertEqual(self.cli.count("iam", "group-membership", "create"), 1)

    def test_resume_reuses_the_bucket_and_key(self):
        first = self.prepared()
        bucket_id, key_id = first._state["bucket_id"], first._state["access_key_id"]
        creates = self.cli.count("storage", "bucket", "create"), self.cli.count("iam", "v2", "access-key", "create")
        resumed = self.prepared()
        self.assertEqual(resumed._state["bucket_id"], bucket_id)
        self.assertEqual(resumed._state["access_key_id"], key_id)
        self.assertEqual((self.cli.count("storage", "bucket", "create"),
                          self.cli.count("iam", "v2", "access-key", "create")), creates)

    def test_resume_after_finish_creates_a_fresh_key(self):
        first = self.prepared()
        old = first._state["access_key_id"]
        first.finish()
        resumed = self.prepared()
        self.assertNotEqual(resumed._state["access_key_id"], old)
        self.assertEqual(len(self.cli.keys), 1)

    def test_membership_already_exists_is_tolerated(self):
        self.cli.fail(("iam", "group-membership", "list-members"), "Unimplemented: unknown command")
        self.cli.groups["faultline-readers"] = "group-e00existing000001"
        self.cli.service_accounts["faultline-reader"] = "serviceaccount-e00existing01"
        self.cli.memberships.append(("group-e00existing000001", "serviceaccount-e00existing01", "gm-1"))
        self.prepared()
        self.assertEqual(len(self.cli.memberships), 1)

    def test_bucket_create_that_collides_recovers_by_name(self):
        self.cli.buckets["faultline-soup-start14-abc123"] = {
            "id": "storagebucket-e00preexisting001", "max_size": "1", "policy": [], "lifecycle": []}
        backend = self.prepared()
        self.assertEqual(backend._state["bucket_id"], "storagebucket-e00preexisting001")

    def test_missing_hf_secret_fails_before_anything_is_created(self):
        self.cli.secrets.clear()
        with self.assertRaises(BackendError) as caught:
            self.prepared()
        self.assertIn("faultline-hf-token", str(caught.exception))
        self.assertEqual((self.cli.groups, self.cli.buckets, self.cli.keys), ({}, {}, {}))

    def test_unpushed_digest_fails_before_anything_is_created(self):
        self.cli.registry_images = [{"digest": "sha256:" + "cd" * 32, "tags": ["other"]}]
        with self.assertRaises(BackendError) as caught:
            self.prepared()
        self.assertIn("no registry tag", str(caught.exception))
        self.assertEqual(self.cli.buckets, {})

    def test_subnet_is_found_or_given(self):
        self.cli.subnets = []
        with self.assertRaises(BackendError):
            self.prepared()
        backend = self.prepared(subnet="vpcsubnet-e00fakegiven000001")
        self.assertEqual(backend._state["subnet_id"], "vpcsubnet-e00fakegiven000001")

    def test_transient_errors_during_prepare_are_retried(self):
        self.cli.fail(("storage", "bucket", "create"), "rpc error: code = Unavailable", times=2)
        backend = self.prepared()
        self.assertIn("bucket_id", backend._state)

    def test_submit_before_prepare_fails(self):
        with self.assertRaises(BackendError):
            self.make().submit("soup-a", self.workload())


class SubmitTests(NebiusCase):
    def test_dry_run_comes_first_then_the_real_create_without_dry_run(self):
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        creates = [c for c in self.cli.calls if c[:3] == ["ai", "job", "create"]]
        self.assertEqual(len(creates), 2)
        self.assertEqual(creates[0][-2:], ["--dry-run", "--async"])
        self.assertNotIn("--dry-run", creates[1])
        self.assertEqual(creates[1][-3:], ["--async", "--format", "json"])
        self.assertEqual(handle.job_name, "soup-a")
        self.assertTrue(handle.job_id.startswith("aijob-"))

    def test_job_command_uses_tag_digest_bucket_secret_and_workload(self):
        backend = self.prepared()
        backend.submit("soup-a", self.workload())
        args = self.cli.jobs["soup-a"]["args"]

        def value(flag):
            return args[args.index(flag) + 1]

        self.assertEqual(value("--image"), IMAGE_NAME + ":" + TAG)
        self.assertEqual(value("--name"), "soup-a")
        self.assertEqual(value("--parent-id"), PROJECT)
        self.assertEqual(value("--subnet-id"), SUBNET)
        self.assertEqual(value("--env-secret"), "HF_TOKEN=" + SECRET)
        self.assertEqual(value("--volume"), backend._state["bucket_id"] + ":/persistent:rw")
        self.assertEqual(value("--inject-file"), "workload.json:/etc/faultline/workload.json")
        written = json.loads((self.run_dir / "jobs" / "soup-a" / "workload.json").read_text(encoding="utf-8"))
        self.assertEqual(written["run_id"], "soup-a")

    def test_the_provider_timeout_is_the_deadline_plus_the_grace_in_whole_minutes(self):
        backend = self.prepared()
        backend.submit("soup-a", self.workload())                   # deadline_seconds 1800
        args = self.cli.jobs["soup-a"]["args"]
        self.assertEqual(args[args.index("--timeout") + 1], "40m")
        config = json.loads((self.run_dir / "jobs" / "soup-a" / "job-config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["timeout_seconds"], 2400)

    def test_job_id_text_output_is_parsed_without_another_call(self):
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())          # the fake prints "Job ID: aijob-e00fake..."
        self.assertEqual(handle.job_id, self.cli.jobs["soup-a"]["id"])
        self.assertEqual(self.cli.count("ai", "job", "get-by-name"), 0)
        self.assertEqual(len(self.real_creates()), 1)

    def real_creates(self):
        return [c for c in self.cli.calls if c[:3] == ["ai", "job", "create"] and "--dry-run" not in c]

    def silence_create_output(self, text="created"):
        real_call = self.cli.__call__

        def quiet(argv, cwd=None, timeout=None):
            result = real_call(argv, cwd=cwd, timeout=timeout)
            if "--dry-run" not in argv and list(argv[1:4]) == ["ai", "job", "create"]:
                return completed(argv, 0, text, "")
            return result

        return quiet

    def test_unparseable_create_output_never_creates_again_and_finds_the_job_by_name(self):
        backend = self.prepared()
        backend._cli._runner = self.silence_create_output()
        handle = backend.submit("soup-a", self.workload())
        self.assertEqual(handle.job_id, self.cli.jobs["soup-a"]["id"])
        self.assertEqual(len(self.real_creates()), 1)
        self.assertEqual(self.cli.count("ai", "job", "get-by-name"), 1)

    def test_a_job_that_cannot_be_found_after_an_exit_0_create_is_an_error_not_a_second_create(self):
        backend = self.prepared()
        real_call = self.cli.__call__

        def create_without_effect(argv, cwd=None, timeout=None):
            if "--dry-run" not in argv and list(argv[1:4]) == ["ai", "job", "create"]:
                self.cli.calls.append(list(argv[1:]))
                return completed(argv, 0, "ok", "")
            return real_call(argv, cwd=cwd, timeout=timeout)

        backend._cli._runner = create_without_effect
        with self.assertRaises(BackendError) as caught:
            backend.submit("soup-a", self.workload())
        self.assertIn("could not be found by name", str(caught.exception))
        self.assertEqual(len(self.real_creates()), 1)
        lookups = self.cli.count("ai", "job", "get-by-name")
        self.assertTrue(1 < lookups <= 6, lookups)

    def test_transient_lookup_errors_after_an_exit_0_create_are_retried_without_creating_again(self):
        backend = self.prepared()
        backend._cli._runner = self.silence_create_output()
        self.cli.fail(("ai", "job", "get-by-name"), "Unavailable: try later", times=4)
        handle = backend.submit("soup-a", self.workload())
        self.assertEqual(handle.job_id, self.cli.jobs["soup-a"]["id"])
        self.assertEqual(len(self.real_creates()), 1)

    def test_json_create_output_is_used_directly(self):
        self.cli.json_create = True
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        self.assertEqual(handle.job_id, self.cli.jobs["soup-a"]["id"])
        self.assertEqual(self.cli.count("ai", "job", "get-by-name"), 0)

    def test_lost_create_response_is_recovered_without_resubmitting(self):
        backend = self.prepared()
        real_call = self.cli.__call__

        def lose_response(argv, cwd=None, timeout=None):
            result = real_call(argv, cwd=cwd, timeout=timeout)
            if "--dry-run" not in argv and list(argv[1:4]) == ["ai", "job", "create"]:
                return completed(argv, 1, "", "rpc error: code = Unavailable desc = connection reset")
            return result

        backend._cli._runner = lose_response
        handle = backend.submit("soup-a", self.workload())
        self.assertEqual(handle.job_id, self.cli.jobs["soup-a"]["id"])
        real_creates = [c for c in self.cli.calls if c[:3] == ["ai", "job", "create"] and "--dry-run" not in c]
        self.assertEqual(len(real_creates), 1)

    def test_transient_failure_before_creation_retries_the_create(self):
        backend = self.prepared()
        self.cli.fail(("ai", "job", "create", "--parent-id"), "Unavailable: try later", times=1)
        # the dry run consumes the scripted failure's retry budget, the real create succeeds
        handle = backend.submit("soup-a", self.workload())
        self.assertIn("soup-a", self.cli.jobs)
        self.assertIsNotNone(handle.job_id)

    def test_known_job_is_never_submitted_twice(self):
        backend = self.prepared()
        first = backend.submit("soup-a", self.workload())
        again = backend.submit("soup-a", self.workload())
        self.assertEqual(first, again)
        real = [c for c in self.cli.calls if c[:3] == ["ai", "job", "create"] and "--dry-run" not in c]
        self.assertEqual(len(real), 1)

    def test_fresh_backend_instance_also_sees_the_saved_job(self):
        first = self.prepared().submit("soup-a", self.workload())
        again = self.prepared().submit("soup-a", self.workload())
        self.assertEqual(first, again)

    def test_run_id_must_match_and_names_are_checked(self):
        backend = self.prepared()
        with self.assertRaises(BackendError):
            backend.submit("soup-a", self.workload("other"))
        with self.assertRaises(BackendError):
            backend.submit("Bad Name", self.workload("Bad Name"))

    def test_moved_tag_is_refused_at_submit_time(self):
        backend = self.prepared()
        self.cli.registry_images = [{"digest": "sha256:" + "cd" * 32, "tags": [TAG]}]
        with self.assertRaises(BackendError):
            backend.submit("soup-a", self.workload())
        self.assertEqual(self.cli.jobs, {})

    def test_script_rejection_is_a_backend_error_and_creates_nothing(self):
        backend = self.prepared(platform="gpu-h100")
        with self.assertRaises(BackendError) as caught:
            backend.submit("soup-a", self.workload())
        self.assertIn("platform", str(caught.exception))
        self.assertEqual(self.cli.jobs, {})

    def test_failing_dry_run_stops_before_the_real_create(self):
        backend = self.prepared()
        self.cli.fail(("ai", "job", "create"), "InvalidArgument: bad flag")
        with self.assertRaises(BackendError):
            backend.submit("soup-a", self.workload())
        self.assertEqual(self.cli.jobs, {})


class WaitTests(NebiusCase):
    def start(self, plan=None):
        if plan is not None:
            self.cli.job_plan = plan
        backend = self.prepared()
        return backend, backend.submit("soup-a", self.workload())

    def test_completed_job_has_times_and_container_seconds(self):
        backend, handle = self.start()
        result = backend.wait(handle, running_max_seconds=3000, total_max_seconds=6000, poll_seconds=60)
        self.assertEqual(result.state, "COMPLETED")
        self.assertIsNone(result.reason)
        self.assertEqual(result.container_seconds, 780.0)
        self.assertTrue(result.started_at.endswith("Z"))
        self.assertEqual(result.job_name, "soup-a")

    def test_capacity_failure_reports_the_reason_and_no_start(self):
        backend, handle = self.start([(0, "PROVISIONING", None), (300, "ERROR", "NotEnoughResources")])
        result = backend.wait(handle, running_max_seconds=3000, total_max_seconds=6000, poll_seconds=60)
        self.assertEqual((result.state, result.reason), ("ERROR", "NotEnoughResources"))
        self.assertIsNone(result.started_at)
        self.assertIsNone(result.container_seconds)

    def test_failed_job(self):
        backend, handle = self.start([(0, "RUNNING", None), (200, "FAILED", None)])
        result = backend.wait(handle, running_max_seconds=3000, total_max_seconds=6000, poll_seconds=30)
        self.assertEqual(result.state, "FAILED")
        self.assertEqual(result.container_seconds, 200.0)

    def test_transient_status_errors_keep_polling(self):
        backend, handle = self.start()
        self.cli.fail(("ai", "job", "get"), "rpc error: code = Unavailable desc = i/o timeout", times=5)
        result = backend.wait(handle, running_max_seconds=3000, total_max_seconds=6000, poll_seconds=60)
        self.assertEqual(result.state, "COMPLETED")

    def test_persistent_non_transient_errors_surface(self):
        backend, handle = self.start()
        self.cli.fail(("ai", "job", "get"), "Unauthenticated: token expired", times=100)
        with self.assertRaises(BackendError) as caught:
            backend.wait(handle, running_max_seconds=3000, total_max_seconds=6000, poll_seconds=60)
        self.assertIn("Unauthenticated", str(caught.exception))

    def test_running_limit_cancels_the_job_itself(self):
        backend, handle = self.start([(0, "PROVISIONING", None), (120, "RUNNING", None)])
        result = backend.wait(handle, running_max_seconds=300, total_max_seconds=6000, poll_seconds=60)
        self.assertEqual((result.state, result.reason), ("CANCELLED", "watchdog_cancel"))
        self.assertEqual(self.cli.count("ai", "job", "cancel"), 1)
        self.assertLess(self.clock.now - self.cli.jobs["soup-a"]["created"], 600)

    def test_total_limit_cancels_even_before_running(self):
        backend, handle = self.start([(0, "PROVISIONING", None)])
        result = backend.wait(handle, running_max_seconds=3000, total_max_seconds=200, poll_seconds=60)
        self.assertEqual((result.state, result.reason), ("CANCELLED", "watchdog_cancel"))
        self.assertIsNone(result.started_at)

    def test_job_that_ignores_cancel_ends_as_timeout(self):
        backend, handle = self.start([(0, "RUNNING", None)])
        self.cli.cancel_ignored = True
        result = backend.wait(handle, running_max_seconds=100, total_max_seconds=6000, poll_seconds=60)
        self.assertEqual((result.state, result.reason), ("TIMEOUT", "watchdog_cancel"))
        self.assertGreater(self.cli.count("ai", "job", "cancel"), 0)

    def test_failed_cancel_is_retried_on_later_polls(self):
        backend, handle = self.start([(0, "RUNNING", None)])
        self.cli.fail(("ai", "job", "cancel"), "Unavailable: try later", times=3)
        result = backend.wait(handle, running_max_seconds=100, total_max_seconds=6000, poll_seconds=60)
        self.assertEqual(result.reason, "watchdog_cancel")

    def test_an_unreachable_api_ends_in_an_error_after_a_hard_ceiling(self):
        backend, handle = self.start([(0, "RUNNING", None)])
        self.cli.fail(("ai", "job", "get"), "rpc error: code = Unavailable desc = i/o timeout", times=10 ** 6)
        self.cli.fail(("ai", "job", "cancel"), "rpc error: code = Unavailable desc = i/o timeout", times=10 ** 6)
        started = self.clock.now
        with self.assertRaises(BackendError) as caught:
            backend.wait(handle, running_max_seconds=3000, total_max_seconds=6000, poll_seconds=60)
        self.assertIn("gave up waiting", str(caught.exception))
        elapsed = self.clock.now - started
        self.assertLess(elapsed, 6000 + 300 + 300 + 200)
        self.assertGreater(elapsed, 6000)

    def test_a_cancel_that_always_fails_ends_in_an_error_after_the_ceiling(self):
        backend, handle = self.start([(0, "RUNNING", None)])
        self.cli.fail(("ai", "job", "cancel"), "rpc error: code = Unavailable desc = i/o timeout", times=10 ** 6)
        started = self.clock.now
        with self.assertRaises(BackendError):
            backend.wait(handle, running_max_seconds=100, total_max_seconds=6000, poll_seconds=60)
        self.assertLess(self.clock.now - started, 6000 + 300 + 300 + 200)
        self.assertGreater(self.cli.count("ai", "job", "cancel"), 3)

    def test_the_cancel_grace_ends_before_the_provider_timeout_does(self):
        from robot_debug import ledger
        from robot_debug.backends import nebius
        from robot_debug import orchestrator as orch
        for deadline in (1000, 1500, 3000):
            watchdog = deadline + orch.RUNNING_GRACE_SECONDS + nebius.CANCEL_GRACE_SECONDS
            self.assertLessEqual(watchdog, ledger.provider_timeout_seconds(deadline))

    def test_handle_without_id_is_recovered_by_name(self):
        backend, handle = self.start()
        result = backend.wait(JobHandle("soup-a", None), running_max_seconds=3000,
                              total_max_seconds=6000, poll_seconds=60)
        self.assertEqual(result.state, "COMPLETED")
        self.assertEqual(result.job_id, handle.job_id)


class DownloadTests(NebiusCase):
    def objects(self):
        return {
            "faultline-runs/soup-a/manifest.json": b"[]",
            "faultline-runs/soup-a/episodes/e0/video.mp4": b"12345",
            "faultline-runs/soup-a-other/leak.json": b"x",
            "faultline-runs/soup-b/leak.json": b"x",
        }

    def test_downloads_only_the_jobs_prefix_with_in_memory_credentials(self):
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        self.s3.objects = self.objects()
        dest = Path(self.temp.name) / "evidence"
        out = backend.download(handle, dest)
        self.assertEqual(out, dest)
        self.assertEqual((dest / "manifest.json").read_bytes(), b"[]")
        self.assertEqual((dest / "episodes" / "e0" / "video.mp4").read_bytes(), b"12345")
        self.assertEqual(self.s3.listed_prefixes, ["faultline-runs/soup-a/"])
        self.assertFalse(any("leak" in key for key in self.s3.downloaded))
        endpoint, region, key_id, secret = self.s3_calls[0]
        self.assertEqual(endpoint, "https://storage.eu-north1.nebius.cloud")
        self.assertEqual((region, key_id, secret), ("eu-north1", "AKIAFAKEKEYID", self.cli.secret_value))

    def test_secret_never_reaches_a_command_line_a_file_or_a_message(self):
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        self.s3.objects = self.objects()
        backend.download(handle, Path(self.temp.name) / "evidence")
        self.assertFalse(any(self.cli.secret_value in part for argv in self.cli.argv for part in argv))
        for path in Path(self.temp.name).rglob("*"):
            if path.is_file():
                self.assertNotIn(self.cli.secret_value.encode(), path.read_bytes(), str(path))

    def test_unsafe_keys_are_refused(self):
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        for bad in ("faultline-runs/soup-a/../../escape", "faultline-runs/soup-a/a//b",
                    "faultline-runs/soup-a/..\\x", "faultline-runs/soup-a/C:evil"):
            self.s3.objects = {bad: b"x"}
            with self.assertRaises(BackendError, msg=bad):
                backend.download(handle, Path(self.temp.name) / "evidence")
        self.assertFalse((Path(self.temp.name) / "escape").exists())

    def test_size_mismatch_is_detected_and_not_kept(self):
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        self.s3.objects = {"faultline-runs/soup-a/a.bin": b"abcdef"}
        self.s3.wrong_size = "faultline-runs/soup-a/a.bin"
        dest = Path(self.temp.name) / "evidence"
        with self.assertRaises(BackendError):
            backend.download(handle, dest)
        self.assertFalse((dest / "a.bin").exists())

    def test_empty_export_is_an_error(self):
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        with self.assertRaises(BackendError) as caught:
            backend.download(handle, Path(self.temp.name) / "evidence")
        self.assertIn("faultline-runs/soup-a/", str(caught.exception))

    def test_byte_limit(self):
        backend = self.prepared(max_download_bytes=3)
        handle = backend.submit("soup-a", self.workload())
        self.s3.objects = {"faultline-runs/soup-a/a.bin": b"abcdef"}
        with self.assertRaises(BackendError):
            backend.download(handle, Path(self.temp.name) / "evidence")

    def test_listing_is_retried_while_a_new_key_propagates(self):
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        self.s3.objects = {"faultline-runs/soup-a/a.bin": b"abc"}
        self.s3.list_failures = 2
        backend.download(handle, Path(self.temp.name) / "evidence")
        self.assertEqual(len(self.s3.listed_prefixes), 3)

    def test_download_after_finish_explains_itself(self):
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        backend.finish()
        with self.assertRaises(BackendError) as caught:
            backend.download(handle, Path(self.temp.name) / "evidence")
        self.assertIn("access key", str(caught.exception))

    def test_missing_boto3_is_explained(self):
        from robot_debug.backends import nebius as module
        import builtins
        real_import = builtins.__import__

        def no_boto(name, *args, **kwargs):
            if name in ("boto3", "botocore", "botocore.config", "truststore"):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        builtins.__import__ = no_boto
        try:
            with self.assertRaises(BackendError) as caught:
                module.default_s3_factory("https://x", "r", "k", "s")
        finally:
            builtins.__import__ = real_import
        self.assertIn("boto3", str(caught.exception))


class LifecycleTests(NebiusCase):
    def test_finish_deletes_the_key_and_is_idempotent(self):
        backend = self.prepared()
        backend.finish()
        backend.finish()
        self.assertEqual(self.cli.keys, {})
        self.assertEqual(self.cli.count("iam", "v2", "access-key", "delete"), 1)
        self.assertTrue(json.loads((self.run_dir / "backend-state.json").read_text("utf-8"))["access_key_deleted"])
        self.assertEqual(self.cli.count("storage", "bucket", "delete"), 1, "an empty bucket is removed once")

    def test_finish_tolerates_an_already_deleted_key(self):
        backend = self.prepared()
        self.cli.keys.clear()
        backend.finish()
        self.assertTrue(backend._state["access_key_deleted"])

    def test_finish_before_prepare_is_a_noop(self):
        self.make().finish()
        self.assertEqual(self.cli.calls, [])

    def test_finish_retries_transient_errors_and_reports_real_failures(self):
        backend = self.prepared()
        self.cli.fail(("iam", "v2", "access-key", "delete"), "Unavailable", times=1)
        backend.finish()
        self.assertEqual(self.cli.keys, {})
        other = self.prepared(run_dir=Path(self.temp.name) / "r2")
        self.cli.fail(("iam", "v2", "access-key", "delete"), "PermissionDenied: nope", times=1)
        with self.assertRaises(BackendError):
            other.finish()
        other.finish()
        self.assertEqual(self.cli.keys, {})

    def test_cancel_stops_a_running_job_and_skips_terminal_ones(self):
        self.cli.job_plan = [(0, "RUNNING", None), (5000, "COMPLETED", None)]
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        backend.cancel(handle)
        self.assertEqual(self.cli.count("ai", "job", "cancel"), 1)
        self.clock.now += 6000
        self.cli.jobs["soup-a"]["cancelled_at"] = None
        backend.cancel(handle)
        self.assertEqual(self.cli.count("ai", "job", "cancel"), 1)

    def test_cancel_reports_what_happened(self):
        self.cli.job_plan = [(0, "RUNNING", None), (5000, "COMPLETED", None)]
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        self.assertEqual(backend.cancel(handle), "cancelled")
        self.clock.now += 6000
        self.cli.jobs["soup-a"]["cancelled_at"] = None
        self.assertEqual(backend.cancel(handle), "finished")
        self.assertEqual(backend.cancel(JobHandle("never-created", None)), "not_found")

    def test_lookup_finds_a_job_by_name_and_says_none_when_absent(self):
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        self.assertEqual(backend.lookup("soup-a"), handle)
        self.assertIsNone(backend.lookup("soup-b"))
        self.cli.fail(("ai", "job", "get-by-name"), "PermissionDenied: nope", times=1)
        with self.assertRaises(BackendError):
            backend.lookup("soup-a")

    def test_logs_tail(self):
        backend = self.prepared()
        handle = backend.submit("soup-a", self.workload())
        self.cli.logs = "\n".join("line %d" % i for i in range(10)) + "\n"
        self.assertEqual(backend.logs_tail(handle, lines=2), "line 8\nline 9")
        self.cli.fail(("ai", "job", "logs"), "PermissionDenied: x", times=1)
        self.assertIn("logs unavailable", backend.logs_tail(handle))


class RealExecutableTests(unittest.TestCase):
    def test_default_runner_drives_a_real_subprocess(self):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "fake_nebius.py"
            script.write_text(
                "import json, sys\n"
                "print(json.dumps({'args': sys.argv[1:]}))\n", encoding="utf-8")
            cli = NebiusCli(Launcher([sys.executable, str(script)]))
            self.assertEqual(cli.json(["config", "get", "parent-id"]), {"args": ["config", "get", "parent-id"]})


if __name__ == "__main__":
    unittest.main()
