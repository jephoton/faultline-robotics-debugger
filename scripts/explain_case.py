"""Prepare or request an evidence-bound explanation for a registered case."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sys
from typing import Callable, NamedTuple


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY_ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from robot_debug.case_store import inspect_case
from robot_debug.evidence_packet import make_evidence_packet, packet_identity
from robot_debug.explanation import build_offline_report
from robot_debug.explanation_store import make_stored_report, store_report
from robot_debug.token_factory import (
    TokenFactoryError,
    load_api_key,
    preflight,
    request_interpretation,
    reserve_pilot,
)


PILOT_ROOT = (
    REPOSITORY_ROOT / "artifacts" / "m5-nemotron-pilot-repair-20261006")


class ExplainCaseError(ValueError):
    """A fixed, non-private CLI orchestration error."""


class Dependencies(NamedTuple):
    """Private orchestration seams used by offline unit tests."""

    inspect_case: Callable
    load_api_key: Callable
    preflight: Callable
    reserve_pilot: Callable
    request_interpretation: Callable
    store_report: Callable


DEFAULT_DEPENDENCIES = Dependencies(
    inspect_case=inspect_case,
    load_api_key=load_api_key,
    preflight=preflight,
    reserve_pilot=reserve_pilot,
    request_interpretation=request_interpretation,
    store_report=store_report,
)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ExplainCaseError("invalid arguments")


def _parser() -> argparse.ArgumentParser:
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--workspace", type=Path, required=True)
    prepare.add_argument("--case-id", required=True)

    preflight_command = commands.add_parser("preflight")
    preflight_command.add_argument("--env-file", type=Path)

    live = commands.add_parser("live")
    live.add_argument("--workspace", type=Path, required=True)
    live.add_argument("--case-id", required=True)
    live.add_argument("--env-file", type=Path)
    return parser


def _fresh_packet(workspace: Path, case_id: str, inspect: Callable) -> dict:
    case = inspect(workspace, case_id)
    try:
        available = case["capabilities"]["inspection"]["status"] == "available"
    except (KeyError, TypeError):
        available = False
    if not available:
        raise ExplainCaseError("case evidence is unavailable or changed")
    return make_evidence_packet(case)


def _offline_provenance() -> dict:
    return {
        "source": "offline", "provider": None, "model": None, "endpoint": None,
        "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "request_status": "offline", "error_code": None, "latency_seconds": None,
        "prompt_tokens": None, "completion_tokens": None,
        "estimated_cost_usd": None, "billed_cost_usd": None,
        "reservation_usd": 0,
    }


def _summary(record: dict) -> dict:
    return {
        "case_id": record["case_id"],
        "report_id": record["report_id"],
        "interpretation_status": record["report"]["interpretation_status"],
        "request_status": record["provenance"]["request_status"],
        "estimated_cost_usd": record["provenance"]["estimated_cost_usd"],
    }


def run_prepare(workspace: Path, case_id: str,
                *, deps: Dependencies = DEFAULT_DEPENDENCIES) -> dict:
    """Store a deterministic offline report without loading credentials."""
    packet = _fresh_packet(workspace, case_id, deps.inspect_case)
    report = build_offline_report(packet)
    record = make_stored_report(case_id, packet, report, _offline_provenance())
    deps.store_report(workspace, record)
    return _summary(record)


def run_preflight(env_file: Path | None,
                  *, deps: Dependencies = DEFAULT_DEPENDENCIES) -> dict:
    """Authenticate and check only the fixed model catalog."""
    api_key = deps.load_api_key(env_file)
    deps.preflight(api_key)
    return {"request_status": "ready"}


def run_live(workspace: Path, case_id: str, env_file: Path | None,
             *, deps: Dependencies = DEFAULT_DEPENDENCIES) -> dict:
    """Reserve and make the single approved paid attempt, then store safely."""
    initial_packet = _fresh_packet(workspace, case_id, deps.inspect_case)
    initial_id = packet_identity(initial_packet)

    api_key = deps.load_api_key(env_file)
    deps.preflight(api_key)

    pre_reservation_packet = _fresh_packet(workspace, case_id, deps.inspect_case)
    if packet_identity(pre_reservation_packet) != initial_id:
        raise ExplainCaseError("case evidence changed during explanation")

    deps.reserve_pilot(PILOT_ROOT, case_id, initial_id)
    result = deps.request_interpretation(pre_reservation_packet, api_key)

    final_packet = _fresh_packet(workspace, case_id, deps.inspect_case)
    if packet_identity(final_packet) != initial_id:
        raise ExplainCaseError("case evidence changed during explanation")

    report = build_offline_report(
        pre_reservation_packet, response_json=result["response_json"])
    record = make_stored_report(
        case_id, pre_reservation_packet, report, result["provenance"])
    deps.store_report(workspace, record)
    return _summary(record)


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "prepare":
            result = run_prepare(args.workspace, args.case_id)
        elif args.command == "preflight":
            result = run_preflight(args.env_file)
        else:
            result = run_live(args.workspace, args.case_id, args.env_file)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except TokenFactoryError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2
    except ExplainCaseError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"error": "explanation operation interrupted"}, sort_keys=True))
        return 130
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        print(json.dumps({"error": "explanation operation failed"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
