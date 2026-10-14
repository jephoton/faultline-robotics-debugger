import json
import tempfile
import unittest
from pathlib import Path

from robot_debug.backends import (
    Backend,
    BackendError,
    JobHandle,
    make_backend,
    redact,
)
from robot_debug.backends.local import LocalBackend
from tests.fakes.backend_fakes import FakeClock, FakeDocker


def spec(**backend):
    base = {"kind": "local", "image": "faultline-serverless:local"}
    base.update(backend)
    return {"name": "unit", "backend": base}


class LocalBackendCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run_dir = Path(self.temp.name) / "run"
        self.run_dir.mkdir()
        self.clock = FakeClock()

    def make(self, **docker_kwargs):
        self.docker = FakeDocker(self.clock, **docker_kwargs)
        backend = LocalBackend(
            "faultline-serverless:local",
            runner=self.docker.run,
            popen=self.docker.popen,
            clock=self.clock,
            sleep=self.clock.sleep,
            environ={"HF_TOKEN": "hf_fake_value_for_tests"},
        )
        backend.prepare(self.run_dir, spec())
        self.addCleanup(backend.finish)
        return backend

    def workload(self, name="unit-a"):
        return {"schema_version": 1, "mode": "m6-smoke", "run_id": name}


class ProtocolTests(LocalBackendCase):
    def test_satisfies_protocol_and_is_free(self):
        backend = self.make()
        self.assertIsInstance(backend, Backend)
        self.assertEqual(backend.kind, "local")
        self.assertEqual(backend.price_per_hour(), 0.0)

    def test_make_backend_builds_local_from_spec(self):
        backend = make_backend(spec())
        self.assertEqual(backend.kind, "local")

    def test_make_backend_rejects_unknown_kind_and_missing_section(self):
        with self.assertRaises(BackendError):
            make_backend({"backend": {"kind": "mystery"}})
        with self.assertRaises(BackendError):
            make_backend({})

    def test_from_spec_requires_an_image(self):
        with self.assertRaises(BackendError):
            LocalBackend.from_spec({"backend": {"kind": "local"}})

    def test_redact_keeps_kind_and_four_characters(self):
        text = redact("job aijob-e00fakejob00000001 in e00fakeregistry001 failed")
        self.assertIn("aijob-e00f...", text)
        self.assertIn("e00f...", text)
        self.assertNotIn("akejob", text)


class PrepareTests(LocalBackendCase):
    def test_refuses_without_nvidia_runtime(self):
        docker = FakeDocker(self.clock, runtimes=("runc",))
        backend = LocalBackend("img", runner=docker.run, popen=docker.popen,
                               clock=self.clock, sleep=self.clock.sleep,
                               environ={"HF_TOKEN": "x"})
        with self.assertRaises(BackendError) as caught:
            backend.prepare(self.run_dir, spec())
        self.assertIn("nvidia", str(caught.exception).lower())

    def test_reports_missing_docker(self):
        def missing(argv, cwd=None, timeout=None):
            raise FileNotFoundError("docker")

        backend = LocalBackend("img", runner=missing, clock=self.clock,
                               sleep=self.clock.sleep, environ={"HF_TOKEN": "x"})
        with self.assertRaises(BackendError) as caught:
            backend.prepare(self.run_dir, spec())
        self.assertIn("docker", str(caught.exception).lower())


