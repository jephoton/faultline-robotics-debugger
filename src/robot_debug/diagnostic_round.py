"""Thin adaptive-round adapter over the shared durable M3 scheduler.

The injected evaluator must already own contained process/container lifecycle
handling.  Production containment is intentionally wired later by the driver.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, Callable

from robot_debug.attempt_ledger import AttemptLedger
from robot_debug.round_scheduler import run_schedule


_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_STATUSES = {"valid", "invalid_evidence", "infrastructure_error", "uncertain"}


@dataclass(frozen=True)
class RoundRequest:
    case_id: str
    config_path: Path
    output_dir: Path


@dataclass(frozen=True)
class RoundResult:
    case_id: str
    status: str
    outcome: str | None
    evidence_paths: tuple[str, ...]


@dataclass(frozen=True)
class RoundSummary:
    results: tuple[RoundResult, ...]
    certifying: bool
    stop_reason: str | None
    manifest_hash: str


@dataclass(frozen=True)
class RoundLifecycle:
    """The single scheduler-owned launch/containment boundary for a round."""

    stop_requested: threading.Event
    interrupt_event: threading.Event
    launch_lock: threading.Lock
    request_stop: Callable[[], None]


def run_round(
    requests: tuple[RoundRequest, ...] | list[RoundRequest], *, workers: int,
    launch_cutoff: float, evaluator: Callable[..., Any], ledger_path: Path | str,
    round_root: Path | str, resume: bool = False,
    lifecycle_observer: Callable[[RoundLifecycle], None] | None = None,
    interrupt_event: threading.Event | None = None,
) -> RoundSummary:
    """Run one immutable local round using M3's shared fail-closed scheduler."""
    root = Path(round_root).resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("round_root must be a real directory")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers not in (1, 2, 4):
        raise ValueError("workers must be one of 1, 2, or 4")
    if (isinstance(launch_cutoff, bool) or not isinstance(launch_cutoff, (int, float))
            or not math.isfinite(launch_cutoff) or launch_cutoff <= 0):
        raise ValueError("launch_cutoff must be a finite positive number")
    if not callable(evaluator):
        raise ValueError("evaluator must be callable")
    path = _contained(Path(ledger_path), root, "ledger_path", must_exist=False)
    items = _items(requests, root, allow_existing_outputs=resume)
    case_ids = [item["case_id"] for item in items]
    digest = _manifest_hash(items)
    launches = root / "launches"
    if resume:
        return _resume(path, root, items, digest)
    if path.exists():
        raise ValueError("ledger already exists; resume explicitly or choose a new ledger path")
    try:
        os.mkdir(launches)
    except FileExistsError as error:
        raise ValueError("launches directory already exists; a fresh round already owns this round root") from error
    _contained(launches, root, "launches directory", must_exist=True)

    ledger = AttemptLedger(case_ids)
    summary: dict[str, Any] = {
        "schema_version": 1, "case_ids": case_ids, "items": items,
        "manifest_hash": digest, "launch_cutoff": launch_cutoff,
        "stop_reason": None, "results": [], "valid_count": 0, "in_flight_ids": [],
    }
    started = time.monotonic()
    stop_requested = threading.Event()
    if interrupt_event is None:
        interrupt_event = threading.Event()
    elif not isinstance(interrupt_event, threading.Event):
        raise ValueError("interrupt_event must be a threading.Event")
    launch_lock = threading.Lock()

    def request_stop() -> None:
        with launch_lock:
            stop_requested.set()

    lifecycle = RoundLifecycle(stop_requested, interrupt_event, launch_lock, request_stop)
    if lifecycle_observer is not None:
        lifecycle_observer(lifecycle)

    def elapsed() -> float:
        return time.monotonic() - started

    def save() -> None:
        summary.update(ledger.snapshot())
        _atomic_json(path, summary)

    def item_paths(item: dict[str, Any]) -> tuple[Path, Path]:
        return Path(item["config_path"]), Path(item["output_path"])

    def validate_prepared(item: dict[str, Any], config: Path, output: Path) -> bool:
        # Configs are immutable caller-owned inputs; output must not predate
        # the durable submit intent.
        _contained(config, root, "config_path", must_exist=True)
        _contained(output, root, "output_dir", must_exist=False)
        if output.exists():
            raise ValueError("output_dir already exists before launch")
        output.parent.mkdir(parents=True, exist_ok=True)
        if _sha256(config) != item["config_hash"]:
            raise ValueError("config hash changed after round manifest creation")
        return True

    def prepare_config(_item: dict[str, Any], _config: Path, _output: Path) -> None:
        raise RuntimeError("adaptive round configs must be prepared before scheduling")

    def execute(item: dict[str, Any], config: Path, output: Path, _started: float) -> dict[str, Any]:
        request = RoundRequest(item["case_id"], config, output)
        identity: dict[str, Any] = {}

        def observe(pid: int, container: str) -> None:
            if (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0
                    or not isinstance(container, str) or container != f"vla-eval-{pid}"):
                identity["uncertain"] = True
                return
            identity.update(evaluator_pid=pid, expected_container=container)
            _atomic_json(launches / f"{request.case_id}.json", {
                "schema_version": 1, "case_id": request.case_id,
                "evaluator_pid": pid, "expected_container": container,
            })

        try:
            parameters = inspect.signature(evaluator).parameters.values()
            accepts_lifecycle = ("lifecycle" in inspect.signature(evaluator).parameters
                                 or any(parameter.kind is inspect.Parameter.VAR_KEYWORD
                                        for parameter in parameters))
            raw = evaluator(request, launch_observer=observe,
                            **({"lifecycle": lifecycle} if accepts_lifecycle else {}))
        except subprocess.TimeoutExpired as error:
            record = _record(request, "uncertain", None, (), identity, f"timeout: {error}")
            record["cleanup_confirmed"] = getattr(error, "cleanup_confirmed", False)
            if getattr(error, "cleanup_error", None):
                record["cleanup_error"] = error.cleanup_error
            return record
        except BaseException as error:
            record = _record(request, "infrastructure_error", None, (), identity,
                             f"evaluator: {type(error).__name__}: {error}")
            record["cleanup_confirmed"] = getattr(error, "cleanup_confirmed", False)
            if getattr(error, "cleanup_error", None):
                record["cleanup_error"] = error.cleanup_error
            return record
        if identity.get("uncertain") or "evaluator_pid" not in identity:
            return _record(request, "uncertain", None, (), identity,
                           "launch identity was not confirmed")
        if not isinstance(raw, dict) or raw.get("status") not in _STATUSES:
            return _record(request, "invalid_evidence", None, (), identity,
                           "evaluator returned an invalid record")
        outcome = raw.get("outcome")
        if outcome is not None and not isinstance(outcome, str):
            return _record(request, "invalid_evidence", None, (), identity,
                           "evaluator outcome must be a string or null")
        if raw["status"] == "valid" and outcome not in {"success", "policy_failure"}:
            return _record(request, "invalid_evidence", None, (), identity,
                           "valid evidence requires a certifying policy outcome")
        try:
            checked = tuple(_contained(Path(value), output, "evidence path", must_exist=True)
                            for value in raw.get("evidence_paths", ()))
            if any(not value.is_file() or value.stat().st_size <= 0 for value in checked):
                raise ValueError("evidence paths must be non-empty regular files")
            evidence = tuple(str(value) for value in checked)
        except (TypeError, ValueError) as error:
            return _record(request, "invalid_evidence", None, (), identity, str(error))
        if raw["status"] == "valid" and not evidence:
            return _record(request, "invalid_evidence", None, (), identity,
                           "valid evidence requires at least one artifact")
        return _record(request, raw["status"], outcome, evidence, identity, None)

    run_schedule(items=items, workers=workers, ledger=ledger, summary=summary,
                 elapsed=elapsed, launch_cutoff_seconds=launch_cutoff,
                 stop_requested=stop_requested, interrupt_event=interrupt_event,
                 launch_lock=launch_lock, request_stop=request_stop, save=save,
                 item_paths=item_paths, validate_prepared_artifacts=validate_prepared,
                 prepare_config=prepare_config, execute=execute)
    results = tuple(_round_result(case_id, ledger.attempts[case_id]["result"])
                    for case_id in case_ids if ledger.attempts[case_id]["state"] == "terminal")
    return RoundSummary(results, summary["stop_reason"] is None and len(results) == len(items),
                        summary["stop_reason"], digest)


