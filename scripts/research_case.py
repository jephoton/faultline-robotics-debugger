"""Plan, retrieve and summarize public research context for a registered case."""

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
from robot_debug.research_query import ResearchQueryError, build_queries
from robot_debug.research_store import (
    ResearchStoreError,
    assign_sources,
    make_research_record,
    not_requested_summary,
    read_case_research,
    store_research_record,
    with_summary,
)
from robot_debug.research_summary import (
    ATTEMPT_LABELS,
    ResearchSummaryError,
    build_summary,
    rejection_reason,
    research_context,
    reserve_attempt,
)
from robot_debug.tavily_search import (
    CACHE_ROOT as DEFAULT_CACHE_ROOT,
    LEDGER_ROOT as DEFAULT_LEDGER_ROOT,
    TavilyError,
    load_api_key as load_tavily_key,
    search as tavily_search,
)
from robot_debug.token_factory import (
    TokenFactoryError,
    check_research_request,
    load_api_key as load_nebius_key,
    preflight,
    request_research_summary,
)


# Approved October 11 (ADR 0024): Tavily 50 credits in total, Nemotron five
# labelled attempts with exclusive US$0.01 reservations (US$0.05 in total).
LEDGER_ROOT = DEFAULT_LEDGER_ROOT
CACHE_ROOT = DEFAULT_CACHE_ROOT
ATTEMPTS_ROOT = REPOSITORY_ROOT / "artifacts" / "m5d-research" / "nemotron"


class ResearchCaseError(ValueError):
    """A fixed, non-private CLI orchestration error."""


class Dependencies(NamedTuple):
    """Private orchestration seams used by offline unit tests."""

    inspect_case: Callable
    load_tavily_key: Callable
    tavily_search: Callable
    load_nebius_key: Callable
    preflight: Callable
    check_research_request: Callable
    reserve_attempt: Callable
    request_research_summary: Callable
    read_case_research: Callable
    store_research_record: Callable


DEFAULT_DEPENDENCIES = Dependencies(
    inspect_case=inspect_case,
    load_tavily_key=load_tavily_key,
    tavily_search=tavily_search,
    load_nebius_key=load_nebius_key,
    preflight=preflight,
    check_research_request=check_research_request,
    reserve_attempt=reserve_attempt,
    request_research_summary=request_research_summary,
    read_case_research=read_case_research,
    store_research_record=store_research_record,
)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ResearchCaseError("invalid arguments")


def _parser() -> argparse.ArgumentParser:
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)

    queries = commands.add_parser("queries")
    queries.add_argument("--workspace", type=Path, required=True)
    queries.add_argument("--case-id", required=True)

    search = commands.add_parser("search")
    search.add_argument("--workspace", type=Path, required=True)
    search.add_argument("--case-id", required=True)
    search.add_argument("--refresh", action="store_true")
    search.add_argument("--env-file", type=Path)

    summarize = commands.add_parser("summarize")
    summarize.add_argument("--workspace", type=Path, required=True)
    summarize.add_argument("--case-id", required=True)
    summarize.add_argument("--attempt", required=True, choices=ATTEMPT_LABELS)
    summarize.add_argument("--env-file", type=Path)
    return parser


def _fresh_packet(workspace: Path, case_id: str, inspect: Callable) -> dict:
    case = inspect(workspace, case_id)
    try:
        available = case["capabilities"]["inspection"]["status"] == "available"
    except (KeyError, TypeError):
        available = False
    if not available:
        raise ResearchCaseError("case evidence is unavailable or changed")
    return make_evidence_packet(case, schema_version=2)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_queries(workspace: Path, case_id: str,
                *, deps: Dependencies = DEFAULT_DEPENDENCIES) -> dict:
    """Print the planned queries; no credentials and no network."""
    packet = _fresh_packet(workspace, case_id, deps.inspect_case)
    return {"case_id": case_id, "queries": build_queries(packet)}


