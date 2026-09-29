"""Shared fail-closed attempt scheduler for fixed M3 and adaptive rounds.

The caller owns scenario-specific config generation and evidence parsing. This
module owns durable submit/result transitions, bounded concurrency, and
interruption cleanup; neither workload should implement those independently.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import threading
import time
from typing import Any, Callable

from robot_debug.attempt_ledger import AttemptLedger


def run_schedule(
    *, items: list[dict[str, Any]], workers: int, ledger: AttemptLedger,
    summary: dict[str, Any], elapsed: Callable[[], float], launch_cutoff_seconds: float,
    stop_requested: threading.Event, interrupt_event: threading.Event,
    launch_lock: threading.Lock, request_stop: Callable[[], None],
    save: Callable[[], None],
    item_paths: Callable[[dict[str, Any]], tuple[Any, Any]],
    validate_prepared_artifacts: Callable[[dict[str, Any], Any, Any], bool],
    prepare_config: Callable[[dict[str, Any], Any, Any], None],
    execute: Callable[[dict[str, Any], Any, Any, float], dict[str, Any] | None],
    wait_for_futures: Callable[..., Any] = wait,
) -> dict[str, Any]:
    """Execute one immutable manifest while preserving attempt ownership.

    Callers must validate the manifest, paths, and config/evidence callbacks
    before entry. ``execute`` must use contained evaluator lifecycle handling
    for live runs. An uncertain attempt is never silently retried here.
    """
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
                if not validate_prepared_artifacts(item, config, output):
                    prepare_config(item, config, output)
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
                        # Persist intent before submit. If submit becomes
                        # uncertain, the ledger prevents an automatic retry.
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
                            # Future registration itself can be interrupted.
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
            done, _ = wait_for_futures(active, timeout=0.2, return_when=FIRST_COMPLETED)
            for future in done:
                case_id = active[future]
                try:
                    record = future.result()
                except KeyboardInterrupt:
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
                # Result durability precedes releasing Future ownership.
                ledger.capture_result(case_id, record, interrupted=interrupt_event.is_set())
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
            if submission_call_case_id is None:
                for case_id, state in ledger.snapshot()["attempt_states"].items():
                    if state == "submitting_unknown":
                        ledger.cancel_unstarted(case_id)
            for future, case_id in list(active.items()):
                if future.cancel():
                    active.pop(future)
                    ledger.cancel_unstarted(case_id)
            save()
            deadline = time.monotonic() + 90
            while active and time.monotonic() < deadline:
                done, _ = wait_for_futures(active, timeout=min(0.2, max(0, deadline - time.monotonic())),
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
            executor.shutdown(wait=not cleanup_incomplete, cancel_futures=True)
        else:
            executor.shutdown(wait=True)
        if summary["stop_reason"] is None and len(summary["results"]) != len(items):
            summary["stop_reason"] = "partial"
        save()
    return summary
