"""Fail closed on unsafe M3 guest evidence, including a valid partial exit 1."""

import json
import hashlib
import math
from pathlib import Path
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def contained(path, root, *, file=True):
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(root.resolve(strict=True)), f"path escapes root: {path}")
    if file:
        require(resolved.is_file() and resolved.stat().st_size > 0, f"empty or missing file: {path}")
    return resolved


def validate(session, mode):
    require(mode in {"sequential-jobs", "adaptive-portfolio"}, "unsupported mode")
    session = Path(session).resolve(strict=True)
    require(session.is_dir(), "missing session")
    rate = float(contained(session / "hourly-rate.txt", session).read_text().strip())
    require(math.isfinite(rate) and rate > 0, "invalid hourly rate")
    root = session / ("sequential" if mode == "sequential-jobs" else "adaptive")
    require(root.is_dir() and root.resolve() == root, "invalid mode root")
    paths = list(root.glob("portfolio-*/portfolio_summary.json"))
    require(len(paths) == 1, "expected exactly one portfolio summary")
    summary_path = contained(paths[0], root)
    portfolio = summary_path.parent
    summary = json.loads(summary_path.read_text())
    manifest = json.loads(contained(session / "manifest.json", session).read_text())
    require(manifest == {"suite": "libero_object", "task_ids": [0, 1, 2], "seed": 7,
                         "family": "agentview_rect_occlusion",
                         "checkpoint_id": "nvidia/gr00t17-lerobot-libero_object-640",
                         "checkpoint_revision": "1499db357f6ca3762b56c2e8c00b530eb9a09444"},
            "manifest identity mismatch")
    manifest_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    require(summary.get("manifest") == manifest and summary.get("manifest_hash") == manifest_hash,
            "summary manifest mismatch")
    require(summary.get("mode") == mode, "mode mismatch")
    require(summary.get("execution_kind") == "live" and summary.get("synthetic") is False
            and summary.get("dry_run") is False, "not live evidence")
    require(summary.get("accounting_incomplete") is False, "accounting incomplete")
    require(summary.get("invalid_attempts") == 0 and summary.get("uncertain_attempts") == 0,
            "invalid or uncertain attempts")
    physical = summary.get("physical_attempts")
    require(type(physical) is int and physical == summary.get("valid_episodes") and physical > 0,
            "physical/valid mismatch")
    cap = 1 if mode == "sequential-jobs" else 2
    observed = summary.get("max_observed_evaluator_calls")
    require(type(observed) is int and 1 <= observed <= cap, "concurrency mismatch")
    require(summary.get("max_workers") == cap, "worker cap mismatch")
    expected_limits = {"episodes": 111, "seconds": 1800.0,
                       "estimated_usd": rate * 1800 / 3600, "hourly_rate": rate}
    require(summary.get("limits") == expected_limits, "immutable limits mismatch")
    waves = summary.get("waves")
    require(isinstance(waves, list) and waves, "missing waves")
    expected_tasks = {"task-00": 0, "task-01": 1, "task-02": 2}
    seen_evidence = set()
    valid_count = 0
    for wave in waves:
        ledger_path = wave.get("ledger_path")
        require(isinstance(ledger_path, str) and ledger_path and not Path(ledger_path).is_absolute(),
                "invalid ledger path")
        ledger = json.loads(contained(portfolio / ledger_path, portfolio).read_text())
        records = ledger.get("attempt_records")
        require(isinstance(records, dict) and all(isinstance(record, dict) and
                record.get("state") in {"prepared", "terminal"} for record in records.values()),
                "nonterminal attempt")
        require(ledger.get("in_flight_ids") == [], "inflight attempt")
        results = wave.get("results")
        require(isinstance(results, list), "invalid wave results")
        for result in results:
            require(result.get("status") == "valid", "invalid wave result")
            case_id = result.get("case_id")
            job = case_id.split("--", 1)[0] if isinstance(case_id, str) else None
            require(job in expected_tasks and case_id in records and records[case_id]["state"] == "terminal",
                    "case identity/ledger mismatch")
            evidence = result.get("evidence_paths")
            require(isinstance(evidence, list) and evidence, "missing evidence")
            output = result.get("output_path")
            require(isinstance(output, str) and Path(output).is_absolute(), "invalid output path")
            output_root = contained(Path(output), portfolio, file=False)
            require(output_root.is_dir(), "invalid output directory")
            files = []
            for raw in evidence:
                require(isinstance(raw, str) and Path(raw).is_absolute(), "evidence must be absolute")
                path = contained(Path(raw), portfolio)
                require(path.is_relative_to(output_root), "evidence escapes case output")
                require(path not in seen_evidence, "evidence reused across cases")
                seen_evidence.add(path)
                files.append(path)
            aggregates = [path for path in files if path.name.endswith("_aggregate.json")]
            require(len(aggregates) == 1 and any(path.suffix == ".jsonl" for path in files)
                    and any(path.suffix == ".mp4" for path in files), "missing aggregate/trace/video")
            episode = json.loads(aggregates[0].read_text())["tasks"][0]["episodes"][0]
            require(type(episode.get("task_id")) is int and episode["task_id"] == expected_tasks[job]
                    and type(episode.get("episode_idx")) is int and episode["episode_idx"] == 0,
                    "task/episode mismatch")
            valid_count += 1
    require(valid_count == physical, "result count mismatch")
    print(mode, summary.get("stop_reason"), physical, "valid attempts", valid_count, "media sets", flush=True)


if __name__ == "__main__":
    try:
        require(len(sys.argv) == 3, "usage: validate-mode.py SESSION MODE")
        validate(sys.argv[1], sys.argv[2])
    except (OSError, ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError) as error:
        print(f"unsafe mode evidence: {error}", file=sys.stderr)
        raise SystemExit(2)