class SubmitTests(LocalBackendCase):
    def test_submit_builds_the_same_entrypoint_as_the_nebius_job(self):
        backend = self.make()
        handle = backend.submit("unit-a", self.workload())
        self.assertEqual(handle, JobHandle("unit-a", "unit-a"))
        argv = self.docker.processes[0].argv
        self.assertEqual(argv[:2], ["docker", "run"])
        self.assertIn("--rm", argv)
        self.assertEqual(argv[argv.index("--name") + 1], "unit-a")
        self.assertEqual(argv[argv.index("--gpus") + 1], "all")
        self.assertEqual(argv[argv.index("--entrypoint") + 1], "/opt/conda/envs/libero/bin/python")
        self.assertEqual(argv[argv.index("-w") + 1], "/opt/robot-debug")
        self.assertEqual(argv[-3:], [
            "/opt/robot-debug/scripts/run_serverless_workload.py",
            "--config", "/etc/faultline/workload.json"])
        self.assertIn("faultline-serverless:local", argv)

    def test_workload_is_mounted_read_only_and_persistent_is_in_the_run_folder(self):
        backend = self.make()
        backend.submit("unit-a", self.workload())
        argv = self.docker.processes[0].argv
        mounts = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--mount"]
        workload_file = self.run_dir / "jobs" / "unit-a" / "workload.json"
        persistent = self.run_dir / "jobs" / "unit-a" / "persistent"
        self.assertEqual(json.loads(workload_file.read_text(encoding="utf-8"))["run_id"], "unit-a")
        self.assertIn("type=bind,source=%s,target=/etc/faultline/workload.json,readonly" % workload_file, mounts)
        self.assertIn("type=bind,source=%s,target=/persistent" % persistent, mounts)
        self.assertTrue(persistent.is_dir())

    def test_token_is_inherited_never_placed_on_the_command_line(self):
        backend = self.make()
        backend.submit("unit-a", self.workload())
        argv = self.docker.processes[0].argv
        self.assertIn("HF_TOKEN", argv)
        self.assertEqual(argv[argv.index("--env") + 1], "HF_TOKEN")
        self.assertFalse(any("hf_fake_value" in part for part in argv))
        env = self.docker.processes[0].kwargs["env"]
        self.assertEqual(env["HF_TOKEN"], "hf_fake_value_for_tests")

    def test_missing_token_is_a_clear_error(self):
        docker = FakeDocker(self.clock)
        backend = LocalBackend("img", runner=docker.run, popen=docker.popen,
                               clock=self.clock, sleep=self.clock.sleep, environ={})
        backend.prepare(self.run_dir, spec())
        with self.assertRaises(BackendError) as caught:
            backend.submit("unit-a", self.workload())
        self.assertIn("HF_TOKEN", str(caught.exception))
        self.assertEqual(docker.processes, [])

    def test_workload_run_id_must_match_job_name(self):
        backend = self.make()
        with self.assertRaises(BackendError):
            backend.submit("unit-a", self.workload("other"))

    def test_job_names_are_validated(self):
        backend = self.make()
        for bad in ("Unit", "-x", "a b", "a/../b", ""):
            with self.assertRaises(BackendError):
                backend.submit(bad, self.workload(bad))

    def test_submit_before_prepare_fails(self):
        backend = LocalBackend("img", runner=lambda *a, **k: None, clock=self.clock,
                               sleep=self.clock.sleep, environ={"HF_TOKEN": "x"})
        with self.assertRaises(BackendError):
            backend.submit("unit-a", self.workload())

    def test_docker_start_failure_is_a_backend_error(self):
        def boom(argv, **kwargs):
            raise FileNotFoundError("docker")

        backend = LocalBackend("img", runner=FakeDocker(self.clock).run, popen=boom,
                               clock=self.clock, sleep=self.clock.sleep,
                               environ={"HF_TOKEN": "x"})
        backend.prepare(self.run_dir, spec())
        with self.assertRaises(BackendError):
            backend.submit("unit-a", self.workload())


