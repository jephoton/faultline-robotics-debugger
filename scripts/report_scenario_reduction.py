"""Write the Markdown report and the case record for a scenario Job summary.

    report_scenario_reduction.py SUMMARY.json [--screen SCREEN_SUMMARY.json]
        [--out REPORT.md] [--case-out CASE.json] [--candidate-out CANDIDATE.json]
        [--hourly-rate USD]

``SUMMARY.json`` is the ``scenario_summary.json`` of a ``scenario-reduce`` Job (a report
and a case are written) or of a ``scenario-screen`` Job (the screen report only). For a
reduction, ``--screen`` adds the screen table of the screen it was planned from.

The report states what the simulator showed (outcomes of reruns), the minimal cause in
one sentence, the Nemotron hypothesis, its source or fallback, and the mechanical
verdict (``confirmed``, ``partly`` or ``refuted``). The case record holds the replay
recipe as a scenario candidate file plus the three video references. Nothing here
decides a claim: the result is a local minimum found by reruns, not proof of the
globally smallest cause.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from robot_debug import scenario_experiment as se
from robot_debug.scenario_import import ScenarioImportError, validate_scenario_candidate, write_scenario_candidate

LETTERS = {"success": "S", "policy_failure": "F", "invalid_scene": "I"}


class ReportError(ValueError):
    """A fixed, non-secret problem with the input."""


def load_summary(path: Path) -> Dict[str, Any]:
    try:
        summary = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ReportError("the summary is unreadable") from None
    if not isinstance(summary, dict) or summary.get("schema_version") != 1 \
            or summary.get("mode") not in se.SCENARIO_MODES:
        raise ReportError("not a scenario summary")
    return summary


def _letters(outcomes: Sequence[Any]) -> str:
    return " ".join(LETTERS.get(item, "?") for item in outcomes) if outcomes else "-"


def _cell(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def _table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> List[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(_cell(item) for item in row) + " |" for row in rows]
    return lines


def _number(value: Any, digits: int = 1) -> str:
    return "-" if not isinstance(value, (int, float)) else "{:.{}f}".format(value, digits)


# ---- screen -------------------------------------------------------------------------


def screen_section(summary: Mapping[str, Any]) -> List[str]:
    lines = ["## Screen", "",
             "Outcomes per start: S success, F policy failure, I invalid scene. The first letter is the "
             "unperturbed screen attempt; failing starts were confirmed with more attempts (4 of 5 "
             "failures reproduce).", ""]
    rows = []
    for task_id, task in sorted(summary.get("tasks", {}).items(), key=lambda item: int(item[0])):
        starts = task.get("starts", {})
        for index, start in sorted(starts.items(), key=lambda item: int(item[0])):
            outcomes = start.get("outcomes") or []
            decision = start.get("decision") or ("passed" if outcomes and outcomes[0] == "success" else "-")
            steps = [s for s in start.get("steps") or [] if isinstance(s, int)]
            rows.append([task_id, index, _letters(outcomes), decision, max(steps) if steps else "-"])
    lines += _table(["task", "start", "outcomes", "decision", "max steps"], rows)
    lines += ["", "Instructions:", ""]
    for task_id, task in sorted(summary.get("tasks", {}).items(), key=lambda item: int(item[0])):
        lines.append("- task {}: {}".format(task_id, task.get("instruction") or "unknown"))
    failures = summary.get("reproducible_failures") or []
    lines += ["", "Starts that failed at least 4 of 5 attempts: {}".format(
        ", ".join("task {} start {}".format(f["task_id"], f["start_index"]) for f in failures) or "none"), ""]
    confirm = summary.get("confirm") or {}
    lines += ["Attempts skipped by early decisions: {}; top-up episodes: {}.".format(
        confirm.get("skipped_attempts", 0), (summary.get("topup") or {}).get("episodes", 0)), ""]
    return lines


# ---- reduction ----------------------------------------------------------------------


def _selection_text(selection: Optional[Mapping[str, Mapping[str, float]]]) -> str:
    if not selection:
        return "(none)"
    return "; ".join("{} ({})".format(entity, ", ".join(
        "{} {:g}".format(component, t) for component, t in parts.items())) for entity, parts in selection.items())


def difference_rows(table: Sequence[Mapping[str, Any]]) -> List[List[Any]]:
    rows = []
    for row in table:
        position = row.get("position") or {}
        rotation = row.get("rotation") or {}
        joints = row.get("joints") or []
        rows.append([
            row.get("entity"),
            _number(position.get("distance_m") * 100.0 if position.get("distance_m") is not None else None),
            _number(rotation.get("angle_deg")),
            ", ".join("{} {:+.3g} {}".format(j["name"], j["offset"], j.get("unit", "")) for j in joints) or "-",
            _number(row.get("distance")),
        ])
    return rows


def reduction_section(summary: Mapping[str, Any], hourly_rate: Optional[float]) -> List[str]:
    plan, reduction = summary["plan"], summary.get("reduction") or {}
    selection = reduction.get("final_selection")
    reference = reduction.get("reference")
    sentence = se.describe_minimal_cause(
        selection or {}, summary.get("differences") or [], reference=reference,
        bisection_steps=reduction.get("bisection_steps"), reduced=bool(reduction.get("reduced")),
        required_failures=reduction.get("required_failures", 4), attempts=reduction.get("attempts", 5))
    lines = ["## Result", "",
             "- Stop reason: `{}`".format(reduction.get("stop_reason")),
             "- Failing start: {}; reference (nearest passing start): {}; candidate references tried: {}".format(
                 plan["failing_start"], reference,
                 ", ".join("{} ({})".format(r["id"], r["decision"]) for r in reduction.get("references_tried") or []) or "-"),
             "- Entity-minimal: {}".format("yes" if reduction.get("entity_minimal") else "no"), "",
             "### Minimal cause", ""]
    lines += [sentence if selection else "No minimal cause was established (stop reason `{}`).".format(
        reduction.get("stop_reason")), ""]
    if reduction.get("note"):
        lines += ["Note: {}".format(reduction["note"]), ""]
    lines += ["Final selection: {}. This is a local minimum found by reruns, not proof of the globally "
              "smallest cause.".format(_selection_text(selection)), ""]
    if reduction.get("parts"):
        lines += _table(["entity", "part", "fraction t", "lower bound tested", "resolution"],
                        [[p["entity"], p["component"], p["t"], p["lower"] if p.get("lower_tested") else "-",
                          p["resolution"]] for p in reduction["parts"]]) + [""]
    lines += ["## Differences between the failing start and the reference", ""]
    table = summary.get("differences") or []
    lines += (_table(["entity", "position (cm)", "rotation (deg)", "joints", "score"], difference_rows(table))
              if table else ["(none)"])
    lines += ["", "Score is centimetres plus degrees / 10, summed over the changed parts.", ""]
    hypothesis = plan["hypothesis"]
    ranking = hypothesis.get("ranking") or plan.get("order") or []
    verdict = se.verdict_for(plan, reduction)
    if plan.get("order_source") != "model":
        verdict_text = "not applicable (the fixed order is a search order, not a model hypothesis)"
    else:
        verdict_text = verdict or "not available"
    lines += ["## Hypothesis", "",
              "- Order source: `{}`{}".format(
                  plan.get("order_source"), "" if plan.get("order_source") == "model" else
                  " (fixed order: largest difference first; {})".format(
                      hypothesis.get("fallback_reason") or "no reason recorded")),
              "- Model: {} (tier {})".format(hypothesis.get("model") or "none", hypothesis.get("tier") or "-"),
              "- Ranking: {}".format(", ".join(ranking) or "-"),
              "- Verdict (top-ranked entity against the surviving entities): **{}**".format(verdict_text),
              ""]
    if summary.get("hypothesis_verdict") not in (None, verdict):
        lines += ["Warning: the Job recorded verdict `{}`, which differs from this recomputation.".format(
            summary["hypothesis_verdict"]), ""]
    lines += [(hypothesis.get("text") or "No hypothesis text (the fixed order was used)."), ""]
    candidates = reduction.get("candidates") or []
    lines += ["## Candidates", ""]
    lines += _table(
        ["#", "phase", "role", "selection", "outcomes", "decision", "gate met", "skipped", "late"],
        [[c["index"], c["phase"], c["role"] + ("" if c.get("reference") is None else " " + str(c["reference"])),
          _selection_text(c.get("selection")) if c["role"] == "hybrid" else "-",
          _letters(c["outcomes"]), c["decision"], c["gate_met"], c["skipped"],
          _letters(c.get("late_outcomes") or [])] for c in candidates])
    probe = reduction.get("ranked_probe") or {}
    lines += ["", "Invalid scenes (never counted as failures): {}".format(
        ", ".join(str(i) for i in reduction.get("invalid_scenes") or []) or "none")]
    if probe.get("modelled_ddmin_candidates") is not None:
        lines += ["", "The ranked probe found its culprit after {} singleton candidate(s); plain ddmin is modelled "
                  "to need {} (a modelled count, not a measured saving).".format(
                      probe.get("singletons_tested"), probe.get("modelled_ddmin_candidates"))]
    lines += ["", "## Effort", "",
              "- Candidates tested: {}; attempts run: {} (gate attempts {}, hybrid attempts {}); attempts "
              "skipped by early decisions: {}".format(
                  reduction.get("candidates_tested"), reduction.get("attempts_run"),
                  reduction.get("attempts_run_gates"), reduction.get("attempts_run_hybrid"),
                  reduction.get("attempts_skipped")),
              "- Job seconds: {}; server start-up seconds: {}".format(
                  summary.get("total_seconds"), summary.get("startup_seconds"))]
    if hourly_rate is not None and isinstance(summary.get("total_seconds"), (int, float)):
        lines.append("- Estimated compute cost at the given rate (an estimate, not billing): ${:.2f}".format(
            summary["total_seconds"] / 3600.0 * hourly_rate))
    videos = summary.get("videos") or {}
    lines += ["", "## Videos", ""]
    lines += _table(["role", "case id", "outcome", "video (relative to the Job's scenario folder)"],
                    [[role, v.get("case_id"), v.get("outcome"), v.get("video")]
                     for role, v in sorted(videos.items())]) if videos else ["(none)"]
    lines.append("")
    return lines


def build_report(summary: Mapping[str, Any], screen: Optional[Mapping[str, Any]] = None,
                 hourly_rate: Optional[float] = None) -> str:
    if summary["mode"] == "scenario-screen":
        title = "# Scenario screen: {}".format(summary.get("suite"))
        lines = [title, "", "Stop reason: `{}`; complete: {}; Job seconds: {}.".format(
            summary.get("stop_reason"), summary.get("complete"), summary.get("total_seconds")), ""]
        lines += screen_section(summary)
        return "\n".join(lines) + "\n"
    if summary["mode"] != "scenario-reduce":
        raise ReportError("only screen and reduce summaries are reported")
    plan = summary.get("plan")
    if not isinstance(plan, dict):
        raise ReportError("the summary has no plan")
    lines = ["# Scenario reduction: {}".format(plan["instruction"]), "",
             "Suite `{}`, task {}. Reference runs decide everything below; the model only proposes an order "
             "and a hypothesis.".format(plan["suite"], plan["task_id"]), ""]
    if screen is not None:
        lines += screen_section(screen)
    lines += reduction_section(summary, hourly_rate)
    return "\n".join(lines) + "\n"


def write_text(path: Path, text: str, force: bool) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w" if force else "x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError:
        raise ReportError("an output file exists (use --force)") from None
    except OSError:
        raise ReportError("an output file could not be written") from None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("summary", type=Path)
    parser.add_argument("--screen", type=Path, help="the screen summary the reduction was planned from")
    parser.add_argument("--out", type=Path, help="report path (default: beside the summary)")
    parser.add_argument("--case-out", type=Path, help="case record path (reduce summaries)")
    parser.add_argument("--candidate-out", type=Path, help="write the replay candidate file here")
    parser.add_argument("--hourly-rate", type=float, default=None)
    parser.add_argument("--force", action="store_true")
    try:
        args = parser.parse_args(argv)
        summary = load_summary(args.summary)
        screen = load_summary(args.screen) if args.screen else None
        if screen is not None and screen["mode"] != "scenario-screen":
            raise ReportError("--screen needs a scenario-screen summary")
        out = args.out or args.summary.with_name(
            "scenario_screen_report.md" if summary["mode"] == "scenario-screen" else "scenario_reduction_report.md")
        write_text(out, build_report(summary, screen, args.hourly_rate), args.force)
        printed = {"report": out.name}
        if summary["mode"] == "scenario-reduce":
            try:
                case = se.build_case(summary)
            except ValueError:
                raise ReportError("the summary cannot be turned into a case") from None
            case_out = args.case_out or args.summary.with_name(
                "scenario_case_{}.json".format(case["case_id"][:12]))
            write_text(case_out, json.dumps(case, indent=1, sort_keys=True, allow_nan=False) + "\n", args.force)
            printed.update(case=case_out.name, case_id=case["case_id"])
            if args.candidate_out is not None:
                candidate = case["replay"]["candidate"]
                if candidate is None:
                    raise ReportError("there is no minimal candidate to write")
                try:
                    write_scenario_candidate(args.candidate_out, validate_scenario_candidate(candidate))
                except (ScenarioImportError, OSError):
                    raise ReportError("the candidate could not be written") from None
                printed["candidate"] = args.candidate_out.name
        print(json.dumps(printed, sort_keys=True))
        return 0
    except ReportError as error:
        print(json.dumps({"error": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
