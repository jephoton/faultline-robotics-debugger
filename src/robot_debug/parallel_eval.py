"""Pure helpers for M3's fixed replay workload and comparable mode reports.

``summarize_modes`` accepts exactly three mode records, one for each worker
count (1, 2, and 4).  A record has ``workers``, ``manifest_hash``, ``case_ids``,
``elapsed_seconds``, ``cost_usd`` (or ``None``), ``valid_count``, and
``results``.  Each result has ``case_id``, ``kind``, ``status: 'valid'``, and
an ``outcome`` of ``success`` or ``policy_failure``.  The results must contain exactly one valid terminal
result for every ID in ``case_ids``.  The returned report is ordered by worker
count and contains the input timing/count fields plus throughput, speedup,
efficiency, cost per valid result, per-kind outcome counts, and drift IDs.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from typing import Any


_WORKER_COUNTS = (1, 2, 4)
_VALID_OUTCOMES = {"success", "policy_failure"}
_MASK_RECTANGLE = {"x": 0.625, "y": 0.0, "width": 0.375, "height": 0.375}


def build_manifest(repeats_per_case: int = 8) -> list[dict[str, Any]]:
    """Build the M3 workload in its frozen nominal-then-mask ordering."""
    if isinstance(repeats_per_case, bool) or not isinstance(repeats_per_case, int) or repeats_per_case <= 0:
        raise ValueError("repeats_per_case must be a positive integer")

    manifest: list[dict[str, Any]] = []
    for kind in ("nominal", "mask"):
        for repeat in range(1, repeats_per_case + 1):
            manifest.append(
                {
                    "case_id": f"{kind}-{repeat:02d}",
                    "kind": kind,
                    "repeat": repeat,
                    "task_id": 0,
                    "episode_index": 0,
                    "seed": 7,
                    "env_seed": 7,
                    "rectangle": None if kind == "nominal" else dict(_MASK_RECTANGLE),
                }
            )
    return manifest


def manifest_hash(items: list[dict[str, Any]]) -> str:
    """Return the SHA-256 digest of the prescribed canonical manifest bytes."""
    encoded = json.dumps(
        items, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assign_items(items: list[dict[str, Any]], workers: int) -> list[list[dict[str, Any]]]:
    """Round-robin unique case IDs among the supported M3 worker counts."""
    if isinstance(workers, bool) or not isinstance(workers, int) or workers not in _WORKER_COUNTS:
        raise ValueError("workers must be one of 1, 2, or 4")
    case_ids = [_case_id(item) for item in items]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("items must have unique case_id values")
    assignments: list[list[dict[str, Any]]] = [[] for _ in range(workers)]
    for index, item in enumerate(items):
        assignments[index % workers].append(item)
    return assignments


def summarize_modes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and compare complete 1-, 2-, and 4-worker M3 mode records.

    The validated record and report schemas are described in this module's
    docstring for the Task 3 scheduler/report integration.
    """
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    by_workers: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("each mode record must be a dictionary")
        workers = record.get("workers")
        if (
            isinstance(workers, bool)
            or not isinstance(workers, int)
            or workers not in _WORKER_COUNTS
            or workers in by_workers
        ):
            raise ValueError("records must contain one each of workers 1, 2, and 4")
        by_workers[workers] = record
    if set(by_workers) != set(_WORKER_COUNTS):
        raise ValueError("records must contain one each of workers 1, 2, and 4")

    validated = {workers: _validate_record(record) for workers, record in by_workers.items()}
    baseline = validated[1]
    for workers in (2, 4):
        current = validated[workers]
        if current["manifest_hash"] != baseline["manifest_hash"]:
            raise ValueError("mode records have different manifest hashes")
        if Counter(current["case_ids"]) != Counter(baseline["case_ids"]):
            raise ValueError("mode records have different case ID multisets")
        if current["kinds"] != baseline["kinds"]:
            raise ValueError("mode records have different case kinds")

    baseline_elapsed = baseline["elapsed_seconds"]
    baseline_outcomes = baseline["outcomes"]
    report: list[dict[str, Any]] = []
    for workers in _WORKER_COUNTS:
        current = validated[workers]
        valid_count = current["valid_count"]
        elapsed = current["elapsed_seconds"]
        throughput_per_hour = valid_count * 3600 / elapsed
        speedup = baseline_elapsed / elapsed
        efficiency = speedup / workers
        if not all(math.isfinite(metric) for metric in (throughput_per_hour, speedup, efficiency)):
            raise ValueError("derived comparison metrics must be finite")
        report.append(
            {
                "workers": workers,
                "elapsed_seconds": elapsed,
                "valid_count": valid_count,
                "throughput_per_hour": throughput_per_hour,
                "speedup": speedup,
                "efficiency": efficiency,
                "cost_per_valid": (
                    None if current["cost_usd"] is None else current["cost_usd"] / valid_count
                ),
                "outcome_counts": _outcome_counts(current["kinds"], current["outcomes"]),
                "drift_case_ids": [
                    case_id
                    for case_id in current["case_ids"]
                    if current["outcomes"][case_id] != baseline_outcomes[case_id]
                ],
            }
        )
    return report


