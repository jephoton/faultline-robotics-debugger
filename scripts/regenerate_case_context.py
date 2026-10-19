"""Rebuild the explanation, next steps and report of a finished run's cases, locally.

For one run folder (``artifacts/runs/<run>``), for each of its cases this

* adds the case's shrink history (``minimal.shrink_history``) from the candidate logs of every reduction Job
  the run saved (the first ``reduce`` and its continuations ``reduce2``, ``reduce3``...), so the explanation
  packet and the report no longer lose a part that a continuation shrank, and every rerun of the case
  (``reruns``, for the case page's "why it is trustworthy" section). The case id does not change;
* asks Nemotron 3 Ultra again for the scenario explanation (one Token Factory call per scenario case);
* recomputes the next steps (one Token Factory call per case) from the Tavily results already stored in the
  case's ``research.json``: no new search, no Tavily credit spent;
* rewrites ``report.md`` with the current report scripts (scenario and stress-test cases) from the run's saved
  summaries: no Job, no network;
* registers the run again, so the viewer library sees the new files.

It makes no cloud Job and no Tavily call. Replaced files are kept beside the new ones as
``explanation.previous.json`` and ``research.previous.json``; a new explanation or next-steps answer replaces the
old one only when it passes its checks. ``--dry-run`` prints what would be called and an estimate of the Token
Factory cost, loads no key and changes nothing. The Token Factory key comes from the environment or ``--env-file``
and is never printed.

    python scripts/regenerate_case_context.py artifacts/runs/<run> [--env-file .env] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY_ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from robot_debug import next_steps as ns                      # noqa: E402
from robot_debug import orchestrator as orch                  # noqa: E402
from robot_debug import pipeline_research as pr               # noqa: E402
from robot_debug import scenario_experiment as se             # noqa: E402
from robot_debug import token_factory as tf                   # noqa: E402
from robot_debug.case_register import reregister_run          # noqa: E402

# Ultra's price is not pinned in code (ADR 0030), so the cost is bounded by the reservation figure the code
# already uses for one explanation call, and described as about one cent each. A next-steps call whose first
# answer fails validation is repaired with one more call, so its ceiling doubles.
CEILING_USD_PER_CALL = float(tf.NEXT_STEPS_RESERVATION_USD)
NEXT_STEPS_MAX_CALLS = 2
TYPICAL_USD_PER_CALL = 0.01
BYTES_PER_TOKEN = 3.0                    # a deliberately low figure: the token estimate is an upper bound


class RegenerateError(ValueError):
    """A fixed, non-secret message about why the run cannot be processed."""


class Deps(NamedTuple):
    """The outside calls, so a test can fake Token Factory and the registration."""

    explain: Callable[..., Mapping[str, Any]]            # (case_path, out_path, env_file, label) -> summary
    research: pr.ResearchDeps
    reregister: Callable[..., List[str]]                 # (run_dir, root) -> case ids
    now: Callable[[], dt.datetime]


def default_deps() -> Deps:
    module = orch._load_script("explain_case")
    return Deps(module.run_scenario_live, pr.default_deps(), reregister_run,
                lambda: dt.datetime.now(dt.timezone.utc))


# --- small file helpers ----------------------------------------------------------------------------------

def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path: Path, value: Any) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=1, sort_keys=True, allow_nan=False) + "\n",
                         encoding="utf-8", newline="\n")
    os.replace(str(temporary), str(path))


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(str(temporary), str(path))


def _inside(run_dir: Path, relative: Any) -> Optional[Path]:
    """``run_dir/relative`` when it is an ordinary file inside the run folder, else ``None``."""

    if type(relative) is not str or not relative or "\\" in relative or relative.startswith("/"):
        return None
    if any(part in ("", ".", "..") for part in relative.split("/")):
        return None
    try:
        path = (run_dir / relative).resolve(strict=True)
        path.relative_to(run_dir.resolve(strict=True))
    except (OSError, ValueError):
        return None
    return path if path.is_file() else None


def step_summary(run_dir: Path, steps: Mapping[str, Any], name: str) -> Optional[Dict[str, Any]]:
    record = steps.get(name)
    path = _inside(run_dir, record.get("summary")) if isinstance(record, Mapping) else None
    return None if path is None else read_json(path)


def reduction_summaries(run_dir: Path, steps: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The saved ``scenario-reduce`` summaries in Job order: ``reduce``, ``reduce2``, ``reduce3``..."""

    names = [name for name in steps if name == "reduce" or (name.startswith("reduce") and name[6:].isdigit())]
    names.sort(key=lambda name: int(name[6:] or 1))
    found = [step_summary(run_dir, steps, name) for name in names]
    return [summary for summary in found if summary is not None and isinstance(summary.get("reduction"), Mapping)]


