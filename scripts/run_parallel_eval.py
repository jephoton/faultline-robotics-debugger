"""Run one bounded M3 replay mode locally or against an already-running evaluator."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import nullcontext
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from robot_debug.attempt_ledger import AttemptLedger
from robot_debug.parallel_eval import build_manifest, manifest_hash, summarize_modes


_FROZEN_M3_MANIFEST_HASH = manifest_hash(build_manifest(8))
_SIGKILL = getattr(signal, "SIGKILL", 9)


_BASE_PATH = Path(__file__).with_name("run_failure_search.py")
_BASE_SPEC = importlib.util.spec_from_file_location("run_failure_search_base", _BASE_PATH)
base = importlib.util.module_from_spec(_BASE_SPEC)
sys.modules[_BASE_SPEC.name] = base
_BASE_SPEC.loader.exec_module(base)


class _LaunchCancelled(Exception):
    """A submitted item never started because another worker requested a stop."""


class _EvaluatorInterrupted(Exception):
    """An active evaluator was cancelled by the session owner."""


def _owned_group_present(group_id: int, problems: list[str]) -> bool | None:
    """Return whether this evaluator's exact process group still exists.

    The group identifier is the evaluator PID because the launcher creates a
    new session.  This deliberately probes one group only; it never searches
    the host process table.
    """
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    except Exception as error:
        problems.append(
            f"process-group observation failed: {type(error).__name__}: {error}"
        )
        return None
    return True


def _wait_for_group_absence(group_id: int, *, deadline: float, problems: list[str]) -> bool | None:
    """Observe one owned group until absent, without sending another signal."""
    while True:
        present = _owned_group_present(group_id, problems)
        if present is not True:
            return present
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(0.2, remaining))


def _run_evaluator_safely(
    argv: list[str], *, cwd: Path, check: bool, timeout: float,
    process_factory: Callable[..., Any] = subprocess.Popen,
    docker_runner: Callable[..., Any] = subprocess.run,
    stop_event: threading.Event | None = None,
    interrupt_event: threading.Event | None = None,
    launch_lock: threading.Lock | None = None,
    launch_observer: Callable[[int, str], None] | None = None,
    graceful_group_wait_seconds: float = 20,
    forced_cleanup_wait_seconds: float = 5,
) -> Any:
    """Own an evaluator process group and its exact PID-named container.

    The pinned Docker CLI names its `--rm` container ``vla-eval-{os.getpid()}``.
    It handles SIGTERM by stopping that container with a ten-second grace period.
    An uncertain process-group or Docker query must never count as cleanup
    confirmation.  Docker observations do not prove the daemon has no pending
    request.
    """
    if process_factory is subprocess.Popen and os.name != "posix":
        raise RuntimeError("the production evaluator launcher requires a POSIX host")
    with launch_lock if launch_lock is not None else nullcontext():
        if ((stop_event is not None and stop_event.is_set())
                or (interrupt_event is not None and interrupt_event.is_set())):
            raise _LaunchCancelled()
        process = process_factory(argv, cwd=cwd, start_new_session=True)
    evaluator_pid = process.pid
    container = f"vla-eval-{evaluator_pid}"
    try:
        process.evaluator_pid = evaluator_pid
        process.expected_container = container
    except Exception:
        # Production Popen instances accept these attributes.  Keep injected
        # fakes usable even when they intentionally expose a narrower API.
        pass
    try:
        if launch_observer is not None:
            launch_observer(evaluator_pid, container)
        if interrupt_event is None:
            process.wait(timeout=timeout)
        else:
            deadline = time.monotonic() + timeout
            while True:
                if interrupt_event.is_set():
                    raise _EvaluatorInterrupted("session interrupted")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                try:
                    process.wait(timeout=min(remaining, 0.2))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(argv, timeout) from None
        return process
    except BaseException as error:
        if stop_event is not None:
            with launch_lock if launch_lock is not None else nullcontext():
                stop_event.set()
        error.evaluator_pid = evaluator_pid
        error.expected_container = container
        problems: list[str] = []
        reaped = False
        supports_groups = os.name == "posix" or hasattr(os, "killpg")
        if supports_groups:
            group_present = _owned_group_present(evaluator_pid, problems)
            if group_present:
                try:
                    os.killpg(evaluator_pid, signal.SIGTERM)
                except ProcessLookupError:
                    group_present = False
                except Exception as cleanup_error:
                    problems.append(
                        f"process-group SIGTERM failed: {type(cleanup_error).__name__}: {cleanup_error}"
                    )
            if group_present is True:
                # Do not reap the leader yet: its unreaped PID prevents numeric
                # PGID reuse before the final possible group signal.
                group_present = _wait_for_group_absence(
                    evaluator_pid,
                    deadline=time.monotonic() + graceful_group_wait_seconds,
                    problems=problems,
                )
            if group_present is True:
                try:
                    os.killpg(evaluator_pid, _SIGKILL)
                except ProcessLookupError:
                    group_present = False
                except Exception as cleanup_error:
                    problems.append(
                        f"process-group SIGKILL failed: {type(cleanup_error).__name__}: {cleanup_error}"
                    )
                cleanup_deadline = time.monotonic() + forced_cleanup_wait_seconds
                try:
                    process.wait(timeout=max(0.001, cleanup_deadline - time.monotonic()))
                    reaped = True
                except subprocess.TimeoutExpired:
                    problems.append("evaluator parent did not exit after process-group SIGKILL")
                except Exception as cleanup_error:
                    problems.append(f"evaluator reap failed: {type(cleanup_error).__name__}: {cleanup_error}")
                if reaped:
                    # After reap, a numeric PGID might be reused.  Observe it
                    # only; a present/uncertain result must never receive a
                    # further signal.
                    group_present = _wait_for_group_absence(
                        evaluator_pid, deadline=cleanup_deadline, problems=problems
                    )
        else:
            # This branch is only for injected test runners on non-POSIX hosts.
            # The production launcher above has already refused such a host.
            group_present = False
            try:
                process.terminate()
                process.wait(timeout=20)
                reaped = True
            except subprocess.TimeoutExpired:
                problems.append("evaluator parent did not exit after SIGTERM")
            except Exception as cleanup_error:
                problems.append(f"SIGTERM/wait failed: {type(cleanup_error).__name__}: {cleanup_error}")

        if not reaped and group_present is not True:
            try:
                process.wait(timeout=5)
                reaped = True
            except Exception as cleanup_error:
                problems.append(f"evaluator reap failed: {type(cleanup_error).__name__}: {cleanup_error}")

        if group_present is True:
            problems.append("owned evaluator process group was still present after bounded cleanup")

        def container_present() -> bool | None:
            try:
                result = docker_runner(["docker", "ps", "-a", "--format", "{{.Names}}"],
                    capture_output=True, text=True, check=False, timeout=15)
            except Exception as cleanup_error:
                problems.append(f"Docker inspection failed: {type(cleanup_error).__name__}: {cleanup_error}")
                return None
            if result.returncode != 0:
                problems.append(f"Docker inspection failed: {result.stderr}")
                return None
            return container in result.stdout.splitlines()

        absent = False
        if group_present is False:
            present = container_present()
            if present is not False:
                try:
                    removed = docker_runner(["docker", "rm", "-f", container],
                        capture_output=True, text=True, check=False, timeout=20)
                    if removed.returncode != 0:
                        problems.append(f"Docker removal failed for {container}: {removed.stderr}")
                except Exception as cleanup_error:
                    problems.append(f"Docker removal failed for {container}: {type(cleanup_error).__name__}: {cleanup_error}")
            # This is an exact-name observation after the owned group is quiet,
            # not proof that the Docker daemon has no outstanding request.
            absent = container_present() is False
        else:
            problems.append("owned evaluator process group was not confirmed quiescent")

        error.cleanup_confirmed = reaped and group_present is False and absent and not problems
        error.cleanup_error = "; ".join(problems) if not error.cleanup_confirmed else None
        if not error.cleanup_confirmed and not error.cleanup_error:
            error.cleanup_error = f"cannot confirm {container} was removed"
        raise


def _positive_finite_seconds(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")


def run_mode(
    *,
    upstream_root: Path | str,
    project_root: Path | str,
    results_root: Path | str,
    workers: int,
    repeats_per_case: int = 8,
    launch_cutoff_seconds: float = 1560,
    item_timeout_seconds: float = 300,
    command_runner: Callable[..., Any] | None = None,
    monotonic_clock: Callable[[], float] = time.monotonic,
    interrupt_event: threading.Event | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Run a fixed manifest once, or resume only proven-safe prepared work."""
    if isinstance(workers, bool) or not isinstance(workers, int) or workers not in (1, 2, 4):
        raise ValueError("workers must be one of 1, 2, or 4")
    _positive_finite_seconds("launch_cutoff_seconds", launch_cutoff_seconds)
    _positive_finite_seconds("item_timeout_seconds", item_timeout_seconds)
    stop_requested = threading.Event()
    if interrupt_event is None:
        interrupt_event = threading.Event()
    launch_lock = threading.Lock()

    def request_stop() -> None:
        with launch_lock:
            stop_requested.set()

    production_command_runner = command_runner is None
    if production_command_runner:
        def command_runner(
            argv: list[str], *, cwd: Path, check: bool, timeout: float,
            launch_observer: Callable[[int, str], None],
        ) -> Any:
            return _run_evaluator_safely(argv, cwd=cwd, check=check, timeout=timeout,
                stop_event=stop_requested, interrupt_event=interrupt_event, launch_lock=launch_lock,
                launch_observer=launch_observer)
    upstream_root = Path(upstream_root).resolve()
    project_root = Path(project_root).resolve()
    started = monotonic_clock()
    items = build_manifest(repeats_per_case)
    case_ids = [item["case_id"] for item in items]
    expected_manifest_bytes = json.dumps(
        items, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    session = Path(results_root).resolve() / f"m3-workers-{workers}"
    summary: dict[str, Any] = {
        "workers": workers, "manifest_hash": manifest_hash(items), "manifest_path": "manifest.json",
        "case_ids": case_ids, "planned_ids": case_ids,
        "in_flight_ids": [], "results": [], "valid_count": 0, "cost_usd": None,
        "elapsed_seconds": 0.0, "stop_reason": None,
    }
    previous_elapsed = 0.0

    if not isinstance(resume, bool):
        raise ValueError("resume must be a boolean")
    if resume:
        if not session.is_dir():
            raise ValueError("cannot resume: no prior session exists")
        manifest_path = session / "manifest.json"
        summary_path = session / "session_summary.json"
        if not manifest_path.is_file() or not summary_path.is_file():
            raise ValueError("cannot resume: partial session is missing manifest or summary")
        try:
            manifest_bytes = manifest_path.read_bytes()
            prior_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("cannot resume: partial summary or manifest is malformed") from error
        if manifest_bytes != expected_manifest_bytes:
            raise ValueError("cannot resume: manifest bytes do not match the frozen workload")
        if not isinstance(prior_summary, dict):
            raise ValueError("cannot resume: partial summary is malformed")
        required_summary_fields = {
            "workers", "manifest_hash", "manifest_path", "case_ids", "planned_ids",
            "elapsed_seconds", "stop_reason", "attempt_states", "attempt_records",
            "results", "valid_count", "in_flight_ids",
        }
        if not required_summary_fields.issubset(prior_summary):
            raise ValueError("cannot resume: partial summary is malformed")
        if prior_summary.get("workers") != workers:
            raise ValueError("cannot resume: worker count does not match the partial session")
        if (prior_summary.get("manifest_hash") != manifest_hash(items)
                or prior_summary.get("manifest_path") != "manifest.json"):
            raise ValueError("cannot resume: manifest digest does not match the partial session")
        if prior_summary.get("case_ids") != case_ids or prior_summary.get("planned_ids") != case_ids:
            raise ValueError("cannot resume: case IDs do not match the frozen workload")
        if prior_summary.get("stop_reason") not in {"partial", "interrupted", "launch_cutoff_reached"}:
            raise ValueError("cannot resume: partial summary has an unsafe stop reason")
        try:
            ledger = AttemptLedger.from_snapshot(case_ids, prior_summary)
        except ValueError as error:
            raise ValueError("cannot resume: partial summary ledger is malformed") from error
        authoritative = ledger.snapshot()
        states = authoritative["attempt_states"]
        if any(state not in {"prepared", "terminal"} for state in states.values()):
            raise ValueError("cannot resume: partial session has in-flight or uncertain attempts")
        if any(result.get("status") != "valid" for result in authoritative["results"]):
            raise ValueError("cannot resume: partial session has nonvalid terminal evidence")
        if any(prior_summary.get(field) != value for field, value in authoritative.items()):
            raise ValueError("cannot resume: partial summary does not match its ledger")
        previous_elapsed = prior_summary.get("elapsed_seconds")
        if (isinstance(previous_elapsed, bool)
                or not isinstance(previous_elapsed, (int, float))
                or not math.isfinite(previous_elapsed) or previous_elapsed < 0):
            raise ValueError("cannot resume: partial summary elapsed time is malformed")
        for directory in (session / "configs", session / "runs", session / "launches"):
            if not directory.is_dir():
                raise ValueError("cannot resume: partial session layout is malformed")
        summary = prior_summary
        summary["resumed"] = True
        summary["stop_reason"] = None
    else:
        ledger = AttemptLedger(case_ids)

    def elapsed() -> float:
        return previous_elapsed + monotonic_clock() - started

    def save() -> None:
        summary.update(ledger.snapshot())
        summary["elapsed_seconds"] = elapsed()
        base._atomic_write_json(session / "session_summary.json", summary)

    try:
        if not resume:
            session = base._prepare_session_directory(
                Path(results_root).resolve(), session_directory_name=f"m3-workers-{workers}"
            )
        configs = session / "configs"
        runs = session / "runs"
        launches = session / "launches"
        if not resume:
            configs.mkdir()
            runs.mkdir()
            launches.mkdir()
        manifest_path = session / "manifest.json"
        if not resume:
            manifest_path.write_bytes(expected_manifest_bytes)
    except KeyboardInterrupt:
        # A directory can exist before session setup reaches its first normal
        # save.  Preserve an explicitly non-comparable durable record rather
        # than making this look like a session that never started.
        interrupt_event.set()
        request_stop()
        summary["stop_reason"] = "interrupted"
        if session.is_dir():
            save()
        return summary

    def item_paths(item: dict[str, Any]) -> tuple[Path, Path]:
        case_id = item["case_id"]
        config = configs / f"{case_id}.yaml"
        output = runs / case_id
        for path in (config, output):
            try:
                path.resolve().relative_to(session)
            except ValueError as error:
                raise ValueError("item path escapes session") from error
        return config, output

    def launch_identity_observer(case_id: str) -> Callable[[int, str], None]:
        sidecar = launches / f"{case_id}.json"
        try:
            sidecar.resolve().relative_to(session)
        except ValueError as error:
            raise ValueError("launch identity path escapes session") from error

        def observe(evaluator_pid: int, expected_container: str) -> None:
            base._atomic_write_json(sidecar, {
                "schema_version": 1,
                "case_id": case_id,
                "evaluator_pid": evaluator_pid,
                "expected_container": expected_container,
            })

        return observe

    def execute(item: dict[str, Any], config: Path, output: Path, attempt_started: float) -> dict[str, Any] | None:
        with launch_lock:
            if stop_requested.is_set():
                return None
        record = {"case_id": item["case_id"], "kind": item["kind"], "task_id": 0, "episode_index": 0,
                  "config_path": str(config.relative_to(session)), "output_path": str(output.relative_to(session)),
                  "started_seconds": attempt_started, "ended_seconds": None, "duration_seconds": None,
                  "status": None, "outcome": None, "replayable": False}

        def record_cleanup_identity(error: BaseException) -> None:
            evaluator_pid = getattr(error, "evaluator_pid", None)
            expected_container = getattr(error, "expected_container", None)
            if evaluator_pid is not None:
                record["evaluator_pid"] = evaluator_pid
            if expected_container is not None:
                record["expected_container"] = expected_container

        def record_process_identity(process: Any) -> None:
            evaluator_pid = getattr(process, "evaluator_pid", None)
            expected_container = getattr(process, "expected_container", None)
            if evaluator_pid is not None:
                record["evaluator_pid"] = evaluator_pid
            if expected_container is not None:
                record["expected_container"] = expected_container

        try:
            arguments = [base._resolve_evaluator_command(Path(sys.executable)), "run", "--config", str(config)]
            if production_command_runner:
                process = command_runner(arguments, cwd=upstream_root, check=False,
                    timeout=item_timeout_seconds,
                    launch_observer=launch_identity_observer(item["case_id"]))
            else:
                process = command_runner(arguments, cwd=upstream_root, check=False,
                    timeout=item_timeout_seconds)
        except _LaunchCancelled:
            return None
        except _EvaluatorInterrupted as error:
            request_stop()
            record_cleanup_identity(error)
            cleanup_confirmed = getattr(error, "cleanup_confirmed", False)
            cleanup_error = getattr(error, "cleanup_error", None)
            record.update(status="infrastructure_error", cleanup_confirmed=cleanup_confirmed,
                infrastructure_error="session interrupted"
                + (f"; cleanup risk: {cleanup_error}" if cleanup_error else ""))
        except subprocess.TimeoutExpired as error:
            request_stop()
            record_cleanup_identity(error)
            cleanup_confirmed = getattr(error, "cleanup_confirmed", False)
            cleanup_error = getattr(error, "cleanup_error", None)
            if not cleanup_confirmed and not cleanup_error:
                cleanup_error = "evaluator container cleanup was not confirmed"
            record.update(status="infrastructure_error", cleanup_confirmed=cleanup_confirmed,
                infrastructure_error=f"timeout: {error}" + (f"; cleanup risk: {cleanup_error}" if cleanup_error else ""))
        except Exception as error:
            request_stop()
            record_cleanup_identity(error)
            cleanup_confirmed = getattr(error, "cleanup_confirmed", None)
            cleanup_error = getattr(error, "cleanup_error", None)
            record.update(status="infrastructure_error", cleanup_confirmed=cleanup_confirmed,
                infrastructure_error=f"command_runner: {type(error).__name__}: {error}"
                + (f"; cleanup risk: {cleanup_error}" if cleanup_error else ""))
        else:
            record_process_identity(process)
            returncode = getattr(process, "returncode", 0)
            record["returncode"] = returncode
            if returncode not in (0, None):
                request_stop()
                record.update(status="infrastructure_error", infrastructure_error=f"evaluator returned nonzero status {returncode}")
            else:
                try:
                    result = base._load_stage_results(output, expected_count=1)[0]
                    raw = json.loads(next(output.rglob("*_aggregate.json")).read_text(encoding="utf-8"))
                    task = raw["tasks"][0]
                    # The pinned harness writes task_id on each episode; the real
                    # aggregate task wrapper may omit it. Validate both when present.
                    episode_task_id = task["episodes"][0].get("task_id")
                    top_task_id = task.get("task_id")
                    if (type(episode_task_id) is not int or episode_task_id != 0
                            or ("task_id" in task and (type(top_task_id) is not int or top_task_id != 0))
                            or result.episode_index != 0):
                        raise ValueError("aggregate task_id or episode_index does not match M3 item")
                    if result.outcome not in {"success", "policy_failure"}:
                        raise ValueError("aggregate did not contain a completed policy outcome")
                    record.update(status="valid", outcome=result.outcome,
                        replayable=any(path.is_file() for path in output.rglob("*.mp4")))
                except Exception as error:
                    request_stop()
                    record.update(status="invalid_evidence", invalid_evidence=f"aggregate evidence error: {type(error).__name__}: {error}")
        record["ended_seconds"] = elapsed()
        record["duration_seconds"] = record["ended_seconds"] - attempt_started
        return record

    pending = iter(item for item in items if ledger.attempts[item["case_id"]]["state"] == "prepared")
    active: dict[Any, str] = {}
    stopped = False
    executor = ThreadPoolExecutor(max_workers=workers)
    interrupted = False
    submission_call_case_id: str | None = None
    try:
        save()
        while True:
            while not stopped and not stop_requested.is_set() and not interrupt_event.is_set() and len(active) < workers:
                if elapsed() >= launch_cutoff_seconds:
                    stopped = True; summary["stop_reason"] = "launch_cutoff_reached"; save(); break
                try:
                    item = next(pending)
                except StopIteration:
                    break
                config, output = item_paths(item)
                base._write_config(config_path=config, output_dir=output, project_root=project_root,
                    stage_name=f"m3-{item['case_id']}", episode_indices=(0,), **({} if item["rectangle"] is None else item["rectangle"]))
                if elapsed() >= launch_cutoff_seconds or stop_requested.is_set() or interrupt_event.is_set():
                    if not stop_requested.is_set():
                        stopped = True
                        summary["stop_reason"] = "launch_cutoff_reached"
                    save()
                    break
                attempt_started = elapsed()
                with launch_lock:
                    if stop_requested.is_set() or interrupt_event.is_set():
                        cancelled = True
                    else:
                        # Persist intent before submit: a signal during submit
                        # leaves conservative, durable submission uncertainty.
                        ledger.begin_submit(item["case_id"])
                        save()
                        submission_call_case_id = item["case_id"]
                        future = executor.submit(execute, item, config, output, attempt_started)
                        try:
                            active[future] = item["case_id"]
                            ledger.register_active(item["case_id"])
                            save()
                            submission_call_case_id = None
                        except BaseException:
                            # A test or signal can interrupt dictionary hashing
                            # after Future return.  Retry the runtime index once
                            # so known work remains observable; otherwise the
                            # durable submitting_unknown record is conservative.
                            try:
                                active[future] = item["case_id"]
                                ledger.register_active(item["case_id"])
                                save()
                            except BaseException:
                                pass
                            raise
                        cancelled = False
                if cancelled:
                    save()
                    break
            if not active:
                break
            if interrupt_event.is_set():
                interrupted = True
                break
            done, _ = wait(active, timeout=0.2, return_when=FIRST_COMPLETED)
            for future in done:
                case_id = active[future]
                try:
                    record = future.result()
                except KeyboardInterrupt:
                    # Preserve the caller's interrupt semantics; finalization
                    # below will reconcile the still-owned Future.
                    raise
                except BaseException as error:
                    record = {
                        "case_id": case_id,
                        "status": "infrastructure_error",
                        "cleanup_confirmed": False,
                        "infrastructure_error": (
                            "worker ended with "
                            f"{type(error).__name__}: {error}"
                        ),
                    }
                if record is None:
                    ledger.cancel_unstarted(case_id)
                    active.pop(future)
                    save()
                    continue
                # Result durability precedes releasing the Future index.
                ledger.capture_result(
                    case_id, record, interrupted=interrupt_event.is_set()
                )
                save()
                ledger.finish(case_id)
                save()
                active.pop(future)
                if record["status"] != "valid":
                    stopped = True
                    summary["stop_reason"] = record["status"]
        if interrupt_event.is_set():
            interrupted = True
    except KeyboardInterrupt:
        interrupted = True
        interrupt_event.set()
    finally:
        if interrupted or interrupt_event.is_set():
            interrupt_event.set()
            request_stop()
            summary["stop_reason"] = "interrupted"
            # A failed intent save occurs before executor.submit is entered,
            # so this one case is proven unlaunched and may return prepared.
            # Once the submit call starts, the ledger deliberately remains
            # conservative even when Python never returns a Future.
            if submission_call_case_id is None:
                for case_id, state in ledger.snapshot()["attempt_states"].items():
                    if state == "submitting_unknown":
                        ledger.cancel_unstarted(case_id)
            for future, case_id in list(active.items()):
                if future.cancel():
                    active.pop(future)
                    ledger.cancel_unstarted(case_id)
            save()
            # This is a bounded cleanup observation window, not a bound on
            # interpreter lifetime: shutdown(wait=False) cannot force a worker
            # thread to exit. Keep every ambiguous worker in_flight.
            deadline = time.monotonic() + 90
            while active and time.monotonic() < deadline:
                done, _ = wait(active, timeout=min(0.2, max(0, deadline - time.monotonic())),
                    return_when=FIRST_COMPLETED)
                for future in done:
                    case_id = active[future]
                    try:
                        record = future.result()
                    except BaseException as error:
                        record = {"case_id": case_id, "status": "infrastructure_error",
                            "cleanup_confirmed": False,
                            "infrastructure_error": f"cleanup risk: worker ended with {type(error).__name__}: {error}"}
                    if record is not None:
                        # A save may have been interrupted after normal-path
                        # capture but before Future release.  That pending
                        # record is already the ledger's single result; do not
                        # recapture a downgraded copy and corrupt its identity.
                        # The mode-level interrupted stop reason still makes
                        # this summary non-comparable.
                        attempt_state = ledger.attempts[case_id]["state"]
                        if attempt_state == "active":
                            ledger.capture_result(case_id, record, interrupted=True)
                        elif attempt_state not in {"completing_pending", "terminal"}:
                            raise RuntimeError(
                                f"known Future {case_id} has unexpected ledger state {attempt_state}"
                            )
                        save()
                        if ledger.attempts[case_id]["state"] == "completing_pending":
                            ledger.finish(case_id)
                            save()
                        if (record["status"] == "infrastructure_error"
                                and record.get("cleanup_confirmed") is not True):
                            summary["stop_reason"] = "interrupted_cleanup_risk"
                    else:
                        ledger.cancel_unstarted(case_id)
                    active.pop(future)
                    save()
            cleanup_incomplete = bool(active or ledger.snapshot()["in_flight_ids"])
            if cleanup_incomplete:
                summary["stop_reason"] = "interrupted_cleanup_risk"
                save()
            # wait=False cannot bound interpreter lifetime.  Join only when
            # every owned worker reached a known terminal state; otherwise the
            # durable cleanup-risk summary is the explicit incomplete result.
            executor.shutdown(wait=not cleanup_incomplete, cancel_futures=True)
        else:
            executor.shutdown(wait=True)
    if summary["stop_reason"] is None and len(summary["results"]) != len(items):
        summary["stop_reason"] = "partial"
    save()
    return summary


def report_mode_summaries(
    mode_summary_paths: list[Path | str], *, hourly_rate_usd: float | None = None,
    billable_seconds: dict[int, float] | None = None, output_dir: Path | str | None = None,
) -> Path:
    """Validate three durable summaries and write a comparable M3 report.

    Source files are only read.  A manifest path must be a relative path below
    its summary directory, so a summary cannot make this command inspect an
    unrelated filesystem location.
    """
    if not isinstance(mode_summary_paths, list) or len(mode_summary_paths) != 3:
        raise ValueError("exactly three mode summary paths are required")
    sources = [Path(path).resolve() for path in mode_summary_paths]
    if len(set(sources)) != 3:
        raise ValueError("mode summary paths must be distinct")
    records = [_load_report_record(source) for source in sources]
    # Validate the full comparison before indexing a record by worker count for
    # cost attribution.  This keeps malformed worker values fail-closed.
    summarize_modes([{**record, "cost_usd": None} for record in records])
    _validate_cost_inputs(hourly_rate_usd, billable_seconds)
    if hourly_rate_usd is not None:
        assert billable_seconds is not None
        for record in records:
            workers = record["workers"]
            record["cost_usd"] = hourly_rate_usd * billable_seconds[workers] / 3600
    else:
        for record in records:
            record["cost_usd"] = None

    metrics = summarize_modes(records)
    by_workers = {record["workers"]: record for record in records}
    if output_dir is None:
        output_root = sources[0].parent.parent
    else:
        output_root = Path(output_dir).resolve()
    json_path = output_root / "m3_comparison.json"
    markdown_path = output_root / "m3_comparison.md"
    input_paths = set(sources) | {record["_manifest_path"] for record in records}
    if json_path in input_paths or markdown_path in input_paths:
        raise ValueError("report output would collide with an input summary or manifest")
    if json_path.exists() or markdown_path.exists():
        raise ValueError("report output already exists; choose a new output directory")
    output_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "manifest_hash": records[0]["manifest_hash"],
        "work_count": len(records[0]["case_ids"]),
        "cost_rate_basis": "unavailable" if hourly_rate_usd is None else "hourly_rate_usd * billable_seconds / 3600",
        "modes": [
            {
                **metric,
                "invalid_count": len(by_workers[metric["workers"]]["results"]) - metric["valid_count"],
                "billable_seconds": None if billable_seconds is None else billable_seconds[metric["workers"]],
                "cost_usd": by_workers[metric["workers"]]["cost_usd"],
                "hourly_rate_usd": hourly_rate_usd,
                "source_summary_path": str(by_workers[metric["workers"]]["_source_path"]),
            }
            for metric in metrics
        ],
    }
    base._atomic_write_json(json_path, payload)
    markdown_path.write_text(_markdown_comparison(payload), encoding="utf-8")
    return json_path


