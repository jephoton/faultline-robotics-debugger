"""Prepare or request an evidence-bound explanation for a registered case."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
from typing import Callable, NamedTuple


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY_ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from robot_debug.case_store import inspect_case
from robot_debug.evidence_packet import make_evidence_packet, packet_identity
from robot_debug.explanation import build_offline_report, explain_rejection
from robot_debug.explanation_store import make_stored_report, store_report
from robot_debug.scenario_packet import (
    make_scenario_packet,
    scenario_packet_identity,
    validate_scenario_explanation,
)
from robot_debug.token_factory import (
    TokenFactoryError,
    load_api_key,
    preflight,
    request_interpretation,
    request_scenario_interpretation,
    reserve_pilot,
)


PILOT_ROOT = (
    REPOSITORY_ROOT / "artifacts" / "m5-nemotron-pilot-repair-20261006")
# October 10 v2 iteration: at most five labelled attempts, each with its own
# exclusive US$0.02 reservation (US$0.10 approved cap; v2-06/07 added October 10
# so that even worst-case reservations stay within it).
ATTEMPTS_ROOT = REPOSITORY_ROOT / "artifacts" / "m5-nemotron-attempts"
ATTEMPT_LABELS = ("v2-01", "v2-02", "v2-03", "v2-04", "v2-05", "v2-06", "v2-07")


class ExplainCaseError(ValueError):
    """A fixed, non-private CLI orchestration error."""


# Scenario reduction cases (M7) are plain JSON files written by report_scenario_reduction.py,
# not entries in the case store. Each live attempt reserves its own US$0.02 under this
# ignored folder; the label names the attempt.
SCENARIO_ATTEMPTS_ROOT = REPOSITORY_ROOT / "artifacts" / "m7-scenario-explanations"
_ATTEMPT_LABEL = re.compile(r"[a-z0-9][a-z0-9\-]{0,31}\Z")
_MAX_CASE_BYTES = 1_048_576


class Dependencies(NamedTuple):
    """Private orchestration seams used by offline unit tests."""

    inspect_case: Callable
    load_api_key: Callable
    preflight: Callable
    reserve_pilot: Callable
    request_interpretation: Callable
    store_report: Callable


class ScenarioDependencies(NamedTuple):
    """Private seams for the scenario commands, replaced by fakes in offline tests."""

    load_api_key: Callable
    preflight: Callable
    reserve_pilot: Callable
    request_scenario_interpretation: Callable


DEFAULT_SCENARIO_DEPENDENCIES = ScenarioDependencies(
    load_api_key=load_api_key,
    preflight=preflight,
    reserve_pilot=reserve_pilot,
    request_scenario_interpretation=request_scenario_interpretation,
)

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
    prepare.add_argument("--packet-version", type=int, choices=(1, 2), default=1)

    preflight_command = commands.add_parser("preflight")
    preflight_command.add_argument("--env-file", type=Path)

    live = commands.add_parser("live")
    live.add_argument("--workspace", type=Path, required=True)
    live.add_argument("--case-id", required=True)
    live.add_argument("--env-file", type=Path)
    live.add_argument("--packet-version", type=int, choices=(1, 2), default=1)
    live.add_argument("--attempt", choices=ATTEMPT_LABELS)

    scenario_prepare = commands.add_parser("scenario-prepare")
    scenario_prepare.add_argument("--case", type=Path, required=True)
    scenario_prepare.add_argument("--packet-out", type=Path)

    scenario_live = commands.add_parser("scenario-live")
    scenario_live.add_argument("--case", type=Path, required=True)
    scenario_live.add_argument("--out", type=Path, required=True)
    scenario_live.add_argument("--env-file", type=Path)
    scenario_live.add_argument("--attempt", required=True)
    return parser


def _fresh_packet(workspace: Path, case_id: str, inspect: Callable,
                  packet_version: int = 1) -> dict:
    case = inspect(workspace, case_id)
    try:
        available = case["capabilities"]["inspection"]["status"] == "available"
    except (KeyError, TypeError):
        available = False
    if not available:
        raise ExplainCaseError("case evidence is unavailable or changed")
    return make_evidence_packet(case, schema_version=packet_version)


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
                *, deps: Dependencies = DEFAULT_DEPENDENCIES,
                packet_version: int = 1) -> dict:
    """Store a deterministic offline report without loading credentials."""
    packet = _fresh_packet(workspace, case_id, deps.inspect_case, packet_version)
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
             *, deps: Dependencies = DEFAULT_DEPENDENCIES,
             packet_version: int = 1, attempt: str | None = None) -> dict:
    """Reserve and make one approved paid attempt, then store safely."""
    if attempt is not None and attempt not in ATTEMPT_LABELS:
        raise ExplainCaseError("unknown attempt label")
    pilot_root = PILOT_ROOT if attempt is None else ATTEMPTS_ROOT / attempt
    initial_packet = _fresh_packet(workspace, case_id, deps.inspect_case, packet_version)
    initial_id = packet_identity(initial_packet)

    api_key = deps.load_api_key(env_file)
    deps.preflight(api_key)

    pre_reservation_packet = _fresh_packet(workspace, case_id, deps.inspect_case, packet_version)
    if packet_identity(pre_reservation_packet) != initial_id:
        raise ExplainCaseError("case evidence changed during explanation")

    if attempt is not None:
        pilot_root.mkdir(parents=True, exist_ok=True)
    deps.reserve_pilot(pilot_root, case_id, initial_id)
    result = deps.request_interpretation(pre_reservation_packet, api_key)
    if attempt is not None and "rejected_content" in result:
        diagnosis = {"reason": explain_rejection(result["rejected_content"],
                                                 pre_reservation_packet),
                     "content": result["rejected_content"]}
        with (pilot_root / "rejected-response.json").open("x", encoding="utf-8") as handle:
            json.dump(diagnosis, handle, ensure_ascii=False, indent=2)

    final_packet = _fresh_packet(workspace, case_id, deps.inspect_case, packet_version)
    if packet_identity(final_packet) != initial_id:
        raise ExplainCaseError("case evidence changed during explanation")

    report = build_offline_report(
        pre_reservation_packet, response_json=result["response_json"])
    record = make_stored_report(
        case_id, pre_reservation_packet, report, result["provenance"])
    deps.store_report(workspace, record)
    return _summary(record)


def _scenario_packet(case_path: Path) -> tuple:
    """Read a scenario case file and project it to the bounded packet (case id, packet)."""
    try:
        if Path(case_path).stat().st_size > _MAX_CASE_BYTES:
            raise ExplainCaseError("invalid scenario case")
        case = json.loads(Path(case_path).read_text(encoding="utf-8"))
        packet = make_scenario_packet(case)
        case_id = case["case_id"]
    except ExplainCaseError:
        raise
    except Exception:
        raise ExplainCaseError("invalid scenario case") from None
    return case_id, packet


def _write_new(path: Path, value: dict) -> None:
    try:
        with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False)
            handle.write("\n")
    except FileExistsError:
        raise ExplainCaseError("an output file exists") from None
    except OSError:
        raise ExplainCaseError("an output file could not be written") from None


def run_scenario_prepare(case_path: Path, packet_out: Path | None = None) -> dict:
    """Build the bounded packet for a scenario reduction case offline (no credentials, no network)."""
    case_id, packet = _scenario_packet(case_path)
    if packet_out is not None:
        _write_new(packet_out, packet)
    return {"case_id": case_id, "packet_id": scenario_packet_identity(packet),
            "evidence_ids": [item["evidence_id"] for item in packet["evidence"]],
            "measured_verdict": None if packet["measured"] is None else packet["measured"]["verdict"]}


def run_scenario_live(case_path: Path, out: Path, env_file: Path | None, attempt: str,
                      *, deps: ScenarioDependencies = DEFAULT_SCENARIO_DEPENDENCIES) -> dict:
    """Reserve and make one paid attempt for a scenario case, then store the validated result."""
    if type(attempt) is not str or _ATTEMPT_LABEL.fullmatch(attempt) is None:
        raise ExplainCaseError("unknown attempt label")
    if Path(out).exists():
        raise ExplainCaseError("an output file exists")
    case_id, packet = _scenario_packet(case_path)
    packet_id = scenario_packet_identity(packet)
    api_key = deps.load_api_key(env_file)
    deps.preflight(api_key)
    deps.reserve_pilot(SCENARIO_ATTEMPTS_ROOT / attempt, case_id, packet_id)
    result = deps.request_scenario_interpretation(packet, api_key)
    interpretation = None
    status, error_code = "absent", result["provenance"].get("error_code")
    if result["response_json"] is not None:
        try:
            interpretation = validate_scenario_explanation(result["response_json"], packet)
            status = "validated-structure"
        except Exception:
            status, error_code = "rejected", "invalid_explanation"
    record = {"schema_version": 1, "kind": "scenario_explanation", "case_id": case_id,
              "packet_id": packet_id, "packet": packet, "interpretation_status": status,
              "interpretation": interpretation, "error_code": error_code,
              "provenance": result["provenance"],
              "disclaimer": "The packet counts reruns only. Necessary and sufficient are relative to the "
                            "final selection, which is a local minimum; there is no causal proof and the "
                            "interpretation requires human review."}
    _write_new(out, record)
    return {"case_id": case_id, "packet_id": packet_id, "interpretation_status": status,
            "request_status": result["provenance"]["request_status"],
            "estimated_cost_usd": result["provenance"].get("estimated_cost_usd")}


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "prepare":
            result = run_prepare(args.workspace, args.case_id,
                                 packet_version=args.packet_version)
        elif args.command == "preflight":
            result = run_preflight(args.env_file)
        elif args.command == "scenario-prepare":
            result = run_scenario_prepare(args.case, args.packet_out)
        elif args.command == "scenario-live":
            result = run_scenario_live(args.case, args.out, args.env_file, args.attempt)
        else:
            result = run_live(args.workspace, args.case_id, args.env_file,
                              packet_version=args.packet_version, attempt=args.attempt)
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