def _validate_record(record: dict[str, Any]) -> dict[str, Any]:
    digest = record.get("manifest_hash")
    if not isinstance(digest, str) or not digest:
        raise ValueError("manifest_hash must be a non-empty string")
    case_ids = record.get("case_ids")
    if (
        not isinstance(case_ids, list)
        or not case_ids
        or any(not isinstance(case_id, str) or not case_id for case_id in case_ids)
    ):
        raise ValueError("case_ids must be non-empty strings")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case_ids must not contain duplicates")
    elapsed = record.get("elapsed_seconds")
    if not _finite_number(elapsed) or elapsed <= 0:
        raise ValueError("elapsed_seconds must be finite and positive")
    cost = record.get("cost_usd")
    if cost is not None and (not _finite_number(cost) or cost < 0):
        raise ValueError("cost_usd must be None or a finite non-negative number")
    results = record.get("results")
    if not isinstance(results, list):
        raise ValueError("results must be a list")
    result_ids = [_case_id(result) for result in results]
    if Counter(result_ids) != Counter(case_ids):
        raise ValueError("results must contain exactly one result per case ID")

    outcomes: dict[str, str] = {}
    kinds: dict[str, str] = {}
    for result in results:
        if result.get("status") != "valid":
            raise ValueError("every result must be terminal and valid")
        kind = result.get("kind")
        outcome = result.get("outcome")
        if (
            not isinstance(kind, str)
            or not kind
            or not isinstance(outcome, str)
            or outcome not in _VALID_OUTCOMES
        ):
            raise ValueError("valid results require a kind and completed policy outcome")
        case_id = result["case_id"]
        kinds[case_id] = kind
        outcomes[case_id] = outcome
    valid_count = record.get("valid_count")
    if isinstance(valid_count, bool) or not isinstance(valid_count, int) or valid_count != len(results):
        raise ValueError("valid_count must equal the number of valid results")
    return {
        "manifest_hash": digest,
        "case_ids": case_ids,
        "elapsed_seconds": elapsed,
        "cost_usd": cost,
        "valid_count": valid_count,
        "kinds": kinds,
        "outcomes": outcomes,
    }


def _case_id(item: object) -> str:
    if not isinstance(item, dict) or not isinstance(item.get("case_id"), str) or not item["case_id"]:
        raise ValueError("each item must have a non-empty string case_id")
    return item["case_id"]


def _finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _outcome_counts(kinds: dict[str, str], outcomes: dict[str, str]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for case_id, kind in kinds.items():
        counts.setdefault(kind, {})[outcomes[case_id]] = counts.setdefault(kind, {}).get(outcomes[case_id], 0) + 1
    return counts