def _items(
    requests: tuple[RoundRequest, ...] | list[RoundRequest], root: Path, *,
    allow_existing_outputs: bool,
) -> list[dict[str, Any]]:
    if not isinstance(requests, (tuple, list)) or not requests:
        raise ValueError("requests must be a non-empty list or tuple")
    if any(not isinstance(request, RoundRequest) for request in requests):
        raise ValueError("requests must contain RoundRequest values")
    if any(not _CASE_ID.fullmatch(request.case_id) for request in requests):
        raise ValueError("case_id must be a safe filename")
    if len({request.case_id for request in requests}) != len(requests):
        raise ValueError("case_ids must be unique")
    items = []
    outputs: set[Path] = set()
    configs: set[Path] = set()
    for request in requests:
        config = _contained(request.config_path, root, "config_path", must_exist=True)
        output = _contained(request.output_dir, root, "output_dir", must_exist=False)
        if config in configs:
            raise ValueError("config_path paths must be unique")
        configs.add(config)
        if any(output == prior or output.is_relative_to(prior) or prior.is_relative_to(output)
               for prior in outputs):
            raise ValueError("output_dir paths must be unique and non-overlapping")
        outputs.add(output)
        if output.exists() and not allow_existing_outputs:
            raise ValueError("output_dir already exists before launch")
        if _config_output_path(config, root) != output:
            raise ValueError("config output_dir must match RoundRequest.output_dir")
        items.append({"case_id": request.case_id, "config_path": str(config),
                      "output_path": str(output), "config_hash": _sha256(config)})
    return items