def _load_report_record(source: Path) -> dict[str, Any]:
    if not source.is_file():
        raise ValueError(f"mode summary is not a file: {source}")
    try:
        record = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read mode summary: {source}") from error
    if (
        not isinstance(record, dict)
        or record.get("stop_reason") is not None
        or record.get("in_flight_ids", [])
    ):
        raise ValueError("mode summary is partial or invalid")
    if record.get("resumed") is True:
        raise ValueError("resumed mode summaries cannot be used for throughput comparison")
    manifest_name = record.get("manifest_path")
    if not isinstance(manifest_name, str) or not manifest_name or Path(manifest_name).is_absolute():
        raise ValueError("mode summary must name a relative manifest path")
    manifest_path = (source.parent / manifest_name).resolve()
    try:
        manifest_path.relative_to(source.parent)
    except ValueError as error:
        raise ValueError("manifest path escapes the mode summary directory") from error
    if not manifest_path.is_file():
        raise ValueError("mode manifest is not a file")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual_hash = manifest_hash(manifest)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError("mode manifest is invalid") from error
    if actual_hash != record.get("manifest_hash"):
        raise ValueError("mode manifest digest does not match its summary")
    if actual_hash != _FROZEN_M3_MANIFEST_HASH or manifest != build_manifest(8):
        raise ValueError("mode manifest is not the frozen M3 workload")
    manifest_ids = [item.get("case_id") if isinstance(item, dict) else None for item in manifest]
    if record.get("case_ids") != manifest_ids or record.get("planned_ids") != manifest_ids:
        raise ValueError("mode summary items do not match its manifest")
    manifest_kinds = {item["case_id"]: item["kind"] for item in manifest}
    results = record.get("results")
    if not isinstance(results, list) or any(
        not isinstance(result, dict) or result.get("kind") != manifest_kinds.get(result.get("case_id"))
        for result in results
    ):
        raise ValueError("mode result kinds do not match the frozen manifest")
    record["_source_path"] = source
    record["_manifest_path"] = manifest_path
    return record


