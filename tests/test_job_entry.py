from __future__ import annotations

import io
import json
import os
import ctypes
from contextlib import nullcontext
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

from robot_debug import job_entry
from robot_debug.job_entry import (
    ImageLayout,
    ProductionModelFactory,
    child_environment,
    evaluator_environment,
    load_workload,
    main,
    model_environment,
    model_server_argv,
    prefetch_models,
)
from robot_debug.job_model import ModelProcess
from robot_debug.job_process import InfrastructureError, close_owned_process_group
from robot_debug.job_runtime import JobRuntimeError
from robot_debug.job_workload import WorkloadPaths, run_workload
from scripts import serverless_prefetch


ROOT = Path(__file__).resolve().parents[1]
POSIX = os.name == "posix"
VALID = {"schema_version": 1, "mode": "pilot", "run_id": "pilot-1", "deadline_seconds": 2400}


def _layout(root: Path) -> ImageLayout:
    for name in ("project", "upstream", "work", "hf", "export"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return ImageLayout(
        project_root=root / "project",
        upstream_root=root / "upstream",
        simulator_source=root / "simulator-src",
        model_python=Path(sys.executable),
        evaluator=root / "vla-eval",
        work_root=root / "work",
        hf_home=root / "hf",
        export_root=root / "export",
    )


class WorkloadLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, payload: bytes) -> Path:
        path = self.root / "workload.json"
        path.write_bytes(payload)
        return path

    def test_accepts_valid_workload(self) -> None:
        self.assertEqual(load_workload(self._write(json.dumps(VALID).encode())), VALID)

    def test_rejects_oversize_invalid_json_and_unknown_fields(self) -> None:
        for payload in (
            b" " * (64 * 1024 + 1),
            b"{not json",
            b"\xff\xfe",
            json.dumps(dict(VALID, extra=1)).encode(),
        ):
            with self.subTest(payload=payload[:20]):
                with self.assertRaises(JobRuntimeError):
                    load_workload(self._write(payload))

    def test_missing_file_is_a_configuration_error(self) -> None:
        with self.assertRaises(JobRuntimeError):
            load_workload(self.root / "absent.json")


class EnvironmentTests(unittest.TestCase):
    BASE = {
        "PATH": "/usr/bin",
        "HF_TOKEN": "hf_secret_value",
        "AWS_SECRET_ACCESS_KEY": "x",
        "API_KEY": "x",
        "DB_PASSWORD": "x",
        "OPENAI_APIKEY": "x",
        "HUGGING_FACE_HUB_TOKEN": "x",
        "GIT_AUTH": "x",
        "TOKENIZERS_PARALLELISM": "false",
        "MUJOCO_GL": "egl",
        "PYTHONPATH": "/somewhere",
    }

    def test_child_environment_drops_secret_like_names_only(self) -> None:
        env = child_environment(self.BASE, EXTRA="1")
        for name in ("HF_TOKEN", "AWS_SECRET_ACCESS_KEY", "API_KEY", "DB_PASSWORD",
                     "OPENAI_APIKEY", "HUGGING_FACE_HUB_TOKEN", "GIT_AUTH"):
            self.assertNotIn(name, env)
        self.assertEqual(env["TOKENIZERS_PARALLELISM"], "false")
        self.assertEqual(env["MUJOCO_GL"], "egl")
        self.assertEqual(env["EXTRA"], "1")

    def test_model_environment_is_offline_private_and_tokenless(self) -> None:
        layout = ImageLayout()
        env = model_environment(layout, self.BASE)
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertEqual(env["TRANSFORMERS_OFFLINE"], "1")
        self.assertEqual(env["HF_HOME"], str(layout.hf_home))
        self.assertNotIn("HF_TOKEN", env)
        self.assertNotIn("PYTHONPATH", env)

    def test_evaluator_environment_uses_project_and_simulator_sources(self) -> None:
        layout = ImageLayout()
        env = evaluator_environment(layout, self.BASE)
        self.assertEqual(
            env["PYTHONPATH"], "{}:{}".format(layout.project_root / "src", layout.simulator_source)
        )
        self.assertNotIn("HF_TOKEN", env)

    def test_single_threaded_blas_is_opt_in_and_overrides_inherited_values(self) -> None:
        layout = ImageLayout()
        plain = evaluator_environment(layout, dict(self.BASE, OMP_NUM_THREADS="16"))
        self.assertEqual("16", plain["OMP_NUM_THREADS"])
        single = evaluator_environment(layout, dict(self.BASE, OMP_NUM_THREADS="16"), single_thread_blas=True)
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            self.assertEqual("1", single[name])
        self.assertEqual(plain["PYTHONPATH"], single["PYTHONPATH"])
        self.assertNotIn("HF_TOKEN", single)