class WaitTests(LocalBackendCase):
    def test_completed_job(self):
        backend = self.make(run_for=30)
        handle = backend.submit("unit-a", self.workload())
        result = backend.wait(handle, running_max_seconds=600, total_max_seconds=900, poll_seconds=5)
        self.assertEqual(result.state, "COMPLETED")
        self.assertIsNone(result.reason)
        self.assertEqual(result.job_name, "unit-a")
        self.assertGreaterEqual(result.container_seconds, 30)
        self.assertTrue(result.started_at.endswith("Z"))
        self.assertTrue(result.finished_at.endswith("Z"))

    def test_nonzero_exit_is_failed_with_container_reason(self):
        backend = self.make(run_for=5, returncode=3)
        handle = backend.submit("unit-a", self.workload())
        result = backend.wait(handle, running_max_seconds=600, total_max_seconds=900, poll_seconds=1)
        self.assertEqual(result.state, "FAILED")
        self.assertEqual(result.reason, "ContainerFailed")

    def test_running_limit_cancels_the_container_itself(self):
        backend = self.make(run_for=10_000)
        handle = backend.submit("unit-a", self.workload())
        result = backend.wait(handle, running_max_seconds=60, total_max_seconds=900, poll_seconds=5)
        self.assertEqual(result.state, "CANCELLED")
        self.assertEqual(result.reason, "watchdog_cancel")
        self.assertEqual(len([c for c in self.docker.calls if c[1:2] == ["stop"]]), 1)

    def test_total_limit_also_cancels(self):
        backend = self.make(run_for=10_000)
        handle = backend.submit("unit-a", self.workload())
        result = backend.wait(handle, running_max_seconds=5000, total_max_seconds=30, poll_seconds=5)
        self.assertEqual(result.reason, "watchdog_cancel")

    def test_stubborn_container_is_killed_and_reported_as_timeout(self):
        backend = self.make(run_for=10_000, ignore_stop=True)
        handle = backend.submit("unit-a", self.workload())
        result = backend.wait(handle, running_max_seconds=20, total_max_seconds=900, poll_seconds=5)
        self.assertEqual(result.state, "TIMEOUT")
        self.assertEqual(result.reason, "watchdog_cancel")
        self.assertTrue(self.docker.processes[0].killed)

    def test_unknown_handle_is_unknown_not_a_crash(self):
        backend = self.make()
        result = backend.wait(JobHandle("ghost", "ghost"), running_max_seconds=60,
                              total_max_seconds=60, poll_seconds=1)
        self.assertEqual(result.state, "UNKNOWN")


class DownloadAndLogsTests(LocalBackendCase):
    def finished(self):
        backend = self.make(run_for=1)
        handle = backend.submit("unit-a", self.workload())
        backend.wait(handle, running_max_seconds=60, total_max_seconds=60, poll_seconds=1)
        return backend, handle

    def test_download_copies_only_this_jobs_export(self):
        backend, handle = self.finished()
        persistent = self.run_dir / "jobs" / "unit-a" / "persistent" / "faultline-runs"
        (persistent / "unit-a" / "episodes").mkdir(parents=True)
        (persistent / "unit-a" / "episodes" / "e0.json").write_text("{}", encoding="utf-8")
        (persistent / "unit-a" / "manifest.json").write_text("[]", encoding="utf-8")
        (persistent / "other").mkdir()
        (persistent / "other" / "secret.json").write_text("{}", encoding="utf-8")
        dest = self.run_dir / "evidence"
        out = backend.download(handle, dest)
        self.assertEqual(out, dest)
        self.assertTrue((dest / "episodes" / "e0.json").is_file())
        self.assertTrue((dest / "manifest.json").is_file())
        self.assertFalse((dest / "secret.json").exists())
        self.assertFalse((dest / "other").exists())

    def test_download_without_export_is_an_error(self):
        backend, handle = self.finished()
        with self.assertRaises(BackendError):
            backend.download(handle, self.run_dir / "evidence")

    def test_logs_tail_reads_the_container_log(self):
        backend, handle = self.finished()
        log = self.run_dir / "jobs" / "unit-a" / "container.log"
        log.write_text("\n".join("line %d" % i for i in range(10)) + "\n", encoding="utf-8")
        self.assertEqual(backend.logs_tail(handle, lines=3), "line 7\nline 8\nline 9")

    def test_cancel_stops_the_named_container_and_finish_is_a_noop(self):
        backend = self.make(run_for=10_000)
        handle = backend.submit("unit-a", self.workload())
        backend.cancel(handle)
        self.assertIn(["docker", "stop", "-t", "30", "unit-a"], self.docker.calls)
        backend.finish()
        backend.finish()


if __name__ == "__main__":
    unittest.main()