def _resume(path: Path, root: Path, items: list[dict[str, Any]], digest: str) -> RoundSummary:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        ledger = AttemptLedger.from_snapshot([item["case_id"] for item in items], saved)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("cannot resume: ledger is malformed") from error
    if saved.get("manifest_hash") != digest or saved.get("items") != items:
        raise ValueError("cannot resume: immutable manifest or config hashes differ")
    authoritative = ledger.snapshot()
    if any(saved.get(field) != value for field, value in authoritative.items()):
        raise ValueError("cannot resume: summary is not authoritative for its ledger")
    states = authoritative["attempt_states"]
    results = authoritative["results"]
    if (saved.get("stop_reason") is not None or any(state != "terminal" for state in states.values())
            or len(results) != len(items) or any(result.get("status") != "valid" for result in results)):
        raise ValueError("cannot resume: round is not complete and clean")
    launches = _contained(root / "launches", root, "launches directory", must_exist=True)
    item_by_id = {item["case_id"]: item for item in items}
    for result in results:
        item = item_by_id[result["case_id"]]
        if (result.get("outcome") not in {"success", "policy_failure"}
                or result.get("config_path") != item["config_path"]
                or result.get("output_path") != item["output_path"]):
            raise ValueError("cannot resume: result does not match the immutable case contract")
        output = _contained(Path(item["output_path"]), root, "output_dir", must_exist=True)
        evidence = result.get("evidence_paths")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("cannot resume: valid result lacks case-specific evidence")
        for evidence_path in evidence:
            checked = _contained(Path(evidence_path), output, "evidence path", must_exist=True)
            if not checked.is_file() or checked.stat().st_size <= 0:
                raise ValueError("cannot resume: evidence is not a non-empty regular file")
        pid = result.get("evaluator_pid")
        container = result.get("expected_container")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 or container != f"vla-eval-{pid}":
            raise ValueError("cannot resume: launch identity is not exact")
        try:
            sidecar = json.loads((launches / f"{result['case_id']}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("cannot resume: launch identity sidecar is malformed") from error
        if sidecar != {"schema_version": 1, "case_id": result["case_id"],
                       "evaluator_pid": pid, "expected_container": container}:
            raise ValueError("cannot resume: launch identity sidecar disagrees with result")
    return RoundSummary(tuple(_round_result(item["case_id"], ledger.attempts[item["case_id"]]["result"])
                              for item in items), True, saved.get("stop_reason"), digest)


def _record(request: RoundRequest, status: str, outcome: str | None, evidence: tuple[str, ...], identity: dict[str, Any], error: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {"case_id": request.case_id, "status": status, "outcome": outcome,
                              "evidence_paths": list(evidence), "config_path": str(request.config_path),
                              "output_path": str(request.output_dir)}
    result.update({key: value for key, value in identity.items() if key != "uncertain"})
    if error:
        result["infrastructure_error" if status in {"uncertain", "infrastructure_error"} else "invalid_evidence"] = error
    return result


def _round_result(case_id: str, record: dict[str, Any]) -> RoundResult:
    return RoundResult(case_id, record["status"], record.get("outcome"), tuple(record.get("evidence_paths", ())))


def _contained(path: Path, root: Path, label: str, *, must_exist: bool) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=must_exist)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError(f"{label} must be contained under the round root") from error
    return resolved


def _config_output_path(config: Path, root: Path) -> Path:
    """Read only the immutable output binding needed by this adapter."""
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError("config_path cannot be read") from error
    values = [line.split(":", 1)[1].strip() for line in lines
              if line.strip().startswith("output_dir:")]
    if len(values) != 1 or not values[0]:
        raise ValueError("config must contain exactly one output_dir")
    value = values[0]
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = value.strip("'\"")
    if not isinstance(parsed, str) or not parsed:
        raise ValueError("config output_dir must be a path string")
    return _contained(Path(parsed), root, "config output_dir", must_exist=False)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_hash(items: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(items, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding="utf-8")
    temporary.replace(path)