def best_reduction(reductions: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """The summary a case is built from: the last reduction whose final selection itself passed the gate."""

    return next((r for r in reversed(reductions) if orch.verified_selection(r.get("reduction") or {})),
                reductions[-1])


def case_folders(run_dir: Path) -> List[Tuple[str, Path]]:
    """Where the run's cases live: ``cases/<name>/`` for a probing run, else the run folder itself."""

    found = [(name, run_dir / "cases" / name) for name in ("audit", "wording")
             if (run_dir / "cases" / name / "case.json").is_file()]
    if not found and (run_dir / "case.json").is_file():
        found = [("case", run_dir)]
    return found


# --- the plan ----------------------------------------------------------------------------------------------

class CasePlan(NamedTuple):
    name: str
    folder: Path
    case: Dict[str, Any]                       # with the shrink history applied (in memory)
    case_changed: bool                         # the shrink history or the reruns are added to case.json
    explain_bytes: Optional[int]               # None: no explanation call (not a scenario case, or no packet)
    next_context: Optional[Dict[str, Any]]     # None: no next-steps call
    next_bytes: Optional[int]
    notes: List[str]


def plan_case(run_dir: Path, steps: Mapping[str, Any], name: str, folder: Path) -> CasePlan:
    case = read_json(folder / "case.json")
    if case is None:
        raise RegenerateError("case.json of the {} case is unreadable".format(name))
    notes: List[str] = []
    case_changed = False
    explain_bytes = None
    if case.get("kind") == "scenario_reduction" and isinstance(case.get("minimal"), Mapping):
        reductions = reduction_summaries(run_dir, steps)
        history = se.shrink_history(reductions)
        if reductions:
            reruns = se.all_reruns(best_reduction(reductions)["reduction"])
            if case["minimal"].get("shrink_history") != history:
                case = dict(case, minimal=dict(case["minimal"], shrink_history=history))
                case_changed = True
            if case.get("reruns") != reruns:
                case = dict(case, reruns=reruns)
                case_changed = True
        else:
            notes.append("no saved reduction summaries: the shrink history and reruns stay as the case has them")
        try:
            from robot_debug.scenario_packet import make_scenario_packet

            explain_bytes = len(json.dumps(tf._scenario_explanation_payload(make_scenario_packet(case)),
                                           ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        except Exception:                       # noqa: BLE001 - reported below; the call would fail the same way
            notes.append("the explanation packet cannot be built from this case: no explanation call")
    next_context = next_bytes = None
    research = read_json(folder / "research.json")
    if research is None or not isinstance(research.get("queries"), list):
        notes.append("no research record (research was off for this run): no next steps")
    else:
        try:
            next_context = pr.build_context(case, research["queries"], run_dir)
            if next_context is None:
                notes.append("the research record holds no sources: no next steps")
            else:
                next_bytes = tf.next_steps_request_size(next_context)
        except (tf.TokenFactoryError, KeyError, TypeError):
            next_context = None
            notes.append("the next-steps request cannot be built from the stored research: no next steps")
    return CasePlan(name, folder, case, case_changed, explain_bytes, next_context, next_bytes, notes)


def estimate_tokens(size_bytes: int) -> int:
    return int(size_bytes / BYTES_PER_TOKEN) + 1


def describe(run_dir: Path, plans: Sequence[CasePlan], out: Callable[[str], None]) -> Tuple[int, float]:
    """Print what would be called; returns ``(Token Factory calls, cost ceiling in USD)``."""

    out("Run {}: {} case(s). No cloud Job and no Tavily call (stored search results are reused).".format(
        run_dir.name, len(plans)))
    calls = 0
    repairable = 0                              # next-steps calls, each of which may need one repair call
    for plan in plans:
        out("  [{}] {} case".format(plan.name, plan.case.get("kind")))
        if plan.case_changed:
            out("    case.json: add minimal.shrink_history and reruns from the saved reduction summaries "
                "(case id unchanged)")
        if plan.case.get("kind") in ("scenario_reduction", "audit"):
            out("    report.md: rebuilt locally from the saved summaries (no call)")
        if plan.explain_bytes is not None:
            calls += 1
            out("    explanation: 1 Token Factory call, {}, request {} bytes (about {} input tokens, at most {} "
                "output)".format(tf.SCENARIO_EXPLAIN_MODEL, plan.explain_bytes, estimate_tokens(plan.explain_bytes),
                                 tf._MAX_TOKENS_SCENARIO_EXPLAIN))
        if plan.next_bytes is not None:
            calls += 1
            repairable += 1
            out("    next steps: 1 call per case (2 if the first answer needs repair), {}, request {} bytes (about {} input tokens, at most {} "
                "output), {} cached source(s)".format(
                    tf.NEXT_STEPS_MODEL, plan.next_bytes, estimate_tokens(plan.next_bytes),
                    tf._MAX_TOKENS_NEXT_STEPS, len(plan.next_context["sources"])))
        for note in plan.notes:
            out("    note: " + note)
    ceiling = (calls + repairable * (NEXT_STEPS_MAX_CALLS - 1)) * CEILING_USD_PER_CALL
    out("Token Factory: {} call(s). Estimated cost about US${:.2f} (US${:.2f} per call typically; ceiling US${:.2f} "
        "at the US${:.2f} reservation per call, counting a repair call for every next-steps call). Nemotron 3 Ultra's price is not pinned in code: reconcile with "
        "billing.".format(calls, calls * TYPICAL_USD_PER_CALL, TYPICAL_USD_PER_CALL, ceiling, CEILING_USD_PER_CALL))
    out("Then: register the run again (case ids unchanged).")
    return calls, ceiling


# --- the work ----------------------------------------------------------------------------------------------

def _label(deps: Deps, run_dir: Path, case_id: str) -> str:
    stamp = deps.now().strftime("%Y%m%dT%H%M%SZ")
    return "g" + hashlib.sha256((run_dir.name + case_id + stamp).encode("utf-8")).hexdigest()[:20]


def rebuild_explanation(deps: Deps, plan: CasePlan, env_file: Optional[Path], run_dir: Path,
                        out: Callable[[str], None]) -> None:
    folder = plan.folder
    fresh = folder / "explanation.json.new"
    fresh.unlink(missing_ok=True)
    summary = deps.explain(folder / "case.json", fresh, env_file, _label(deps, run_dir, plan.case["case_id"]))
    record = read_json(fresh)
    status = (record or {}).get("interpretation_status", summary.get("interpretation_status"))
    if record is None or status != "validated-structure":
        fresh.unlink(missing_ok=True)
        out("    explanation: the new answer was not accepted ({}); the old explanation is kept".format(status))
        return
    current = folder / "explanation.json"
    if current.exists():
        os.replace(str(current), str(folder / "explanation.previous.json"))
    os.replace(str(fresh), str(current))
    out("    explanation: replaced (the old one is explanation.previous.json)")


def rebuild_next_steps(deps: Deps, plan: CasePlan, env_file: Optional[Path], out: Callable[[str], None]) -> None:
    folder = plan.folder
    research = read_json(folder / "research.json") or {}
    block = pr.request_record(plan.next_context, env_file, deps.research)
    had = isinstance(research.get("next_steps"), Mapping) and research["next_steps"].get("status") == "interpreted"
    if block["status"] != "interpreted" and had:
        out("    next steps: the new answer was not accepted ({}); the old next steps are kept".format(block["status"]))
        return
    updated = {key: value for key, value in research.items() if key != "summary"}
    updated["next_steps"] = block
    write_json(folder / "research.previous.json", research)
    write_json(folder / "research.json", updated)
    out("    next steps: {} ({} item(s))".format(block["status"], len(block["items"])))


def rebuild_report(plan: CasePlan, run_dir: Path, steps: Mapping[str, Any], out: Callable[[str], None]) -> None:
    """``report.md`` for a scenario or stress-test case from the run's saved summaries, with the current scripts."""

    case, folder = plan.case, plan.folder
    ledger = read_json(run_dir / "ledger.json") or {}
    hourly = ledger.get("hourly_usd") if isinstance(ledger.get("hourly_usd"), (int, float)) else None
    if case.get("kind") == "scenario_reduction":
        reductions = reduction_summaries(run_dir, steps)
        if not reductions:
            out("    report.md: kept (no saved reduction summaries)")
            return
        best = best_reduction(reductions)
        module = orch._load_script("report_scenario_reduction")
        text = module.build_report(best, step_summary(run_dir, steps, "screen"), hourly, reductions)
    elif case.get("kind") == "audit":
        groups = case.get("groups")
        if groups:
            summaries = [step_summary(run_dir, steps, g.get("step")) for g in groups
                         if isinstance(g, Mapping) and isinstance(g.get("step"), str)]
            missing = "a group's saved summary is missing"
        else:
            summaries = [step_summary(run_dir, steps, "audit")]
            missing = "the legacy audit step's saved summary is missing"
        if not summaries or any(s is None for s in summaries):
            out("    report.md: kept ({})".format(missing))
            return
        module = orch._load_script("report_m6_experiment")
        text = module.render_report(summaries, title=module.stress_test_title(summaries))
        if case.get("thresholds_unconfirmed"):
            text = text.rstrip("\n") + orch.THRESHOLDS_UNCONFIRMED_NOTE
    else:
        return
    write_text(folder / "report.md", text if text.endswith("\n") else text + "\n")
    out("    report.md: rebuilt")


def regenerate(run_dir: Path, env_file: Optional[Path] = None, *, dry_run: bool = False,
               deps: Optional[Deps] = None, diagnoses_root: Optional[Path] = None,
               out: Callable[[str], None] = print) -> int:
    """Process one run folder; returns an exit status (0 done, 1 some step failed, 2 the run cannot be used)."""

    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise RegenerateError("the run folder does not exist")
    steps = (read_json(run_dir / "steps.json") or {}).get("steps")
    if not isinstance(steps, Mapping):
        raise RegenerateError("the run folder has no steps.json")
    folders = case_folders(run_dir)
    if not folders:
        raise RegenerateError("the run has no case to rebuild")
    plans = [plan_case(run_dir, steps, name, folder) for name, folder in folders]
    calls, _ceiling = describe(run_dir, plans, out)
    if dry_run:
        out("Dry run: nothing was called, written or registered.")
        return 0
    deps = deps or default_deps()
    if calls:
        deps.research.load_nebius_key(env_file)          # fail before any change if the key is missing
    failed = 0
    before = sorted(plan.case["case_id"] for plan in plans)
    for plan in plans:
        out("[{}] {}".format(plan.name, plan.case.get("kind")))
        if plan.case_changed:
            write_json(plan.folder / "case.json", plan.case)
            out("    case.json: shrink history and reruns added")
        for label, active, step in (
                ("explanation", plan.explain_bytes is not None,
                 lambda p=plan: rebuild_explanation(deps, p, env_file, run_dir, out)),
                ("next steps", plan.next_context is not None,
                 lambda p=plan: rebuild_next_steps(deps, p, env_file, out)),
                ("report", plan.case.get("kind") in ("scenario_reduction", "audit"),
                 lambda p=plan: rebuild_report(p, run_dir, steps, out))):
            if not active:
                continue
            try:
                step()
            except Exception as error:                  # noqa: BLE001 - only the type is shown, never a message
                failed += 1
                out("    {}: FAILED ({})".format(label, type(error).__name__))
    ids = sorted(deps.reregister(run_dir, diagnoses_root))
    if ids != before:
        raise RegenerateError("the case ids changed on registration; stop and check the run folder")
    out("Registered {} case(s) again; ids unchanged.".format(len(ids)))
    return 1 if failed else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path, help="a finished run folder, for example artifacts/runs/<run>")
    parser.add_argument("--env-file", type=Path, help="dotenv file with NEBIUS_API_KEY (else the environment)")
    parser.add_argument("--dry-run", action="store_true", help="print the calls and the estimated cost; change nothing")
    parser.add_argument("--diagnoses-root", type=Path, help="register here instead of artifacts/diagnoses")
    try:
        args = parser.parse_args(argv)
        return regenerate(args.run_dir, args.env_file, dry_run=args.dry_run, diagnoses_root=args.diagnoses_root)
    except RegenerateError as error:
        print("regenerate rejected: {}".format(error), file=sys.stderr)
        return 2
    except tf.TokenFactoryError as error:
        print("regenerate stopped: Token Factory ({})".format(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
