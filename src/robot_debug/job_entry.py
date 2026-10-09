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
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
import uuid

from .job_model import ModelProcess
from .job_process import DirectEvaluator, InfrastructureError, close_owned_process_group
from .job_runtime import JobRuntimeError, export_closed_evidence, validate_workload_config


MAX_WORKLOAD_BYTES = 64 * 1024
PREFETCH_CAP_SECONDS = 1200.0
POST_PREFETCH_RESERVE_SECONDS = 600.0
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
EXIT_SIGINT = 130
EXIT_SIGTERM = 143


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


def model_server_argv(layout: ImageLayout, port: int = MODEL_PORT) -> List[str]:
    """Same server invocation as the historical ``model-launch.sh``."""

    return [
        layout.model_python.as_posix(),
        (layout.upstream_root / "src" / "vla_eval" / "model_servers" / "lerobot.py").as_posix(),
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


def write_provenance(run_root: Path, layout: ImageLayout, resolution: Mapping[str, Any]) -> None:
    provenance = {
        "schema_version": 1,
        "backend": "nebius-serverless",
        "upstream_revision": UPSTREAM_REVISION,
        "upstream_revision_source": "verified during image build",
        "model_resolution": resolution,
        "simulator_packages": _read_json(layout.project_root / "simulator-packages.json"),
        "model_packages": _read_json(layout.project_root / "model-packages.json"),
        "model_server_argv": model_server_argv(layout)[1:],
        "python": sys.version.split()[0],
    }
    target = run_root / "provenance.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(provenance, handle, sort_keys=True, indent=2)
        handle.write("\n")


class ProductionModelFactory:
    """Prefetch pinned inputs within the deadline, then describe the server."""

    def __init__(
        self,
        layout: ImageLayout,
        *,
        base_env: Mapping[str, str],
        deadline: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._layout = layout
        self._base_env = dict(base_env)
        self._deadline = deadline
        self._clock = clock

    def __call__(self, *, log_root: Path) -> ModelProcess:
        log_root = Path(log_root)
        run_root = log_root.parent
        budget = self._deadline - self._clock() - POST_PREFETCH_RESERVE_SECONDS
        resolution = prefetch_models(
            self._layout,
            base_env=self._base_env,
            output=run_root / "model-resolution.json",
            log_root=log_root,
            timeout_seconds=min(PREFETCH_CAP_SECONDS, budget),
        )
        write_provenance(run_root, self._layout, resolution)
        return ModelProcess(
            argv=model_server_argv(self._layout),
            cwd=self._layout.upstream_root,
            env=model_environment(self._layout, self._base_env),
            log_root=log_root,
            port=MODEL_PORT,
        )


def evaluator_factory(
    layout: ImageLayout, base_env: Mapping[str, str]
) -> Callable[..., DirectEvaluator]:
    env = evaluator_environment(layout, base_env)

    def build(*, timeout_seconds: float, log_root: Path) -> DirectEvaluator:
        return DirectEvaluator(
            executable=layout.evaluator,
            timeout_seconds=timeout_seconds,
            env=env,
            log_root=log_root,
        )

    return build


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
        for root in (layout.work_root, layout.export_root):
            root.mkdir(parents=True, exist_ok=True)
    except OSError:
        print(json.dumps({"status": "rejected", "error": "work or export root unavailable"}), file=stdout)
        return EXIT_CONFIG

    secrets = tuple(sorted({environ[name] for name in TOKEN_ALIASES if environ.get(name)}))
    exporter = functools.partial(export_closed_evidence, secret_values=secrets)
    latch = _TerminationLatch()
    previous = signal.signal(signal.SIGTERM, latch)
    try:
        summary = runner(
            config,
            paths=WorkloadPaths(
                project_root=layout.project_root,
                upstream_root=layout.upstream_root,
                work_root=layout.work_root,
                export_root=layout.export_root,
            ),
            model_factory=ProductionModelFactory(
                layout, base_env=environ, deadline=deadline, clock=clock
            ),
            evaluator_factory=evaluator_factory(layout, environ),
            exporter=exporter,
            clock=clock,
        )
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "run_id": config["run_id"]}), file=stdout)
        return EXIT_SIGTERM if latch.received else EXIT_SIGINT
    except JobRuntimeError as error:
        print(json.dumps({"status": "rejected", "error": str(error)}), file=stdout)
        return EXIT_CONFIG
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