class ModelArgvTests(unittest.TestCase):
    def test_server_arguments_match_historical_launch_script(self) -> None:
        script = (ROOT / "scripts" / "cloud_guest" / "model-launch.sh").read_text(encoding="utf-8")
        block = script[script.index('nohup "$PY"'):script.index("> \"$SESSION/model-server.log\"")]
        historical = [token for token in shlex.split(block.replace("\\\n", " ")) if token.startswith("--")]
        argv = model_server_argv(ImageLayout())
        self.assertEqual(argv[0], "/opt/model-env/bin/python")
        self.assertEqual(argv[1], "/opt/upstream/src/vla_eval/model_servers/lerobot.py")
        self.assertEqual(argv[2:], historical)

    def test_pinned_revisions_match_historical_launch_and_design(self) -> None:
        script = (ROOT / "scripts" / "cloud_guest" / "model-launch.sh").read_text(encoding="utf-8")
        checkpoint = serverless_prefetch.PINNED_REVISIONS["nvidia/gr00t17-lerobot-libero_object-640"]
        self.assertIn(checkpoint, script)
        design = (ROOT / "docs" / "superpowers" / "specs" / "2026-10-06-serverless-job-migration-design.md").read_text(encoding="utf-8")
        for revision in serverless_prefetch.pinned_for_suite("libero_object").values():
            self.assertIn(revision, design)

    def test_suite_checkpoints_default_to_libero_object_and_cover_libero_10(self) -> None:
        self.assertEqual("libero_object", job_entry.DEFAULT_SUITE)
        self.assertEqual(
            {"libero_object": "nvidia/gr00t17-lerobot-libero_object-640",
             "libero_10": "nvidia/gr00t17-lerobot-libero_10-640"},
            job_entry.SUITE_CHECKPOINTS)
        self.assertEqual(job_entry.SUITE_CHECKPOINTS, serverless_prefetch.SUITE_CHECKPOINTS)

    def test_other_suite_changes_only_the_checkpoint_flag(self) -> None:
        default = model_server_argv(ImageLayout(), server="faultline", max_batch_size=12)
        other = model_server_argv(ImageLayout(), server="faultline", max_batch_size=12, suite="libero_10")
        self.assertEqual(model_server_argv(ImageLayout(), server="faultline", max_batch_size=12,
                                           suite="libero_object"), default)
        changed = [(a, b) for a, b in zip(default, other) if a != b]
        self.assertEqual([("--args.checkpoint=nvidia/gr00t17-lerobot-libero_object-640",
                           "--args.checkpoint=nvidia/gr00t17-lerobot-libero_10-640")], changed)
        self.assertEqual(len(default), len(other))
        self.assertIn("--args.checkpoint=nvidia/gr00t17-lerobot-libero_10-640",
                      job_entry.model_flags_for_scripts(ImageLayout(), 12, suite="libero_10"))
        self.assertIn("--args.checkpoint=nvidia/gr00t17-lerobot-libero_object-640",
                      job_entry.model_flags_for_scripts(ImageLayout(), 12))

    def test_unknown_suite_is_rejected(self) -> None:
        for suite in ("libero_spatial", "", None, 3, "libero_10 "):
            with self.subTest(suite=suite), self.assertRaises(ValueError):
                model_server_argv(ImageLayout(), suite=suite)

    def test_prefetch_command_names_a_suite_only_when_it_is_not_the_default(self) -> None:
        layout = ImageLayout()
        base = job_entry.prefetch_command(layout, Path("/tmp/out.json"))
        self.assertNotIn("--suite", base)
        self.assertEqual(base, job_entry.prefetch_command(layout, Path("/tmp/out.json"), suite="libero_object"))
        other = job_entry.prefetch_command(layout, Path("/tmp/out.json"), suite="libero_10")
        self.assertEqual(base + ["--suite", "libero_10"], other)
        with self.assertRaises(ValueError):
            job_entry.prefetch_command(layout, Path("/tmp/out.json"), suite="libero_goal")

    def test_factory_uses_its_suite_for_the_server_description(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            factory = ProductionModelFactory(
                _layout(Path(temp)), base_env={}, deadline=time.monotonic() + 2400, suite="libero_10")
            factory.ensure_prefetched = lambda *args, **kwargs: None
            model = factory(log_root=Path(temp) / "work" / "run" / "logs", server="faultline", max_batch_size=4)
        self.assertIn("--args.checkpoint=nvidia/gr00t17-lerobot-libero_10-640", model._argv)
        with self.assertRaises(ValueError):
            ProductionModelFactory(ImageLayout(), base_env={}, deadline=1.0, suite="libero_spatial")


class _FakeHub:
    """Minimal snapshot cache: commit downloads, ``refs/main`` resolution."""

    def __init__(self, cache: Path, remote_main: dict) -> None:
        self.constants = types.SimpleNamespace(HF_HUB_CACHE=str(cache))
        self.cache = cache
        self.remote_main = remote_main

    def _repo(self, repo_id: str) -> Path:
        return self.cache / ("models--" + repo_id.replace("/", "--"))

    def snapshot_download(self, *, repo_id, revision=None, local_files_only=False):
        repo = self._repo(repo_id)
        if local_files_only:
            commit = (repo / "refs" / (revision or "main")).read_text(encoding="ascii")
        else:
            commit = revision if re.fullmatch(r"[0-9a-f]{40}", revision) else self.remote_main[repo_id]
            if not re.fullmatch(r"[0-9a-f]{40}", revision):
                (repo / "refs").mkdir(parents=True, exist_ok=True)
                (repo / "refs" / revision).write_text(commit, encoding="ascii")
        snapshot = repo / "snapshots" / commit
        snapshot.mkdir(parents=True, exist_ok=True)
        return str(snapshot)


class PrefetchScriptTests(unittest.TestCase):
    def test_pins_main_to_approved_commit_and_records_cosmos(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cosmos = "c" * 40
            moved = {
                "nvidia/gr00t17-lerobot-libero_object-640": "a" * 40,
                "nvidia/GR00T-N1.7-3B": "b" * 40,
                "nvidia/Cosmos-Reason2-2B": cosmos,
            }
            hub = _FakeHub(root / "hub", moved)
            output = root / "resolution.json"
            self.assertEqual(serverless_prefetch.main(["--output", str(output)], hub=hub), 0)
            repositories = json.loads(output.read_text(encoding="utf-8"))["repositories"]
            self.assertEqual(
                {"nvidia/gr00t17-lerobot-libero_object-640", "nvidia/GR00T-N1.7-3B", "nvidia/Cosmos-Reason2-2B"},
                set(repositories))
            for repo, revision in serverless_prefetch.pinned_for_suite("libero_object").items():
                self.assertEqual(repositories[repo], {"revision": revision, "pinned": True})
                self.assertEqual(Path(hub.snapshot_download(repo_id=repo, local_files_only=True)).name, revision)
            self.assertEqual(repositories["nvidia/Cosmos-Reason2-2B"], {"revision": cosmos, "pinned": False})
            with self.assertRaises(FileExistsError):
                serverless_prefetch.main(["--output", str(output)], hub=hub)

    def test_libero_10_prefetch_fetches_only_its_checkpoint_and_the_shared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hub = _FakeHub(root / "hub", {"nvidia/Cosmos-Reason2-2B": "c" * 40})
            output = root / "resolution.json"
            self.assertEqual(
                serverless_prefetch.main(["--output", str(output), "--suite", "libero_10"], hub=hub), 0)
            repositories = json.loads(output.read_text(encoding="utf-8"))["repositories"]
            self.assertEqual(
                {"nvidia/gr00t17-lerobot-libero_10-640", "nvidia/GR00T-N1.7-3B", "nvidia/Cosmos-Reason2-2B"},
                set(repositories))
            self.assertEqual({"revision": "5ee08ab09fac5c5ef2388a14c882ea825ac861db", "pinned": True},
                             repositories["nvidia/gr00t17-lerobot-libero_10-640"])

    def test_all_suites_option_fetches_every_pinned_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hub = _FakeHub(root / "hub", {"nvidia/Cosmos-Reason2-2B": "c" * 40})
            output = root / "resolution.json"
            serverless_prefetch.main(["--output", str(output), "--suite", "all"], hub=hub)
            repositories = json.loads(output.read_text(encoding="utf-8"))["repositories"]
            self.assertEqual(set(serverless_prefetch.PINNED_REVISIONS) | {"nvidia/Cosmos-Reason2-2B"},
                             set(repositories))

    def test_unknown_prefetch_suite_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hub = _FakeHub(Path(temp) / "hub", {})
            with self.assertRaises(SystemExit), mock.patch.object(sys, "stderr", io.StringIO()):
                serverless_prefetch.main(["--output", str(Path(temp) / "r.json"), "--suite", "libero_goal"],
                                         hub=hub)

    def test_real_hub_resolves_pinned_main_offline(self) -> None:
        try:
            import huggingface_hub
        except ImportError:
            self.skipTest("huggingface_hub is not installed")
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "hub"
            fake = _FakeHub(cache, {"nvidia/Cosmos-Reason2-2B": "c" * 40})
            real = huggingface_hub.snapshot_download
            simulated = fake.snapshot_download

            def download(*, repo_id, revision=None, local_files_only=False):
                if local_files_only:
                    return real(repo_id=repo_id, local_files_only=True, cache_dir=str(cache))
                path = Path(simulated(repo_id=repo_id, revision=revision))
                (path / "config.json").write_text("{}", encoding="utf-8")
                return str(path)

            fake.snapshot_download = download
            resolution = serverless_prefetch.fetch(fake, cache)
            for repo, revision in serverless_prefetch.pinned_for_suite("libero_object").items():
                self.assertEqual(resolution[repo]["revision"], revision)
                resolved = real(repo_id=repo, local_files_only=True, cache_dir=str(cache))
                self.assertEqual(Path(resolved).name, revision)

    def test_mismatched_pinned_snapshot_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hub = _FakeHub(Path(temp) / "hub", {})
            hub.snapshot_download = lambda **_kwargs: str(Path(temp) / "snapshots" / ("0" * 40))
            with self.assertRaises(RuntimeError):
                serverless_prefetch.fetch(hub, Path(temp) / "hub")


_FAKE_PREFETCH = """
import argparse, json, os, sys, time, subprocess
parser = argparse.ArgumentParser()
parser.add_argument("--output")
args = parser.parse_args()
mode = os.environ.get("FAKE_PREFETCH_MODE", "ok")
if mode == "fail":
    sys.exit(3)
if mode == "hang":
    pid_file = os.environ["FAKE_PREFETCH_PID_FILE"]
    subprocess.Popen([sys.executable, "-c",
        "import os, sys, time; open(sys.argv[1] + '.tmp', 'w').write(str(os.getpid())); "
        "os.replace(sys.argv[1] + '.tmp', sys.argv[1]); time.sleep(60)", pid_file])
    time.sleep(60)
with open(args.output, "x") as out:
    json.dump({"schema_version": 1, "token_seen": os.environ.get("HF_TOKEN") == "hf_value",
               "offline": os.environ.get("HF_HUB_OFFLINE"),
               "hf_home": os.environ.get("HF_HOME")}, out)
"""


@unittest.skipUnless(POSIX, "prefetch uses POSIX process groups")
class PrefetchProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layout = _layout(self.root)
        scripts = self.layout.project_root / "scripts"
        scripts.mkdir()
        (scripts / "serverless_prefetch.py").write_text(_FAKE_PREFETCH, encoding="utf-8")
        self.run_root = self.layout.work_root / "run"
        self.run_root.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _env(self, mode: str) -> dict:
        return dict(
            os.environ,
            HF_TOKEN="hf_value",
            HF_HUB_OFFLINE="1",
            FAKE_PREFETCH_MODE=mode,
            FAKE_PREFETCH_PID_FILE=str(self.root / "grandchild.pid"),
        )

    def _grandchild_pid(self) -> int:
        pid_file = self.root / "grandchild.pid"
        deadline = time.monotonic() + 20
        while not pid_file.exists():
            if time.monotonic() > deadline:
                self.fail("hanging prefetch grandchild never started")
            time.sleep(0.05)
        return int(pid_file.read_text())

    def _assert_gone(self, pid: int) -> None:
        deadline = time.monotonic() + 2
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            if time.monotonic() > deadline:
                self.fail("prefetch grandchild survived cleanup")
            time.sleep(0.05)

    def _interrupt_once_started(self, signum: int) -> threading.Thread:
        def send() -> None:
            self._grandchild_pid()
            os.kill(os.getpid(), signum)

        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        return thread

    def _prefetch(self, mode: str, timeout_seconds: float) -> None:
        prefetch_models(
            self.layout,
            base_env=self._env(mode),
            output=self.run_root / "model-resolution.json",
            log_root=self.run_root / "logs",
            timeout_seconds=timeout_seconds,
        )

    def test_factory_prefetches_records_provenance_and_does_not_start_model(self) -> None:
        clock = time.monotonic
        factory = ProductionModelFactory(
            self.layout, base_env=self._env("ok"), deadline=clock() + 2400, clock=clock
        )
        model = factory(log_root=self.run_root / "logs")
        self.assertIsInstance(model, ModelProcess)
        self.assertIsNone(model._process)
        resolution = json.loads((self.run_root / "model-resolution.json").read_text(encoding="utf-8"))
        self.assertTrue(resolution["token_seen"])
        self.assertIsNone(resolution["offline"])
        self.assertEqual(resolution["hf_home"], str(self.layout.hf_home))
        provenance = json.loads((self.run_root / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["model_resolution"], resolution)
        self.assertEqual(provenance["upstream_revision"], job_entry.UPSTREAM_REVISION)
        self.assertNotIn("hf_value", (self.run_root / "provenance.json").read_text(encoding="utf-8"))
        self.assertNotIn("HF_TOKEN", model._env)
        self.assertEqual(model._env["HF_HUB_OFFLINE"], "1")

    def test_failed_prefetch_raises_infrastructure_error(self) -> None:
        with self.assertRaises(InfrastructureError):
            prefetch_models(
                self.layout,
                base_env=self._env("fail"),
                output=self.run_root / "model-resolution.json",
                log_root=self.run_root / "logs",
                timeout_seconds=30,
            )

    def test_hanging_prefetch_times_out_and_its_group_is_gone(self) -> None:
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            self._prefetch("hang", 3.0)
        self.assertLess(time.monotonic() - started, 15.0)
        self._assert_gone(self._grandchild_pid())

    def test_interrupt_during_prefetch_cleans_group_and_propagates(self) -> None:
        thread = self._interrupt_once_started(signal.SIGINT)
        with self.assertRaises(KeyboardInterrupt):
            self._prefetch("hang", 30.0)
        thread.join(5)
        self._assert_gone(self._grandchild_pid())

    def test_sigterm_during_cleanup_is_deferred_until_group_is_gone(self) -> None:
        stubborn = subprocess.Popen(
            [sys.executable, "-c",
             "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"],
            start_new_session=True,
        )
        time.sleep(0.3)
        latch = job_entry._TerminationLatch()
        previous = signal.signal(signal.SIGTERM, latch)
        timer = threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGTERM))
        try:
            timer.start()
            with self.assertRaises(KeyboardInterrupt):
                close_owned_process_group(stubborn, stubborn.pid, term_grace_seconds=2.0)
        finally:
            timer.cancel()
            signal.signal(signal.SIGTERM, previous)
        self.assertTrue(latch.received)
        self.assertIsNotNone(stubborn.poll())
        with self.assertRaises(ProcessLookupError):
            os.killpg(stubborn.pid, 0)

    def test_exhausted_budget_refuses_prefetch(self) -> None:
        factory = ProductionModelFactory(
            self.layout, base_env=self._env("ok"), deadline=time.monotonic() + 100
        )
        with self.assertRaises(InfrastructureError):
            factory(log_root=self.run_root / "logs")


@unittest.skipUnless(POSIX, "export preflight owns POSIX process groups")
class ExportPreflightProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.layout = _layout(self.root)
        if sys.platform == "linux":
            self._libc = ctypes.CDLL(None, use_errno=True)
            previous = ctypes.c_int()
            self.assertEqual(self._libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
            self.assertEqual(self._libc.prctl(36, 1, 0, 0, 0), 0)
            self.addCleanup(self._restore_subreaper, previous.value)

        real_popen = subprocess.Popen

        def tracked_popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            if kwargs.get("start_new_session"):
                self.addCleanup(self._cleanup_owned_process_group, process.pid)
            return process

        self._popen_patch = mock.patch.object(job_entry.subprocess, "Popen", side_effect=tracked_popen)
        self._popen_patch.start()
        self.addCleanup(self._popen_patch.stop)

    def _restore_subreaper(self, previous: int) -> None:
        self.assertEqual(self._libc.prctl(36, previous, 0, 0, 0), 0)

    def _reap_adopted_children(self, process_group: int) -> None:
        while True:
            try:
                pid, _status = os.waitpid(-process_group, os.WNOHANG)
            except ChildProcessError:
                return
            if pid == 0:
                return

    def _cleanup_owned_process_group(self, process_group: int) -> None:
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 2.0
        while True:
            self._reap_adopted_children(process_group)
            try:
                os.killpg(process_group, 0)
            except ProcessLookupError:
                return
            if time.monotonic() >= deadline:
                os.killpg(process_group, signal.SIGKILL)
                break
            time.sleep(0.03)
        deadline = time.monotonic() + 2.0
        while True:
            self._reap_adopted_children(process_group)
            try:
                os.killpg(process_group, 0)
            except ProcessLookupError:
                return
            if time.monotonic() >= deadline:
                self.fail("owned preflight process group survived test cleanup")
            time.sleep(0.03)

    def _wait_for_file(self, path: Path, timeout: float = 5.0) -> None:
        limit = time.monotonic() + timeout
        while not path.exists():
            if time.monotonic() >= limit:
                self.fail("preflight fixture did not reach its marker")
            time.sleep(0.02)

    def _assert_gone(self, pid: int) -> None:
        limit = time.monotonic() + 3.0
        while True:
            try:
                waited, _status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                waited = 0
            if waited == pid:
                return
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            if time.monotonic() >= limit:
                self.fail("preflight process group member survived cleanup")
            time.sleep(0.03)

    def _run_fixture(self, argv, *, deadline=None, clock=time.monotonic) -> None:
        job_entry._run_preflight_process(
            argv,
            cwd=self.root,
            log_root=self.root / "logs",
            deadline=deadline if deadline is not None else clock() + 60,
            clock=clock,
        )

    def test_probe_exports_to_unique_paths_and_keeps_logs_private(self) -> None:
        job_entry.bounded_export_preflight(
            self.layout, "pilot-1", deadline=time.monotonic() + 60
        )
        job_entry.bounded_export_preflight(
            self.layout, "pilot-1", deadline=time.monotonic() + 60
        )
        probes = list(self.layout.export_root.glob(".preflight-pilot-1-*"))
        self.assertEqual(2, len(probes))
        self.assertTrue(all((probe / "manifest.json").is_file() for probe in probes))
        logs = sorted((self.layout.work_root / "preflight-logs").glob("*.log"))
        self.assertEqual(4, len(logs))
        self.assertTrue(all(path.stat().st_mode & 0o077 == 0 for path in logs))
        self.assertFalse(any(b"HF_TOKEN" in path.read_bytes() for path in logs))

    def test_child_argv_is_fixed_and_contains_only_trusted_payload(self) -> None:
        argv = job_entry._preflight_child_argv(self.layout, "pilot-1")
        self.assertEqual(sys.executable, argv[0])
        self.assertEqual(["-I", "-B", "-c"], argv[1:4])
        self.assertEqual(str(Path(job_entry.__file__).resolve().parents[1]), argv[5])
        self.assertEqual(
            {"work_root": str(self.layout.work_root),
             "export_root": str(self.layout.export_root), "run_id": "pilot-1"},
            json.loads(argv[6]),
        )
        with self.assertRaises(JobRuntimeError):
            job_entry._preflight_child_argv(self.layout, "../private")

    def test_wait_timeout_uses_thirty_second_cap_and_original_remaining_budget(self) -> None:
        class Finished:
            pid = 900001

            def wait(self, *, timeout):
                self.timeout = timeout
                return 0

        for deadline, expected in ((1000.0, 30.0), (115.5, 1.5)):
            with self.subTest(deadline=deadline):
                process = Finished()
                with mock.patch.object(job_entry.subprocess, "Popen", return_value=process), \
                     mock.patch.object(job_entry, "close_owned_process_group") as close_group:
                    self._run_fixture(
                        [sys.executable, "-B", "-c", "pass"],
                        deadline=deadline,
                        clock=lambda: 100.0,
                    )
                self.assertEqual(expected, process.timeout)
                close_group.assert_called_once_with(process, process.pid)

    def test_child_environment_is_empty_and_output_stays_in_local_logs(self) -> None:
        code = "import os; print(os.environ.get('HF_TOKEN', 'unset')); print('fixture-secret')"
        with mock.patch.dict(os.environ, {"HF_TOKEN": "parent-secret"}):
            self._run_fixture([sys.executable, "-B", "-c", code])
        (stdout_path,) = (self.root / "logs").glob("*.stdout.log")
        output = stdout_path.read_text(encoding="utf-8")
        self.assertEqual("unset\nfixture-secret\n", output)

    def test_nonzero_child_exit_is_a_fixed_runtime_error(self) -> None:
        with self.assertRaisesRegex(InfrastructureError, "export preflight process failed"):
            self._run_fixture([sys.executable, "-B", "-c", "raise SystemExit(7)"])

    def test_expired_probe_budget_does_not_spawn(self) -> None:
        with mock.patch.object(job_entry.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(InfrastructureError, "no time remains"):
                self._run_fixture(
                    [sys.executable, "-B", "-c", "raise SystemExit(0)"],
                    deadline=114.0,
                    clock=lambda: 100.0,
                )
        popen.assert_not_called()

    def test_timeout_closes_grandchild_process_group(self) -> None:
        marker = self.root / "grandchild.pid"
        child_code = (
            "import pathlib,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(60)']); "
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
        )
        argv = [sys.executable, "-B", "-c", child_code, str(marker)]
        started = time.monotonic()
        with self.assertRaisesRegex(InfrastructureError, "export preflight did not complete"):
            self._run_fixture(argv, deadline=started + 14.5)
        self._wait_for_file(marker)
        self._assert_gone(int(marker.read_text(encoding="utf-8")))
        self.assertLess(time.monotonic() - started, 12.0)

    def test_success_closes_orphaned_grandchild_process_group(self) -> None:
        marker = self.root / "success-grandchild.pid"
        child_code = (
            "import pathlib,subprocess,sys; "
            "child=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(60)']); "
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid))"
        )
        self._run_fixture([sys.executable, "-B", "-c", child_code, str(marker)])
        self._assert_gone(int(marker.read_text(encoding="utf-8")))

    def test_sigterm_during_probe_cleans_group_before_exit_143(self) -> None:
        config = self.root / "workload.json"
        config.write_text(json.dumps(VALID), encoding="utf-8")
        marker = self.root / "sigterm-grandchild.pid"
        child_code = (
            "import pathlib,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(60)']); "
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
        )
        argv_builder = lambda *_args: [sys.executable, "-B", "-c", child_code, str(marker)]

        def sender() -> None:
            self._wait_for_file(marker)
            os.kill(os.getpid(), signal.SIGTERM)

        thread = threading.Thread(target=sender, daemon=True)
        thread.start()
        output = io.StringIO()
        with mock.patch.object(job_entry, "_preflight_child_argv", side_effect=argv_builder):
            code = main(
                ["--config", str(config)],
                layout=self.layout,
                environ={},
                runner=lambda *_args, **_kwargs: self.fail("runner started after SIGTERM"),
                stdout=output,
            )
        thread.join(3)
        self.assertEqual(143, code)
        self._assert_gone(int(marker.read_text(encoding="utf-8")))

    def test_sigterm_at_spawn_return_cleans_owned_group_before_exit_143(self) -> None:
        config = self.root / "spawn-workload.json"
        config.write_text(json.dumps(VALID), encoding="utf-8")
        previous = signal.getsignal(signal.SIGTERM)
        owned = []
        tracked_popen = job_entry.subprocess.Popen

        def signal_after_spawn(*args, **kwargs):
            process = tracked_popen(*args, **kwargs)
            owned.append(process.pid)
            os.kill(os.getpid(), signal.SIGTERM)
            return process

        output = io.StringIO()
        with mock.patch.object(job_entry, "_preflight_child_argv", return_value=[
            sys.executable, "-B", "-c", "import time; time.sleep(60)"
        ]), mock.patch.object(job_entry.subprocess, "Popen", side_effect=signal_after_spawn):
            code = main(
                ["--config", str(config)], layout=self.layout, environ={},
                runner=lambda *_args, **_kwargs: self.fail("runner started after SIGTERM"),
                stdout=output,
            )

        self.assertEqual(143, code)
        self.assertEqual(1, len(owned))
        with self.assertRaises(ProcessLookupError):
            os.killpg(owned[0], 0)
        self.assertIs(signal.getsignal(signal.SIGTERM), previous)

    def test_signal_inside_real_popen_constructor_closes_group_before_exit(self) -> None:
        config = self.root / "constructor-workload.json"
        config.write_text(json.dumps(VALID), encoding="utf-8")
        fork_owner = subprocess if hasattr(subprocess, "_fork_exec") else subprocess._posixsubprocess
        fork_name = "_fork_exec" if fork_owner is subprocess else "fork_exec"
        real_fork_exec = getattr(fork_owner, fork_name)
        for signum, expected in ((signal.SIGINT, 130), (signal.SIGTERM, 143)):
            with self.subTest(signum=signum):
                previous = signal.getsignal(signum)
                owned = []

                def signal_inside_constructor(*args):
                    pid = real_fork_exec(*args)
                    owned.append(pid)
                    self.addCleanup(self._cleanup_owned_process_group, pid)
                    os.kill(os.getpid(), signum)
                    return pid

                with mock.patch.object(job_entry, "_preflight_child_argv", return_value=[
                    sys.executable, "-B", "-c", "import time; time.sleep(60)"
                ]), mock.patch.object(fork_owner, fork_name, side_effect=signal_inside_constructor):
                    code = main(
                        ["--config", str(config)], layout=self.layout, environ={},
                        runner=lambda *_args, **_kwargs: self.fail("runner started after signal"),
                        stdout=io.StringIO(),
                    )
                self.assertEqual(expected, code)
                self.assertEqual(1, len(owned))
                with self.assertRaises(ProcessLookupError):
                    os.killpg(owned[0], 0)
                self.assertIs(signal.getsignal(signum), previous)

    def test_launch_signal_with_uncertain_cleanup_is_runtime_error(self) -> None:
        config = self.root / "uncertain-workload.json"
        config.write_text(json.dumps(VALID), encoding="utf-8")
        previous = signal.getsignal(signal.SIGTERM)
        tracked_popen = job_entry.subprocess.Popen
        self._uncertain_processes = []

        def signal_after_spawn(*args, **kwargs):
            process = tracked_popen(*args, **kwargs)
            self._uncertain_processes.append(process)
            os.kill(os.getpid(), signal.SIGTERM)
            return process

        with mock.patch.object(job_entry, "_preflight_child_argv", return_value=[
            sys.executable, "-B", "-c", "import time; time.sleep(60)"
        ]), mock.patch.object(job_entry.subprocess, "Popen", side_effect=signal_after_spawn), \
             mock.patch.object(job_entry, "close_owned_process_group", side_effect=OSError("uncertain")):
            code = main(
                ["--config", str(config)], layout=self.layout, environ={},
                runner=lambda *_args, **_kwargs: self.fail("runner started after signal"),
                stdout=io.StringIO(),
            )
        self.assertEqual(3, code)
        self.assertIs(signal.getsignal(signal.SIGTERM), previous)
        for process in self._uncertain_processes:
            self._cleanup_owned_process_group(process.pid)
            process.poll()

    def test_cleanup_uncertainty_wins_interrupt_during_handler_restoration(self) -> None:
        config = self.root / "restore-workload.json"
        config.write_text(json.dumps(VALID), encoding="utf-8")
        previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
        tracked_popen = job_entry.subprocess.Popen
        real_signal = signal.signal
        owned = []
        deferred_installed = [False]

        def signal_after_spawn(*args, **kwargs):
            process = tracked_popen(*args, **kwargs)
            owned.append(process)
            os.kill(os.getpid(), signal.SIGTERM)
            return process

        def signal_during_restore(signum, handler):
            result = real_signal(signum, handler)
            if signum == signal.SIGINT and handler is not previous[signal.SIGINT]:
                deferred_installed[0] = True
            elif signum == signal.SIGINT and deferred_installed[0] and handler is previous[signal.SIGINT]:
                os.kill(os.getpid(), signal.SIGINT)
                deferred_installed[0] = False
            return result

        try:
            with mock.patch.object(job_entry, "_preflight_child_argv", return_value=[
                sys.executable, "-B", "-c", "import time; time.sleep(60)"
            ]), mock.patch.object(job_entry.subprocess, "Popen", side_effect=signal_after_spawn), \
                 mock.patch.object(job_entry, "close_owned_process_group", side_effect=InfrastructureError("uncertain")), \
                 mock.patch.object(job_entry.signal, "signal", side_effect=signal_during_restore):
                code = main(
                    ["--config", str(config)], layout=self.layout, environ={},
                    runner=lambda *_args, **_kwargs: self.fail("runner started after signal"),
                    stdout=io.StringIO(),
                )
        finally:
            for process in owned:
                self._cleanup_owned_process_group(process.pid)
                process.poll()
        self.assertEqual(3, code)
        self.assertEqual(1, len(owned))
        for signum, handler in previous.items():
            self.assertIs(signal.getsignal(signum), handler)

    def test_direct_probe_restores_handler_when_interrupt_precedes_native_restore(self) -> None:
        previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
        tracked_popen = job_entry.subprocess.Popen
        real_signal = signal.signal
        owned = []
        sent = []

        def signal_after_spawn(*args, **kwargs):
            process = tracked_popen(*args, **kwargs)
            owned.append(process)
            os.kill(os.getpid(), signal.SIGINT)
            return process

        def interrupt_before_restore(signum, handler):
            current = signal.getsignal(signum)
            if (signum == signal.SIGTERM and handler is previous[signal.SIGTERM]
                    and getattr(current, "__name__", "") == "defer_launch_signal" and not sent):
                sent.append(signum)
                os.kill(os.getpid(), signal.SIGINT)
            return real_signal(signum, handler)

        try:
            with mock.patch.object(job_entry.subprocess, "Popen", side_effect=signal_after_spawn), \
                 mock.patch.object(job_entry, "close_owned_process_group", side_effect=InfrastructureError("uncertain")), \
                 mock.patch.object(job_entry.signal, "signal", side_effect=interrupt_before_restore):
                with self.assertRaisesRegex(InfrastructureError, "cleanup could not be confirmed"):
                    self._run_fixture([sys.executable, "-B", "-c", "import time; time.sleep(60)"])
                observed = {signum: signal.getsignal(signum) for signum in previous}
        finally:
            for signum, handler in previous.items():
                real_signal(signum, handler)
            for process in owned:
                self._cleanup_owned_process_group(process.pid)
                process.poll()
        self.assertEqual([signal.SIGTERM], sent)
        self.assertEqual(1, len(owned))
        for signum, handler in previous.items():
            self.assertIs(observed[signum], handler)

    def test_launch_error_restores_handlers_and_reports_fixed_error(self) -> None:
        previous = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
        with mock.patch.object(job_entry.subprocess, "Popen", side_effect=OSError("private argv")):
            with self.assertRaisesRegex(InfrastructureError, "process could not be started") as error:
                self._run_fixture([sys.executable, "-B", "-c", "pass"])
        self.assertNotIn("private argv", str(error.exception))
        for signum, handler in previous.items():
            self.assertIs(signal.getsignal(signum), handler)

    def test_ignored_sigint_stays_ignored_during_launch(self) -> None:
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        tracked_popen = job_entry.subprocess.Popen

        def send_ignored_signal(*args, **kwargs):
            process = tracked_popen(*args, **kwargs)
            os.kill(os.getpid(), signal.SIGINT)
            return process

        try:
            with mock.patch.object(job_entry.subprocess, "Popen", side_effect=send_ignored_signal):
                self._run_fixture([sys.executable, "-B", "-c", "pass"])
            self.assertEqual(signal.SIG_IGN, signal.getsignal(signal.SIGINT))
        finally:
            signal.signal(signal.SIGINT, previous)

    def test_non_main_thread_rejects_before_spawn(self) -> None:
        failures = []

        def run() -> None:
            try:
                self._run_fixture([sys.executable, "-B", "-c", "pass"])
            except BaseException as error:
                failures.append(error)

        with mock.patch.object(job_entry.subprocess, "Popen") as popen:
            thread = threading.Thread(target=run)
            thread.start()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(1, len(failures))
        self.assertIsInstance(failures[0], InfrastructureError)
        popen.assert_not_called()

    def test_sigint_during_probe_cleans_group_before_exit_130(self) -> None:
        config = self.root / "sigint-workload.json"
        config.write_text(json.dumps(VALID), encoding="utf-8")
        marker = self.root / "sigint-grandchild.pid"
        child_code = (
            "import pathlib,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(60)']); "
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
        )
        argv_builder = lambda *_args: [sys.executable, "-B", "-c", child_code, str(marker)]

        def sender() -> None:
            self._wait_for_file(marker)
            os.kill(os.getpid(), signal.SIGINT)

        thread = threading.Thread(target=sender, daemon=True)
        thread.start()
        output = io.StringIO()
        with mock.patch.object(job_entry, "_preflight_child_argv", side_effect=argv_builder):
            code = main(
                ["--config", str(config)],
                layout=self.layout,
                environ={},
                runner=lambda *_args, **_kwargs: self.fail("runner started after SIGINT"),
                stdout=output,
            )
        thread.join(3)
        self.assertEqual(130, code)
        self._assert_gone(int(marker.read_text(encoding="utf-8")))

    def test_nonzero_child_is_runtime_exit_three_and_never_calls_runner(self) -> None:
        config = self.root / "workload.json"
        config.write_text(json.dumps(VALID), encoding="utf-8")
        output = io.StringIO()
        with mock.patch.object(
            job_entry, "_preflight_child_argv",
            return_value=[sys.executable, "-B", "-c", "raise SystemExit(9)"],
        ):
            code = main(
                ["--config", str(config)],
                layout=self.layout,
                environ={},
                runner=lambda *_args, **_kwargs: self.fail("runner started after failed probe"),
                stdout=output,
            )
        self.assertEqual(3, code)
        self.assertEqual("error", json.loads(output.getvalue().splitlines()[-1])["status"])

    def test_expired_main_deadline_never_spawns_probe_or_runner(self) -> None:
        config = self.root / "short-workload.json"
        config.write_text(json.dumps(dict(VALID, deadline_seconds=14)), encoding="utf-8")
        output = io.StringIO()
        with mock.patch.object(job_entry.subprocess, "Popen") as popen:
            code = main(
                ["--config", str(config)],
                layout=self.layout,
                environ={},
                runner=lambda *_args, **_kwargs: self.fail("runner started without probe budget"),
                clock=lambda: 100.0,
                stdout=output,
            )
        self.assertEqual(3, code)
        popen.assert_not_called()


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layout = _layout(self.root)
        self.config = self.root / "workload.json"
        self.config.write_text(json.dumps(VALID), encoding="utf-8")
        self.calls = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _runner(self, status: str):
        def run(config, **kwargs):
            self.calls.append((config, kwargs))
            return {"status": status, "run_id": config["run_id"]}

        return run

    def _main(self, runner, environ=None, clock=None) -> tuple:
        output = io.StringIO()
        def direct_test_process(argv, **_kwargs):
            payload = json.loads(argv[-1])
            return job_entry.export_preflight(self.layout, payload["run_id"])

        context = (
            mock.patch.object(job_entry, "_run_preflight_process", side_effect=direct_test_process)
            if not POSIX
            else nullcontext()
        )
        with context:
            code = main(
                ["--config", str(self.config)],
                layout=self.layout,
                environ={"HF_TOKEN": "hf_value"} if environ is None else environ,
                runner=runner,
                clock=clock or time.monotonic,
                stdout=output,
            )
        return code, output.getvalue()

    def test_complete_and_partial_exit_codes(self) -> None:
        self.assertEqual(self._main(self._runner("complete"))[0], 0)
        self.assertEqual(self._main(self._runner("partial"))[0], 1)

    def test_scenario_workloads_pick_the_suite_checkpoint_and_other_modes_keep_the_default(self) -> None:
        self._main(self._runner("complete"))
        self.assertEqual("libero_object", self.calls[-1][1]["model_factory"]._suite)
        scenario = {"schema_version": 1, "mode": "scenario-smoke", "run_id": "scn-smoke-1",
                    "deadline_seconds": 1500}
        self.config.write_text(json.dumps(scenario), encoding="utf-8")
        self._main(self._runner("complete"))
        self.assertEqual("libero_10", self.calls[-1][1]["model_factory"]._suite)
        self.config.write_text(json.dumps(dict(scenario, suite="libero_object")), encoding="utf-8")
        self._main(self._runner("complete"))
        self.assertEqual("libero_object", self.calls[-1][1]["model_factory"]._suite)

    def test_repeated_preflights_use_unique_directories(self) -> None:
        self._main(self._runner("complete"))
        self._main(self._runner("complete"))
        self.assertEqual(len(list(self.layout.export_root.glob(".preflight-pilot-1-*"))), 2)

    def test_raw_io_errors_from_the_runner_are_runtime_errors(self) -> None:
        def broken(config, **kwargs):
            raise OSError(5, "Input/output error")

        code, output = self._main(broken)
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(output.splitlines()[-1]), {"status": "error", "error": "OSError"})

    def test_runner_receives_production_wiring_and_token_scanning_exporter(self) -> None:
        self._main(self._runner("complete"))
        config, kwargs = self.calls[0]
        self.assertEqual(config, VALID)
        self.assertEqual(kwargs["paths"].work_root, self.layout.work_root)
        self.assertEqual(kwargs["paths"].export_root, self.layout.export_root)
        self.assertIsInstance(kwargs["model_factory"], ProductionModelFactory)
        self.assertEqual(kwargs["exporter"].inner.keywords["secret_values"], ("hf_value",))
        evaluator = kwargs["evaluator_factory"](timeout_seconds=5, log_root=self.root / "logs")
        self.assertNotIn("HF_TOKEN", evaluator.evaluator._env)

    def test_preflight_time_consumes_original_deadline_before_readiness(self) -> None:
        now = [100.0]
        readiness_deadlines = []

        class Model:
            def start(self):
                pass

            def wait_ready(self, *, deadline):
                readiness_deadlines.append(deadline)

            def check_alive(self):
                pass

            def close(self):
                pass

        def actual_runner(config, **kwargs):
            return run_workload(
                config,
                paths=WorkloadPaths(
                    kwargs["paths"].project_root,
                    kwargs["paths"].upstream_root,
                    kwargs["paths"].work_root,
                    kwargs["paths"].export_root,
                ),
                model_factory=lambda **_fields: Model(),
                evaluator_factory=lambda **_fields: lambda *_args, **_kwargs: None,
                exporter=lambda *_args, **_kwargs: {"files": []},
                clock=lambda: now[0],
                absolute_deadline=kwargs["absolute_deadline"],
            )

        def elapsed_preflight(layout, run_id, **_kwargs):
            job_entry.export_preflight(layout, run_id)
            now[0] = 500.0

        with mock.patch.object(job_entry, "bounded_export_preflight", side_effect=elapsed_preflight):
            code, _ = self._main(actual_runner, clock=lambda: 100.0)
        self.assertEqual(1, code)
        self.assertEqual([2486.0], readiness_deadlines)

    def test_missing_token_scans_nothing(self) -> None:
        self._main(self._runner("complete"), environ={})
        self.assertEqual(self.calls[0][1]["exporter"].inner.keywords["secret_values"], ())

    def test_rejected_configuration_does_not_run(self) -> None:
        self.config.write_text("{}", encoding="utf-8")
        code, output = self._main(self._runner("complete"))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["status"], "rejected")
        self.assertEqual(self.calls, [])

    def test_runner_contract_errors_are_reported_not_raised(self) -> None:
        def rejected(config, **kwargs):
            raise JobRuntimeError("workload run and export destinations must be new")

        code, output = self._main(rejected)
        self.assertEqual(code, 3)
        lines = [json.loads(line) for line in output.splitlines()]
        self.assertEqual(lines[0]["event"], "workload_start")
        self.assertEqual(lines[-1]["status"], "error")

    def test_reporting_exporter_logs_summary_and_outcome(self) -> None:
        run_root = self.root / "run"
        run_root.mkdir()
        (run_root / "workload_summary.json").write_text(
            '{"status": "complete", "stop_reason": "completed", "unexpected": "hf_secretish"}', encoding="utf-8")
        events = []

        def record(event, **fields):
            events.append((event, fields))

        ok = job_entry.reporting_exporter(lambda *a, **k: {"files": [1, 2], "status": "complete"}, record)
        ok(run_root, self.root / "out", status="complete", cleanup_confirmed=True)
        self.assertEqual([e for e, _ in events], ["workload_finished", "export_start", "export_done"])
        logged = events[0][1]["summary"]
        self.assertEqual(logged["status"], "complete")
        self.assertEqual(logged["stop_reason"], "completed")
        self.assertNotIn("unexpected", logged)
        self.assertEqual(events[-1][1]["files"], 2)

        events.clear()

        def failing(*_args, **_kwargs):
            raise JobRuntimeError("source evidence changed during open")

        with self.assertRaises(JobRuntimeError):
            job_entry.reporting_exporter(failing, record)(run_root, self.root / "out", status="partial")
        self.assertEqual(events[-1][0], "export_failed")
        self.assertIn("changed during open", events[-1][1]["message"])

    def test_export_preflight_publishes_probe_before_running(self) -> None:
        self._main(self._runner("complete"))
        (probe,) = self.layout.export_root.glob(".preflight-pilot-1-*")
        self.assertTrue((probe / "manifest.json").is_file())
        self.assertEqual((probe / "probe.txt").read_text(encoding="utf-8"), "faultline export preflight\n")
        self.assertEqual(len(self.calls), 1)

    def test_parent_does_not_touch_remote_export_root_before_bounded_probe(self) -> None:
        events = []

        class RemoteRoot:
            def _unexpected_parent_io(self, *_args, **_kwargs):
                events.append("parent-remote-io")
                raise AssertionError("parent touched remote export root")

            mkdir = stat = lstat = exists = is_dir = _unexpected_parent_io

            def __str__(self):
                return str(self.layout.export_root)

            def __fspath__(self):
                return str(self.layout.export_root)

        remote = RemoteRoot()
        remote.layout = self.layout
        layout = ImageLayout(
            project_root=self.layout.project_root,
            upstream_root=self.layout.upstream_root,
            simulator_source=self.layout.simulator_source,
            model_python=self.layout.model_python,
            evaluator=self.layout.evaluator,
            work_root=self.layout.work_root,
            hf_home=self.layout.hf_home,
            export_root=remote,
        )

        def probe(*_args, **_kwargs):
            events.append("probe")

        def runner(*_args, **_kwargs):
            events.append("runner")
            return {"status": "complete", "run_id": "pilot-1"}

        with mock.patch.object(job_entry, "bounded_export_preflight", side_effect=probe):
            main(
                ["--config", str(self.config)],
                layout=layout,
                environ={},
                runner=runner,
                stdout=io.StringIO(),
            )
        self.assertEqual(["probe", "runner"], events)

    def test_failed_export_preflight_stops_before_runner(self) -> None:
        from unittest import mock

        with mock.patch.object(job_entry, "bounded_export_preflight",
                               side_effect=JobRuntimeError("export preflight failed")):
            code, output = self._main(self._runner("complete"))
        self.assertEqual(code, 3)
        lines = [json.loads(line) for line in output.splitlines()]
        self.assertEqual(lines[-2]["event"], "export_preflight_failed")
        self.assertEqual(lines[-1]["status"], "error")
        self.assertEqual(self.calls, [])

    def test_m6_modes_run_their_evaluators_with_single_threaded_blas(self) -> None:
        m6_config = {"schema_version": 1, "mode": "m6-smoke", "run_id": "m6-smoke-1", "deadline_seconds": 1200}
        self.config.write_text(json.dumps(m6_config), encoding="utf-8")
        self._main(self._runner("complete"))
        _config, kwargs = self.calls[0]
        evaluator = kwargs["evaluator_factory"](timeout_seconds=5, log_root=self.root / "logs")
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            self.assertEqual("1", evaluator.evaluator._env[name])

    def test_other_modes_keep_the_evaluator_environment_unchanged(self) -> None:
        self._main(self._runner("complete"))
        _config, kwargs = self.calls[0]
        evaluator = kwargs["evaluator_factory"](timeout_seconds=5, log_root=self.root / "logs")
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            self.assertNotIn(name, evaluator.evaluator._env)

    def test_evaluator_wrapper_reports_start_and_failure(self) -> None:
        events = []

        def record(event, **fields):
            events.append((event, fields))

        build = job_entry.evaluator_factory(self.layout, {}, record)
        run = build(timeout_seconds=5, log_root=self.root / "logs")
        with self.assertRaises(Exception):
            run(["vla-eval", "run", "--config", str(self.root / "stage.yaml")], cwd=self.root)
        self.assertEqual([e for e, _ in events], ["evaluator_start", "evaluator_failed"])
        self.assertEqual(events[0][1]["config"], "stage.yaml")

    def test_progress_printer_emits_one_json_line_per_event(self) -> None:
        output = io.StringIO()
        job_entry.progress_printer(output)("prefetch_done", elapsed_seconds=1.5)
        record = json.loads(output.getvalue())
        self.assertEqual(record["event"], "prefetch_done")
        self.assertEqual(record["elapsed_seconds"], 1.5)
        self.assertIn("time", record)

    def test_alias_token_is_also_scanned(self) -> None:
        self._main(self._runner("complete"), environ={"HUGGING_FACE_HUB_TOKEN": "alias"})
        self.assertEqual(self.calls[0][1]["exporter"].inner.keywords["secret_values"], ("alias",))

    def test_keyboard_interrupt_maps_to_sigint_code(self) -> None:
        def interrupted(config, **kwargs):
            raise KeyboardInterrupt

        self.assertEqual(self._main(interrupted)[0], 130)

    @unittest.skipUnless(POSIX, "real SIGTERM delivery")
    def test_sigterm_maps_to_143_and_restores_handler(self) -> None:
        before = signal.getsignal(signal.SIGTERM)

        def terminated(config, **kwargs):
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(5)
            self.fail("SIGTERM was not translated")

        self.assertEqual(self._main(terminated)[0], 143)
        self.assertIs(signal.getsignal(signal.SIGTERM), before)

    def test_termination_latch_ignores_repeats(self) -> None:
        latch = job_entry._TerminationLatch()
        with self.assertRaises(KeyboardInterrupt):
            latch(signal.SIGTERM, None)
        latch(signal.SIGTERM, None)
        self.assertTrue(latch.received)

    def test_entrypoint_script_matches_image_and_job_contract(self) -> None:
        dockerfile = (ROOT / "deploy" / "serverless" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("/opt/robot-debug/scripts/run_serverless_workload.py", dockerfile)
        self.assertTrue((ROOT / "scripts" / "run_serverless_workload.py").is_file())


if __name__ == "__main__":
    unittest.main()