def _validate_cost_inputs(hourly_rate_usd: float | None, billable_seconds: dict[int, float] | None) -> None:
    if (hourly_rate_usd is None) != (billable_seconds is None):
        raise ValueError("hourly rate and all billable seconds must be supplied together")
    if hourly_rate_usd is None:
        return
    if isinstance(hourly_rate_usd, bool) or not isinstance(hourly_rate_usd, (int, float)) or not math.isfinite(hourly_rate_usd) or hourly_rate_usd < 0:
        raise ValueError("hourly_rate_usd must be a finite non-negative number")
    if set(billable_seconds or {}) != {1, 2, 4}:
        raise ValueError("billable_seconds must contain workers 1, 2, and 4")
    for workers, seconds in billable_seconds.items():
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError(f"billable seconds for {workers} must be finite and positive")


def _markdown_comparison(payload: dict[str, Any]) -> str:
    lines = [
        "# M3 fixed replay comparison",
        "",
        f"Manifest: `{payload['manifest_hash']}`; work items: {payload['work_count']}; cost basis: {payload['cost_rate_basis']}.",
        "",
        "| Workers | Valid | Invalid | Elapsed (s) | Throughput/hour | Speedup | Efficiency | Billable (s) | Cost (USD) | Cost/valid | Nominal outcomes | Mask outcomes | Drift |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for mode in payload["modes"]:
        cost = "unavailable" if mode["cost_usd"] is None else f"{mode['cost_usd']:.6f}"
        cost_per_valid = "unavailable" if mode["cost_per_valid"] is None else f"{mode['cost_per_valid']:.6f}"
        billable = "unavailable" if mode["billable_seconds"] is None else f"{mode['billable_seconds']:.3f}"
        drift = ", ".join(mode["drift_case_ids"]) or "none"
        nominal = _format_outcomes(mode["outcome_counts"].get("nominal", {}))
        mask = _format_outcomes(mode["outcome_counts"].get("mask", {}))
        lines.append(
            f"| {mode['workers']} | {mode['valid_count']} | {mode['invalid_count']} | {mode['elapsed_seconds']:.3f} | "
            f"{mode['throughput_per_hour']:.3f} | {mode['speedup']:.3f} | {mode['efficiency']:.3f} | {billable} | {cost} | {cost_per_valid} | {nominal} | {mask} | {drift} |"
        )
    return "\n".join(lines) + "\n"


def _format_outcomes(counts: dict[str, int]) -> str:
    return f"success={counts.get('success', 0)}, policy_failure={counts.get('policy_failure', 0)}"


def _parse_billable_seconds(value: str) -> tuple[int, float]:
    try:
        workers_text, seconds_text = value.split("=", 1)
        workers = int(workers_text)
        seconds = float(seconds_text)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("billable seconds must be WORKERS=SECONDS") from error
    return workers, seconds


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        report_parser = argparse.ArgumentParser(description="Validate and compare three complete M3 replay modes.")
        report_parser.add_argument("--mode-summary", required=True, action="append", type=Path)
        report_parser.add_argument("--output-dir", type=Path)
        report_parser.add_argument("--hourly-rate-usd", type=float)
        report_parser.add_argument("--billable-seconds", action="append", type=_parse_billable_seconds)
        report_args = report_parser.parse_args(sys.argv[2:])
        billable = None
        if report_args.billable_seconds is not None:
            billable = {}
            for workers, seconds in report_args.billable_seconds:
                if workers in billable:
                    report_parser.error("billable seconds may name each worker count only once")
                billable[workers] = seconds
        try:
            report_path = report_mode_summaries(
                report_args.mode_summary, hourly_rate_usd=report_args.hourly_rate_usd,
                billable_seconds=billable, output_dir=report_args.output_dir,
            )
        except ValueError as error:
            report_parser.error(str(error))
        print(f"comparison: {report_path}")
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--workers", required=True, type=int, choices=(1, 2, 4))
    parser.add_argument("--launch-cutoff-seconds", required=True, type=float)
    parser.add_argument("--item-timeout-seconds", required=True, type=float)
    parser.add_argument("--resume", action="store_true",
        help="resume only a validated partial session with prepared work")
    args = parser.parse_args()
    interrupt_event = threading.Event()
    previous_handlers = {}
    if os.name == "posix" and threading.current_thread() is threading.main_thread():
        def request_interrupt(signum: int, frame: Any) -> None:
            interrupt_event.set()
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, request_interrupt)
    try:
        summary = run_mode(**vars(args), interrupt_event=interrupt_event)
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)
    path = args.results_root.resolve() / f"m3-workers-{args.workers}" / "session_summary.json"
    print(f"summary: {path} | stop: {summary['stop_reason'] or 'complete'} | valid: {summary['valid_count']}/{len(summary['planned_ids'])} | attempts: {len(summary['results'])}")
    if summary["stop_reason"] is not None or summary["valid_count"] != len(summary["planned_ids"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