def run_search(workspace: Path, case_id: str, env_file: Path | None,
               *, refresh: bool = False,
               deps: Dependencies = DEFAULT_DEPENDENCIES) -> dict:
    """Retrieve sources for the planned queries and store a summary-less record."""
    initial_packet = _fresh_packet(workspace, case_id, deps.inspect_case)
    initial_id = packet_identity(initial_packet)
    queries = build_queries(initial_packet)

    api_key = deps.load_tavily_key(env_file)
    searches = [
        deps.tavily_search(query, api_key, ledger_root=LEDGER_ROOT,
                           cache_root=CACHE_ROOT, refresh=refresh)
        for query in queries]

    final_packet = _fresh_packet(workspace, case_id, deps.inspect_case)
    if packet_identity(final_packet) != initial_id:
        raise ResearchCaseError("case evidence changed during research")
    record = make_research_record(
        case_id, final_packet, assign_sources(searches), not_requested_summary(_utc_now()))
    deps.store_research_record(workspace, record)
    return {
        "case_id": case_id,
        "record_id": record["record_id"],
        "queries": len(searches),
        "sources": sum(len(entry["results"]) for entry in record["queries"]),
        "cached_queries": sum(1 for item in searches if item["from_cache"]),
        "tavily_credits_used": sum(item["credits"] for item in searches
                                   if not item["from_cache"]),
        "summary_status": record["summary"]["status"],
    }


def run_summarize(workspace: Path, case_id: str, env_file: Path | None, attempt: str,
                  *, deps: Dependencies = DEFAULT_DEPENDENCIES) -> dict:
    """Reserve one labelled attempt, ask Nemotron for a cited note, store a new record."""
    if attempt not in ATTEMPT_LABELS:
        raise ResearchCaseError("unknown attempt label")
    initial_packet = _fresh_packet(workspace, case_id, deps.inspect_case)
    initial_id = packet_identity(initial_packet)
    records = deps.read_case_research(workspace, case_id)["records"]
    if not records:
        raise ResearchCaseError("no research record for the current case evidence")
    record = records[-1]
    if record["packet_id"] != initial_id:
        raise ResearchCaseError("case evidence changed during research")
    context = research_context(initial_packet, record)
    deps.check_research_request(context)

    api_key = deps.load_nebius_key(env_file)
    deps.preflight(api_key)

    pre_reservation_packet = _fresh_packet(workspace, case_id, deps.inspect_case)
    if packet_identity(pre_reservation_packet) != initial_id:
        raise ResearchCaseError("case evidence changed during research")

    deps.reserve_attempt(ATTEMPTS_ROOT / attempt, attempt, case_id, initial_id,
                         record["record_id"])
    result = deps.request_research_summary(context, api_key)
    if "rejected_content" in result:
        diagnosis = {"reason": rejection_reason(result["rejected_content"], context),
                     "content": result["rejected_content"]}
        (ATTEMPTS_ROOT / attempt).mkdir(parents=True, exist_ok=True)
        with (ATTEMPTS_ROOT / attempt / "rejected-response.json").open(
                "x", encoding="utf-8") as handle:
            json.dump(diagnosis, handle, ensure_ascii=False, indent=2)

    final_packet = _fresh_packet(workspace, case_id, deps.inspect_case)
    if packet_identity(final_packet) != initial_id:
        raise ResearchCaseError("case evidence changed during research")
    summary = build_summary(result, context)
    stored = with_summary(record, summary)
    deps.store_research_record(workspace, stored)
    return {
        "case_id": case_id,
        "record_id": stored["record_id"],
        "attempt": attempt,
        "summary_status": stored["summary"]["status"],
        "request_status": stored["summary"]["provenance"]["request_status"],
        "estimated_cost_usd": stored["summary"]["provenance"]["estimated_cost_usd"],
    }


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "queries":
            result = run_queries(args.workspace, args.case_id)
        elif args.command == "search":
            result = run_search(args.workspace, args.case_id, args.env_file,
                                refresh=args.refresh)
        else:
            result = run_summarize(args.workspace, args.case_id, args.env_file,
                                   args.attempt)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except (TavilyError, TokenFactoryError, ResearchCaseError, ResearchQueryError,
            ResearchStoreError, ResearchSummaryError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"error": "research operation interrupted"}, sort_keys=True))
        return 130
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        print(json.dumps({"error": "research operation failed"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
