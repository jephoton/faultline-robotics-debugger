"""Production wiring for one Serverless Job workload inside the pinned image."""

from __future__ import annotations

from dataclasses import dataclass
import functools
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
import uuid

from .job_model import ModelProcess
from .job_process import DirectEvaluator, InfrastructureError, close_owned_process_group
from .job_runtime import JobRuntimeError, export_closed_evidence, validate_workload_config


MAX_WORKLOAD_BYTES = 64 * 1024
PREFETCH_CAP_SECONDS = 1200.0
POST_PREFETCH_RESERVE_SECONDS = 600.0
EXPORT_PREFLIGHT_CAP_SECONDS = 30.0
PREFLIGHT_CLEANUP_RESERVE_SECONDS = 14.0
MODEL_PORT = 8000
UPSTREAM_REVISION = "35f1200eb15608aa898f727a3722f7eef889c6cd"
TOKEN_VARIABLE = "HF_TOKEN"
TOKEN_ALIASES = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
_SECRET_NAME = re.compile(
    r"(?:^|_)(?:TOKEN|SECRETS?|PASSWORD|PASSWD|PASSPHRASE|CREDENTIALS?|KEY|APIKEY|AUTH(?:ORIZATION)?)(?:_|$)",
    re.IGNORECASE,
)
# Inherited overrides that could redirect, disable or bypass the private cache.
_HF_OVERRIDES = (
    "HF_HUB_OFFLINE",
    "TRANSFORMERS_OFFLINE",
    "HF_ENDPOINT",
    "HF_HUB_CACHE",
    "HUGGINGFACE_HUB_CACHE",
    "TRANSFORMERS_CACHE",
    "HF_HOME",
)

EXIT_COMPLETE = 0
EXIT_PARTIAL = 1
EXIT_CONFIG = 2
EXIT_RUNTIME = 3
EXIT_SIGINT = 130
EXIT_SIGTERM = 143

# Workload summary fields safe to echo into Job logs before the export secret scan.
_SUMMARY_LOG_FIELDS = ("status", "stop_reason", "mode", "run_id", "elapsed_seconds", "pilot_outcomes")


@dataclass(frozen=True)
class ImageLayout:
    """Fixed paths in the serverless image; tests substitute temporary ones."""

    project_root: Path = Path("/opt/robot-debug")
    upstream_root: Path = Path("/opt/upstream")
    simulator_source: Path = Path("/workspace/src")
    model_python: Path = Path("/opt/model-env/bin/python")
    evaluator: Path = Path("/opt/conda/envs/libero/bin/vla-eval")
    work_root: Path = Path("/tmp/faultline-work")
    hf_home: Path = Path("/tmp/faultline-hf")
    export_root: Path = Path("/persistent/faultline-runs")
    # Optional private injected file for the m5b mode (gzip candidate JSON).
    external_reset_file: Path = Path("/etc/faultline/external-reset.json.gz")


