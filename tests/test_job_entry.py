from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest

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
        for revision in serverless_prefetch.PINNED_REVISIONS.values():
            self.assertIn(revision, design)


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
            for repo, revision in serverless_prefetch.PINNED_REVISIONS.items():
                self.assertEqual(repositories[repo], {"revision": revision, "pinned": True})
                self.assertEqual(Path(hub.snapshot_download(repo_id=repo, local_files_only=True)).name, revision)
            self.assertEqual(repositories["nvidia/Cosmos-Reason2-2B"], {"revision": cosmos, "pinned": False})
            with self.assertRaises(FileExistsError):
                serverless_prefetch.main(["--output", str(output)], hub=hub)

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
            for repo, revision in serverless_prefetch.PINNED_REVISIONS.items():
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

    def _main(self, runner, environ=None) -> tuple:
        output = io.StringIO()
        code = main(
            ["--config", str(self.config)],
            layout=self.layout,
            environ={"HF_TOKEN": "hf_value"} if environ is None else environ,
            runner=runner,
            stdout=output,
        )
        return code, output.getvalue()

    def test_complete_and_partial_exit_codes(self) -> None:
        self.assertEqual(self._main(self._runner("complete"))[0], 0)
        shutil.rmtree(self.layout.export_root / ".preflight-pilot-1")
        self.assertEqual(self._main(self._runner("partial"))[0], 1)

    def test_reused_run_id_fails_export_preflight(self) -> None:
        self._main(self._runner("complete"))
        self.assertEqual(self._main(self._runner("complete"))[0], 3)
        self.assertEqual(len(self.calls), 1)

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
        (run_root / "workload_summary.json").write_text('{"status": "complete"}', encoding="utf-8")
        events = []

        def record(event, **fields):
            events.append((event, fields))

        ok = job_entry.reporting_exporter(lambda *a, **k: {"files": [1, 2], "status": "complete"}, record)
        ok(run_root, self.root / "out", status="complete", cleanup_confirmed=True)
        self.assertEqual([e for e, _ in events], ["workload_finished", "export_start", "export_done"])
        self.assertEqual(events[0][1]["summary"], {"status": "complete"})
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
        probe = self.layout.export_root / ".preflight-pilot-1"
        self.assertTrue((probe / "manifest.json").is_file())
        self.assertEqual((probe / "probe.txt").read_text(encoding="utf-8"), "faultline export preflight\n")
        self.assertEqual(len(self.calls), 1)

    def test_failed_export_preflight_stops_before_runner(self) -> None:
        from unittest import mock

        with mock.patch.object(job_entry, "export_closed_evidence",
                               side_effect=JobRuntimeError("source evidence changed during open")):
            code, output = self._main(self._runner("complete"))
        self.assertEqual(code, 3)
        lines = [json.loads(line) for line in output.splitlines()]
        self.assertEqual(lines[-2]["event"], "export_preflight_failed")
        self.assertEqual(lines[-1]["status"], "error")
        self.assertEqual(self.calls, [])

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