def load_workload(path: Path) -> Dict[str, Any]:
    """Read and validate a bounded workload JSON file."""

    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_WORKLOAD_BYTES + 1)
    except OSError as error:
        raise JobRuntimeError("workload file could not be read") from error
    if len(payload) > MAX_WORKLOAD_BYTES:
        raise JobRuntimeError("workload file exceeds 64 KiB")
    try:
        config = json.loads(payload.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise JobRuntimeError("workload file is not valid JSON") from error
    return validate_workload_config(config)


def child_environment(base: Mapping[str, str], **overrides: str) -> Dict[str, str]:
    """Copy the base environment without secret-like variables, then override."""

    env = {key: value for key, value in base.items() if not _SECRET_NAME.search(key)}
    env.update(overrides)
    return env


SERVER_VARIANTS = ("upstream", "faultline")


def faultline_server_script(layout: ImageLayout) -> Path:
    """The batch-capable, instrumented server shipped with the project scripts."""

    return layout.project_root / "scripts" / "model_servers" / "faultline_groot_server.py"


def model_server_argv(
    layout: ImageLayout,
    port: int = MODEL_PORT,
    *,
    server: str = "upstream",
    max_batch_size: int = 1,
    timing_log: Optional[Path] = None,
) -> List[str]:
    """Same server invocation as the historical ``model-launch.sh``.

    ``server="faultline"`` swaps in the instrumented batch server and appends
    ``--args.max_batch_size`` (and ``--args.timing_log`` when given); the model
    flags are shared. The default is byte-identical to the historical argv.
    """

    if server not in SERVER_VARIANTS:
        raise ValueError("unknown model server variant")
    if type(max_batch_size) is not int or not 1 <= max_batch_size <= 64:
        raise ValueError("max_batch_size must be an integer from 1 to 64")
    if server == "upstream" and (max_batch_size != 1 or timing_log is not None):
        raise ValueError("batching and timing logs need the faultline server variant")
    argv = _model_flags(layout, port, server)
    if server == "faultline":
        argv.append("--args.max_batch_size={}".format(max_batch_size))
        if timing_log is not None:
            text = Path(timing_log).as_posix()
            if not text.startswith("/") or any(ord(ch) < 33 or ord(ch) == 127 for ch in text):
                raise ValueError("timing_log must be an absolute path without spaces or control characters")
            argv.append("--args.timing_log={}".format(text))
    return argv


def model_flags_for_scripts(layout: ImageLayout, max_batch_size: int = 1) -> List[str]:
    """The ``--args.*`` flags of the faultline server, without interpreter, script or port."""

    return model_server_argv(layout, server="faultline", max_batch_size=max_batch_size)[3:]


def _model_flags(layout: ImageLayout, port: int, server: str) -> List[str]:
    script = (
        (layout.upstream_root / "src" / "vla_eval" / "model_servers" / "lerobot.py")
        if server == "upstream"
        else faultline_server_script(layout)
    )
    return [
        layout.model_python.as_posix(),
        script.as_posix(),
        "--port={}".format(port),
        "--args.device=cuda",
        "--args.policy_type=groot",
        "--args.checkpoint=nvidia/gr00t17-lerobot-libero_object-640",
        "--args.state_key=observation.state",
        "--args.chunk_size=null",
        '--args.image_keys={"agentview":"observation.images.image","wrist":"observation.images.wrist_image"}',
        '--args.policy_kwargs={"base_model_path":"nvidia/GR00T-N1.7-3B"}',
    ]


def _model_base_environment(layout: ImageLayout, base: Mapping[str, str]) -> Dict[str, str]:
    env = child_environment(base)
    for name in _HF_OVERRIDES + ("PYTHONPATH",):
        env.pop(name, None)
    env.update({"HF_HOME": str(layout.hf_home), "HF_HUB_CACHE": str(layout.hf_home / "hub")})
    return env


def hf_token(base: Mapping[str, str]) -> Optional[str]:
    for name in TOKEN_ALIASES:
        value = base.get(name)
        if value:
            return value
    return None


def model_environment(layout: ImageLayout, base: Mapping[str, str]) -> Dict[str, str]:
    env = _model_base_environment(layout, base)
    env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    return env


def evaluator_environment(layout: ImageLayout, base: Mapping[str, str]) -> Dict[str, str]:
    pythonpath = "{}:{}".format(layout.project_root / "src", layout.simulator_source)
    return child_environment(base, PYTHONPATH=pythonpath)


def prefetch_models(
    layout: ImageLayout,
    *,
    base_env: Mapping[str, str],
    output: Path,
    log_root: Path,
    timeout_seconds: float,
) -> Dict[str, Any]:
    """Run the pinned prefetch as one owned process group with a hard timeout."""

    if os.name != "posix":
        raise InfrastructureError("model prefetch requires POSIX process groups")
    if not timeout_seconds > 0:
        raise InfrastructureError("no time remains for model prefetch")
    env = _model_base_environment(layout, base_env)
    token = hf_token(base_env)
    if token:
        env[TOKEN_VARIABLE] = token
    argv = [
        str(layout.model_python),
        "-I",
        str(layout.project_root / "scripts" / "serverless_prefetch.py"),
        "--output",
        str(output),
    ]
    log_root.mkdir(parents=True, exist_ok=True)
    ident = "prefetch-" + uuid.uuid4().hex
    with (log_root / (ident + ".stdout.log")).open("xb") as stdout, (
        log_root / (ident + ".stderr.log")
    ).open("xb") as stderr:
        process = subprocess.Popen(
            argv,
            cwd=str(layout.project_root),
            env=env,
            shell=False,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
        )
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except BaseException:
            close_owned_process_group(process, process.pid)
            raise
        close_owned_process_group(process, process.pid)
    if return_code != 0:
        raise InfrastructureError("model prefetch failed")
    try:
        resolution = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise InfrastructureError("model prefetch resolution is unreadable") from error
    return resolution


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_provenance(
    run_root: Path,
    layout: ImageLayout,
    resolution: Mapping[str, Any],
    server_argv: Optional[Sequence[str]] = None,
) -> None:
    provenance = {
        "schema_version": 1,
        "backend": "nebius-serverless",
        "upstream_revision": UPSTREAM_REVISION,
        "upstream_revision_source": "verified during image build",
        "model_resolution": resolution,
        "simulator_packages": _read_json(layout.project_root / "simulator-packages.json"),
        "model_packages": _read_json(layout.project_root / "model-packages.json"),
        "model_server_argv": list(server_argv) if server_argv is not None else model_server_argv(layout)[1:],
        "python": sys.version.split()[0],
    }
    target = run_root / "provenance.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(provenance, handle, sort_keys=True, indent=2)
        handle.write("\n")


Progress = Callable[..., None]


def _no_progress(_event: str, **_fields: Any) -> None:
    return None


def progress_printer(stdout: Any) -> Progress:
    """One JSON line per lifecycle event, so Job logs show how far a run got."""

    def emit(event: str, **fields: Any) -> None:
        record = {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event}
        record.update(fields)
        print(json.dumps(record, sort_keys=True, default=str), file=stdout, flush=True)

    return emit


def _require_posix(what: str) -> None:
    if os.name != "posix":
        raise InfrastructureError("{} requires POSIX process groups".format(what))


class ProductionModelFactory:
    """Prefetch pinned inputs within the deadline, then describe the server."""

    def __init__(
        self,
        layout: ImageLayout,
        *,
        base_env: Mapping[str, str],
        deadline: float,
        clock: Callable[[], float] = time.monotonic,
        progress: Progress = _no_progress,
    ) -> None:
        self._layout = layout
        self._base_env = dict(base_env)
        self._deadline = deadline
        self._clock = clock
        self._progress = progress
        self._prefetched = False

    def __call__(
        self,
        *,
        log_root: Path,
        server: str = "upstream",
        max_batch_size: int = 1,
        timing_log: Optional[Path] = None,
    ) -> ModelProcess:
        """Describe one model server start; the first call prefetches, later calls reuse it.

        The variant options are validated before any prefetch so a bad phase
        description cannot spend time or write provenance.
        """

        argv = model_server_argv(
            self._layout, server=server, max_batch_size=max_batch_size, timing_log=timing_log
        )
        log_root = Path(log_root)
        self.ensure_prefetched(log_root, argv=argv)
        return ModelProcess(
            argv=argv,
            cwd=self._layout.upstream_root,
            env=model_environment(self._layout, self._base_env),
            log_root=log_root,
            port=MODEL_PORT,
        )

    def run_parity(
        self,
        *,
        output: Path,
        log_root: Path,
        max_batch_size: int,
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        """Run the batch parity check in the model environment; returns its verdict.

        The check exits 0 (pass) or 1 (fail) after writing ``output``; any other
        outcome, or a missing or unreadable verdict, is an infrastructure error.
        """

        _require_posix("parity check")
        log_root = Path(log_root)
        argv = model_server_argv(self._layout, server="faultline", max_batch_size=max_batch_size)
        self.ensure_prefetched(log_root, argv=argv)
        if not timeout_seconds > 0:
            raise InfrastructureError("no time remains for the parity check")
        command = [
            str(self._layout.model_python),
            str(self._layout.project_root / "scripts" / "model_servers" / "groot_batch_parity.py"),
            *model_flags_for_scripts(self._layout, max_batch_size),
            "--output={}".format(Path(output).as_posix()),
        ]
        log_root.mkdir(parents=True, exist_ok=True)
        ident = "parity-" + uuid.uuid4().hex
        with (log_root / (ident + ".stdout.log")).open("xb") as stdout, (
            log_root / (ident + ".stderr.log")
        ).open("xb") as stderr:
            process = subprocess.Popen(
                command,
                cwd=str(self._layout.upstream_root),
                env=model_environment(self._layout, self._base_env),
                shell=False,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
            )
            try:
                return_code = process.wait(timeout=timeout_seconds)
            except BaseException:
                close_owned_process_group(process, process.pid)
                raise
            close_owned_process_group(process, process.pid)
        if return_code not in (0, 1):
            raise InfrastructureError("parity check crashed")
        try:
            verdict = json.loads(Path(output).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise InfrastructureError("parity verdict is unreadable") from error
        if not isinstance(verdict, dict):
            raise InfrastructureError("parity verdict is malformed")
        if (return_code == 0) != (verdict.get("passed") is True):
            raise InfrastructureError("parity verdict disagrees with the exit status")
        return verdict

    def ensure_prefetched(self, log_root: Path, *, argv: Optional[Sequence[str]] = None) -> None:
        """Prefetch the pinned inputs and write provenance, once per Job."""

        if self._prefetched:
            return
        log_root = Path(log_root)
        run_root = log_root.parent
        budget = self._deadline - self._clock() - POST_PREFETCH_RESERVE_SECONDS
        self._progress("prefetch_start", timeout_seconds=round(min(PREFETCH_CAP_SECONDS, budget), 1))
        started = self._clock()
        try:
            resolution = prefetch_models(
                self._layout,
                base_env=self._base_env,
                output=run_root / "model-resolution.json",
                log_root=log_root,
                timeout_seconds=min(PREFETCH_CAP_SECONDS, budget),
            )
        except BaseException as error:
            self._progress("prefetch_failed", error=type(error).__name__,
                           elapsed_seconds=round(self._clock() - started, 1))
            raise
        self._progress("prefetch_done", elapsed_seconds=round(self._clock() - started, 1),
                       repositories=resolution.get("repositories"))
        write_provenance(
            run_root, self._layout, resolution,
            server_argv=None if argv is None else list(argv)[1:],
        )
        self._prefetched = True


def evaluator_factory(
    layout: ImageLayout, base_env: Mapping[str, str], progress: Progress = _no_progress
) -> Callable[..., Any]:
    env = evaluator_environment(layout, base_env)

    def build(*, timeout_seconds: float, log_root: Path, cancel: Optional[threading.Event] = None) -> Any:
        evaluator = DirectEvaluator(
            executable=layout.evaluator,
            timeout_seconds=timeout_seconds,
            env=env,
            log_root=log_root,
            **({} if cancel is None else {"cancel": cancel}),
        )

        def run(command: Sequence[str], **kwargs: Any) -> Any:
            config = Path(command[-1]).name if command else ""
            progress("evaluator_start", config=config, timeout_seconds=round(timeout_seconds, 1))
            started = time.monotonic()
            try:
                result = evaluator(command, **kwargs)
            except BaseException as error:
                progress("evaluator_failed", config=config, error=type(error).__name__,
                         elapsed_seconds=round(time.monotonic() - started, 1))
                raise
            progress("evaluator_done", config=config, returncode=getattr(result, "returncode", None),
                     elapsed_seconds=round(time.monotonic() - started, 1))
            return result

        run.evaluator = evaluator  # type: ignore[attr-defined]
        return run

    return build


def reporting_exporter(exporter: Callable[..., Dict[str, Any]], progress: Progress) -> Callable[..., Dict[str, Any]]:
    """Log the workload summary before export and the export outcome after."""

    def export(source_root: Any, destination_root: Any, **kwargs: Any) -> Dict[str, Any]:
        try:
            loaded = json.loads((Path(source_root) / "workload_summary.json").read_text(encoding="utf-8"))
            summary = {key: loaded.get(key) for key in _SUMMARY_LOG_FIELDS} if isinstance(loaded, dict) else None
        except (OSError, ValueError):
            summary = None
        progress("workload_finished", summary=summary)
        progress("export_start", status=kwargs.get("status"))
        try:
            manifest = exporter(source_root, destination_root, **kwargs)
        except BaseException as error:
            progress("export_failed", error=type(error).__name__, message=str(error)[:200])
            raise
        progress("export_done", files=len(manifest.get("files", ())), status=manifest.get("status"))
        return manifest

    export.inner = exporter  # type: ignore[attr-defined]
    return export


def export_preflight(layout: ImageLayout, run_id: str) -> None:
    """Prove the export destination works before spending time on the model.

    Exports one small file through the real exporter to a unique sibling
    ``.preflight-<run_id>-<random>`` directory, so a broken bucket mount fails
    within the first minute instead of after the whole workload, and a failed
    probe never blocks a retry. The in-container re-read may be served from a
    mount cache; the workstation downloader re-hashes every object against the
    manifest, which is the authoritative check.
    """

    layout.export_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(layout.work_root)) as probe:
        Path(probe, "probe.txt").write_text("faultline export preflight\n", encoding="utf-8")
        export_closed_evidence(
            probe,
            layout.export_root / ".preflight-{}-{}".format(run_id, uuid.uuid4().hex[:8]),
            status="complete",
            cleanup_confirmed=True,
        )


_EXPORT_PREFLIGHT_PROGRAM = (
    "import json,sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from robot_debug.job_entry import ImageLayout, export_preflight\n"
    "data=json.loads(sys.argv[2])\n"
    "layout=ImageLayout(work_root=Path(data['work_root']), export_root=Path(data['export_root']))\n"
    "export_preflight(layout, data['run_id'])\n"
)


def _preflight_child_argv(layout: ImageLayout, run_id: str) -> List[str]:
    """Build the fixed child operation; tests may replace this low-level seam."""

    validated = validate_workload_config(
        {"schema_version": 1, "mode": "pilot", "run_id": run_id, "deadline_seconds": 1}
    )
    payload = {
        "work_root": str(layout.work_root),
        "export_root": str(layout.export_root),
        "run_id": validated["run_id"],
    }
    return [
        sys.executable,
        "-I",
        "-B",
        "-c",
        _EXPORT_PREFLIGHT_PROGRAM,
        str(Path(__file__).resolve().parents[1]),
        json.dumps(payload, sort_keys=True),
    ]


def _run_preflight_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    log_root: Path,
    deadline: float,
    clock: Callable[[], float],
) -> None:
    """Run one owned probe child, retaining private local logs and proving teardown."""

    if os.name != "posix":
        raise InfrastructureError("export preflight requires POSIX process groups")

    def wait_budget() -> float:
        return min(
            EXPORT_PREFLIGHT_CAP_SECONDS,
            deadline - clock() - PREFLIGHT_CLEANUP_RESERVE_SECONDS,
        )

    timeout = wait_budget()
    if timeout <= 0:
        raise InfrastructureError("no time remains for export preflight")
    log_root.mkdir(parents=True, exist_ok=True)
    ident = "export-preflight-" + uuid.uuid4().hex
    stdout_path = log_root / (ident + ".stdout.log")
    stderr_path = log_root / (ident + ".stderr.log")
    stdout_fd = os.open(str(stdout_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        stderr_fd = os.open(str(stderr_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except BaseException:
        os.close(stdout_fd)
        raise

    process = None
    deferred_signal = None
    previous_handlers = {}
    cleanup_uncertain = None

    def defer_launch_signal(signum: int, _frame: object) -> None:
        nonlocal deferred_signal
        if deferred_signal is None:
            deferred_signal = signum

    def close_probe() -> None:
        nonlocal process, cleanup_uncertain
        owned = process
        process = None
        try:
            close_owned_process_group(owned, owned.pid)
        except KeyboardInterrupt:
            raise
        except BaseException as cleanup_error:
            cleanup_uncertain = InfrastructureError("export preflight cleanup could not be confirmed")
            raise cleanup_uncertain from cleanup_error

    def restore_launch_handler(signum: int) -> None:
        if signum not in previous_handlers:
            return
        previous = previous_handlers[signum]
        try:
            signal.signal(signum, previous)
        except KeyboardInterrupt:
            # The interruption may precede the native restoration call.
            if signal.getsignal(signum) is not previous:
                try:
                    signal.signal(signum, previous)
                except BaseException:
                    if cleanup_uncertain is None:
                        raise
            if cleanup_uncertain is None:
                raise
        except BaseException:
            if cleanup_uncertain is None:
                raise

    try:
        with os.fdopen(stdout_fd, "wb") as stdout, os.fdopen(stderr_fd, "wb") as stderr:
            timeout = wait_budget()
            if timeout <= 0:
                raise InfrastructureError("no time remains for export preflight")
            if threading.current_thread() is not threading.main_thread():
                raise InfrastructureError("export preflight launch requires the main thread")
            try:
                try:
                    for signum in (signal.SIGINT, signal.SIGTERM):
                        previous = signal.getsignal(signum)
                        if previous != signal.SIG_IGN:
                            previous_handlers[signum] = signal.signal(signum, defer_launch_signal)
                    process = subprocess.Popen(
                        list(argv),
                        cwd=str(cwd),
                        env={},
                        shell=False,
                        start_new_session=True,
                        stdin=subprocess.DEVNULL,
                        stdout=stdout,
                        stderr=stderr,
                    )
                    if deferred_signal is not None:
                        close_probe()
                finally:
                    try:
                        restore_launch_handler(signal.SIGINT)
                    finally:
                        restore_launch_handler(signal.SIGTERM)
                if deferred_signal is not None:
                    if process is not None:
                        close_probe()
                    signal.raise_signal(deferred_signal)
                    raise InfrastructureError("export preflight interrupted during launch")
                timeout = wait_budget()
                if timeout <= 0:
                    raise subprocess.TimeoutExpired(list(argv), 0)
                return_code = process.wait(timeout=timeout)
                close_probe()
            except KeyboardInterrupt:
                if process is not None:
                    close_probe()
                raise
            except BaseException as error:
                launch_failed = process is None
                if process is not None:
                    close_probe()
                if isinstance(error, InfrastructureError):
                    raise
                if isinstance(error, OSError) and launch_failed:
                    raise
                raise InfrastructureError("export preflight did not complete") from error
    except InfrastructureError:
        raise
    except OSError as error:
        raise InfrastructureError("export preflight process could not be started") from error
    if return_code != 0:
        raise InfrastructureError("export preflight process failed")


def bounded_export_preflight(
    layout: ImageLayout,
    run_id: str,
    *,
    deadline: float,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Run the fixed export probe with the original Job deadline and cleanup reserve."""

    argv = _preflight_child_argv(layout, run_id)
    _run_preflight_process(
        argv,
        cwd=layout.project_root,
        log_root=layout.work_root / "preflight-logs",
        deadline=deadline,
        clock=clock,
    )


def exit_code(summary: Mapping[str, Any]) -> int:
    return EXIT_COMPLETE if summary.get("status") == "complete" else EXIT_PARTIAL


class _TerminationLatch:
    """Translate the first SIGTERM into KeyboardInterrupt; ignore repeats."""

    def __init__(self) -> None:
        self.received = False

    def __call__(self, _signum: int, _frame: object) -> None:
        if self.received:
            return
        self.received = True
        raise KeyboardInterrupt


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    layout: ImageLayout = ImageLayout(),
    environ: Optional[Mapping[str, str]] = None,
    runner: Optional[Callable[..., Dict[str, Any]]] = None,
    clock: Callable[[], float] = time.monotonic,
    stdout: Any = None,
) -> int:
    import argparse

    from .job_workload import WorkloadPaths, run_workload

    parser = argparse.ArgumentParser(description="Run one bounded Faultline Serverless workload.")
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    environ = dict(os.environ if environ is None else environ)
    runner = run_workload if runner is None else runner
    stdout = sys.stdout if stdout is None else stdout

    started = clock()
    try:
        config = load_workload(args.config)
    except JobRuntimeError as error:
        print(json.dumps({"status": "rejected", "error": str(error)}), file=stdout)
        return EXIT_CONFIG
    deadline = started + float(config["deadline_seconds"])
    try:
        layout.work_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        print(json.dumps({"status": "rejected", "error": "work root unavailable"}), file=stdout)
        return EXIT_CONFIG

    secrets = tuple(sorted({environ[name] for name in TOKEN_ALIASES if environ.get(name)}))
    progress = progress_printer(stdout)
    progress("workload_start", run_id=config["run_id"], mode=config["mode"],
             deadline_seconds=config["deadline_seconds"])
    exporter = reporting_exporter(
        functools.partial(export_closed_evidence, secret_values=secrets), progress
    )
    latch = _TerminationLatch()
    previous = signal.signal(signal.SIGTERM, latch)
    try:
        try:
            bounded_export_preflight(
                layout, config["run_id"], deadline=deadline, clock=clock
            )
        except (InfrastructureError, JobRuntimeError, OSError, subprocess.SubprocessError) as error:
            progress("export_preflight_failed", error=type(error).__name__)
            print(json.dumps({"status": "error", "error": "export preflight failed"}), file=stdout)
            return EXIT_RUNTIME
        progress("export_preflight_ok")
        model_factory = ProductionModelFactory(
            layout, base_env=environ, deadline=deadline, clock=clock, progress=progress
        )
        summary = runner(
            config,
            paths=WorkloadPaths(
                project_root=layout.project_root,
                upstream_root=layout.upstream_root,
                work_root=layout.work_root,
                export_root=layout.export_root,
            ),
            model_factory=model_factory,
            evaluator_factory=evaluator_factory(layout, environ, progress),
            exporter=exporter,
            clock=clock,
            absolute_deadline=deadline,
            external_reset_source=layout.external_reset_file,
            parity_runner=model_factory.run_parity,
            progress=progress,
        )
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "run_id": config["run_id"]}), file=stdout)
        return EXIT_SIGTERM if latch.received else EXIT_SIGINT
    except JobRuntimeError as error:
        # Runtime contract failures (existing destinations, export checks) are
        # not configuration rejections; report them distinctly.
        print(json.dumps({"status": "error", "error": str(error)}), file=stdout)
        return EXIT_RUNTIME
    except OSError as error:
        # Raw I/O failures (for example on the bucket mount) must not exit 1,
        # which would read as a partial workload result.
        print(json.dumps({"status": "error", "error": type(error).__name__}), file=stdout)
        return EXIT_RUNTIME
    finally:
        signal.signal(signal.SIGTERM, previous)
    print(json.dumps(summary, sort_keys=True), file=stdout)
    return exit_code(summary)


__all__ = [
    "ImageLayout",
    "ProductionModelFactory",
    "child_environment",
    "evaluator_factory",
    "load_workload",
    "main",
    "model_server_argv",
    "prefetch_models",
]
