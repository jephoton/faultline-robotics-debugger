"""Write the Markdown report and the case record for a scenario Job summary.

    report_scenario_reduction.py SUMMARY.json [--screen SCREEN_SUMMARY.json] [--plan PLAN.json]
        [--out REPORT.md] [--case-out CASE.json] [--candidate-out CANDIDATE.json]
        [--hourly-rate USD]

``SUMMARY.json`` is the ``scenario_summary.json`` of a ``scenario-reduce`` Job (a report
and a case are written) or of a ``scenario-screen`` Job (the screen report only). For a
reduction, ``--screen`` adds the screen table of the screen it was planned from.

The report states what the simulator showed (outcomes of reruns), the minimal cause in
one sentence, the Nemotron hypothesis, its source or fallback, the mechanical verdict
(``confirmed``, ``partly`` or ``refuted``, for a fully reduced run) and a "Hypothesis vs
result" section: whether the model's top-ranked entities were necessary and sufficient,
read from the reruns in the summary (recomputed, so budget-exhausted entity-minimal runs
get one too). The case record holds the replay
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
from robot_debug.scenario_hypothesis import compact_differences
from robot_debug.scenario_import import ScenarioImportError, validate_scenario_candidate, write_scenario_candidate
from robot_debug.viewer.library import _one_decimal, minimal_cause

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


def merge_plan(summary: Dict[str, Any], plan_path: Path) -> Dict[str, Any]:
    """Fill what the summary's own plan lacks (order, order source, hypothesis) from ``plan.json``.

    The task identity must match; a field the summary already has is never overridden.
    """

    try:
        plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ReportError("the plan is unreadable") from None
    own = summary.get("plan")
    if not isinstance(plan, dict) or not isinstance(own, dict):
        raise ReportError("the plan or the summary has no plan")
    for key in ("suite", "task_id", "instruction"):
        if key in plan and key in own and plan[key] != own[key]:
            raise ReportError("the plan does not match the summary")
    for key in ("suite", "task_id", "instruction", "order", "order_source", "hypothesis"):
        if own.get(key) in (None, [], {}) and key in plan:
            own[key] = plan[key]
    return summary


def _letters(outcomes: Sequence[Any]) -> str:
    return " ".join(LETTERS.get(item, "?") for item in outcomes) if outcomes else "-"


def _cell(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def _table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> List[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(_cell(item) for item in row) + " |" for row in rows]
    return lines


def _checkpoint_text(checkpoint: Any) -> str:
    if not isinstance(checkpoint, dict) or not checkpoint.get("id"):
        return "not recorded"
    revision = checkpoint.get("revision")
    return "`{}` at revision `{}`{}".format(
        checkpoint["id"], revision or "unknown", "" if checkpoint.get("pinned") else " (not pinned or not recorded)")


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


def _yes_no(value: Any) -> str:
    return "yes" if value is True else "no" if value is False else "not tested"


_DECISION_TEXT = {"reproduces": "reproduced", "does_not_reproduce": "did not reproduce", "passes": "passes",
                  "invalid_scene": "was an invalid scene"}


def _run_text(candidate: Mapping[str, Any]) -> str:
    return "{}, {}".format(_letters(candidate.get("outcomes") or []),
                           _DECISION_TEXT.get(candidate.get("decision"), str(candidate.get("decision"))))


def _evidence_sentences(entity: Mapping[str, Any], kind: str, by_index: Mapping[Any, Mapping[str, Any]]) -> str:
    """The measured cell as one line: the answer, then the reruns it was read from."""

    name = entity["entity"]
    answer = entity[kind]
    indices = entity["basis"][kind]
    pieces = ["{}, {}: {}.".format(name, kind, _yes_no(answer))]
    if kind == "necessary" and entity.get("necessary_basis") == "not_in_final":
        pieces.append("Not in the final selection" + ("; candidate #{} without it still reproduced: {}.".format(
            indices[0], _letters((by_index.get(indices[0]) or {}).get("outcomes") or [])) if indices else "."))
        return " ".join(pieces)
    if not indices:
        pieces.append("No candidate changed only {}.".format(name) if kind == "sufficient" else
                      "No candidate matched the final selection without {}.".format(name))
        return " ".join(pieces)
    for index in indices:
        candidate = by_index.get(index) or {}
        head = "Candidate #{} ({})".format(index, candidate.get("phase", "?"))
        if kind == "sufficient":
            pieces.append("{} changed only {}: {}.".format(
                head, _selection_text(candidate.get("selection")), _run_text(candidate)))
        elif entity.get("necessary_basis") == "reference":
            pieces.append("{} is the passing reference with nothing changed: {}.".format(head, _run_text(candidate)))
        else:
            suffix = (" (same entities and parts as the final selection without {}, other sizes)".format(name)
                      if entity.get("necessary_basis") == "entity_set" else "")
            pieces.append("{} kept {}: {}{}.".format(
                head, _selection_text(candidate.get("selection")), _run_text(candidate), suffix))
    return " ".join(pieces)


def hypothesis_vs_result_section(summary: Mapping[str, Any]) -> List[str]:
    """What the model's ranking got right and missed, generated only from the reruns.

    The measurement is recomputed from the stored candidates, so a run whose summary has
    no stored verdict (a budget-exhausted, entity-minimal reduction) still gets one.
    """

    plan, reduction = summary["plan"], summary.get("reduction") or {}
    hypothesis = plan.get("hypothesis") or {}
    lines = ["## Hypothesis vs result", ""]
    if plan.get("order_source") != "model":
        return lines + ["Comparison not applicable: the fixed order is a search order, not a model hypothesis.", ""]
    measurement = se.measurement_for(plan, reduction)
    ranking = hypothesis.get("ranking") or plan.get("order") or []
    lines += ["- Hypothesis text: {}".format(hypothesis.get("text") or "none"),
              "- Ranking: {}".format(", ".join(ranking) or "-")]
    if measurement is None:
        return lines + ["- Comparison not available: the reduction is not entity-minimal (stop reason `{}`) or has "
                        "no final selection, so no entity can be called necessary or sufficient.".format(
                            reduction.get("stop_reason")), ""]
    if measurement["result_scope"] == "reduced":
        scope = "reduced (every kept part shrunk to its resolution)"
    else:
        scope = "entity-minimal, sizes only partly shrunk (stop reason `{}`)".format(reduction.get("stop_reason"))
    stored = summary.get("hypothesis_measurement")
    top = measurement["top"]
    lines += ["- Scope: {}".format(scope),
              "- Measured label for the top-ranked entity ({}): **{}**".format(top, measurement["verdict"])]
    if stored is None:
        lines.append("- This was recomputed from the candidates in this summary; no new runs were made.")
    elif stored.get("verdict") != measurement["verdict"]:
        lines.append("Warning: the Job recorded measured label `{}`, which differs from this recomputation.".format(
            stored.get("verdict")))
    by_index = {c["index"]: c for c in reduction.get("candidates") or []}
    entities = measurement["entities"]
    lines += [""] + _table(
        ["rank", "entity", "in final selection", "necessary", "sufficient", "label"],
        [[e["rank"], e["entity"], _yes_no(e["in_final"]), _yes_no(e["necessary"]), _yes_no(e["sufficient"]),
          e["label"]] for e in entities])
    lines += ["", "Necessary: the final selection without that entity did not reproduce the failure. Sufficient: "
              "changing only that entity reproduced it. Both are read from reruns already in the candidate "
              "list, relative to this final selection.", "", "### Evidence", ""]
    for entity in entities:
        lines.append("- " + _evidence_sentences(entity, "sufficient", by_index))
        lines.append("- " + _evidence_sentences(entity, "necessary", by_index))
    lines += ["", "### What the ranking got right and missed", ""]
    leader = entities[0]
    if leader["necessary"] is True:
        lines.append("- Right: the top-ranked entity ({}) is needed. The final selection without it did not "
                     "reproduce the failure.".format(top))
    elif leader["necessary"] is False and not leader["in_final"]:
        lines.append("- Missed: the top-ranked entity ({}) is not part of the minimal cause. The failure still "
                     "reproduced without it.".format(top))
    elif leader["necessary"] is False:
        lines.append("- Missed: the top-ranked entity ({}) is not needed: the final selection without it still "
                     "reproduced the failure.".format(top))
    else:
        lines.append("- Untested: whether the final selection without {} still reproduces the failure.".format(top))
    if leader["sufficient"] is True:
        lines.append("- Right: {} alone reproduces the failure.".format(top))
    elif leader["sufficient"] is False:
        lines.append("- Missed: {} alone does not reproduce the failure{}".format(
            top, ", so it is necessary but not sufficient." if leader["necessary"] is True else "."))
    else:
        lines.append("- Untested: whether {} alone reproduces the failure.".format(top))
    survivors = measurement["survivors"]
    lines.append("- {} of the top {} ranked entities are in the final selection ({} entit{} survive).".format(
        measurement["ranked_survivors_overlap"], measurement["top_k"], len(survivors),
        "y" if len(survivors) == 1 else "ies"))
    extra = [name for name in survivors if name not in [e["entity"] for e in entities]]
    if extra:
        lines.append("- Also in the final selection but not in the top {}: {}.".format(
            measurement["top_k"], ", ".join(extra)))
    lines += ["", "The hypothesis text is free prose; this section compares only the ranking with the "
              "measurements and does not interpret the prose.", ""]
    return lines


def _failing_text(plan: Mapping[str, Any]) -> str:
    """The failing start: its benchmark index, or the imported file it came from."""

    if plan.get("failing_start") is not None:
        return str(plan["failing_start"])
    imported = plan.get("failing_import") or {}
    source = plan.get("failing_source") or {}
    where = ""
    if source.get("kind") == "benchmark":
        where = ", from benchmark start {}".format(source.get("init_state_index"))
    return "imported (file sha256 {}, state sha256 {}{})".format(
        str(imported.get("file_sha256"))[:12], str(imported.get("state_sha256"))[:12], where)


def _share_text(fraction: float) -> str:
    """A share as the page shows it: one decimal at most, half-up, no trailing ``.0`` (0.875 -> ``87.5%``)."""

    text = _one_decimal(float(fraction) * 100.0)
    return "{}%".format(text[:-2] if text.endswith(".0") else text)


_STOPPED_AT = {
    "budget_exhausted": "Stopped at the candidate budget",
    "deadline_exhausted": "Stopped at the time limit",
    "failing_not_reproducible": "Stopped because the failing start did not fail reliably",
    "reference_not_passing": "Stopped because no reference passed 5 of 5 attempts",
    "infrastructure_error": "Stopped by an infrastructure error",
}


def _summary_stop_text(reduction: Mapping[str, Any], has_cause: bool) -> str:
    """The stop status in plain words, for example ``Stopped at the candidate budget: entity-minimal, sizes not
    fully shrunk.`` The same facts as the case page, so the report and the page never disagree."""

    reason = reduction.get("stop_reason")
    if reduction.get("reduced"):
        steps = reduction.get("bisection_steps")
        return "Fully reduced: every kept shift was shrunk to within 1/{} of its original size.".format(
            2 ** steps) if steps else "Fully reduced."
    stopped = _STOPPED_AT.get(reason, "Stopped ({})".format(reason))
    if not has_cause:
        return "{}: no minimal cause was established.".format(stopped)
    if reduction.get("entity_minimal"):
        return "{}: entity-minimal (each kept entity is needed), sizes not fully shrunk.".format(stopped)
    return "{}: not yet entity-minimal; this is the smallest cause found so far.".format(stopped)


def summary_section(summary: Mapping[str, Any]) -> List[str]:
    """A few bullets that answer the report's main questions before the detail: does it reproduce, from which
    start, against which reference, which shifts are enough (with size and share), and why it stopped."""

    plan, reduction = summary["plan"], summary.get("reduction") or {}
    selection = reduction.get("final_selection")
    kept = minimal_cause({
        "differences": compact_differences(summary.get("differences") or []),
        "minimal": {"selection": selection or {}}}) if selection else []
    if kept:
        verdict = ("Reproduces. Applying the kept shifts to the passing reference makes the policy fail at "
                   "least {} of {} attempts.".format(reduction.get("required_failures", 4), reduction.get("attempts", 5)))
    else:
        verdict = "Not reproduced. No smaller cause than the whole arrangement was established."
    if plan.get("failing_start") is not None:
        failing = "benchmark start {}".format(plan["failing_start"])
    else:
        imported = plan.get("failing_import") or {}
        source = plan.get("failing_source") or {}
        failing = "imported file {}".format(str(imported.get("file_sha256"))[:12])
        if source.get("kind") == "benchmark" and source.get("init_state_index") is not None:
            failing += " (from benchmark start {})".format(source["init_state_index"])
    reference = reduction.get("reference")
    lines = ["## Summary", "",
             "- Verdict: {}".format(verdict),
             "- Failing start: {}.".format(failing),
             "- Reference: {}.".format("none was established" if reference is None else
                                       "benchmark start {}, the nearest start that passed".format(reference))]
    for row in kept:
        lines.append("- Kept shift: {} {}, {} ({} of the full difference).".format(
            row["entity"], row["part"], row["magnitude"], _share_text(row["fraction"])))
    lines += ["- Status: {}".format(_summary_stop_text(reduction, bool(kept))), ""]
    return lines


def _points(fraction: float) -> str:
    """A gap between two shares in percentage points, with its 1/N form when it is one: ``6.25 points (1/16)``."""

    points = "{:g} point{}".format(round(fraction * 100.0, 2), "" if abs(fraction * 100.0 - 1.0) < 1e-9 else "s")
    count = round(1.0 / fraction) if fraction > 0 else 0
    return "{} (1/{})".format(points, count) if count >= 2 and abs(count * fraction - 1.0) < 1e-6 else points


def size_rows(summary: Mapping[str, Any], reductions: Optional[Sequence[Mapping[str, Any]]] = None) -> List[List[str]]:
    """One row per kept part of the final selection, from the sizes tried in every reduction Job.

    ``reductions`` are all the run's reduction summaries (the first reduce and its continuations); the
    last Job's ``parts`` lists only the size searches that finished, so a part cut off by the budget (the
    ``l10-start14`` milk, shrunk to 87.5% in the continuation) would be missing. A kept part nothing was
    tried below is shown as "not shrunk"."""

    reduction = summary.get("reduction") or {}
    selection = reduction.get("final_selection") or {}
    history = {(h["entity"], h["component"]): h["tested"]
               for h in se.shrink_history(reductions if reductions else [summary])}
    parts = {(p.get("entity"), p.get("component")): p for p in reduction.get("parts") or [] if isinstance(p, Mapping)}
    rows: List[List[str]] = []
    for entity in sorted(selection):
        for component in sorted(selection[entity]):
            kept = float(selection[entity][component])
            tested, part = history.get((entity, component), []), parts.get((entity, component))
            passed = [t["t"] for t in tested if t["decision"] == "does_not_reproduce" and t["t"] < kept]
            if not passed and part is not None and part.get("lower_tested") and part.get("lower") is not None:
                passed = [float(part["lower"])]
            invalid = sorted({t["t"] for t in tested if t["decision"] == "invalid_scene"}
                             | {float(v) for v in (part or {}).get("invalid_points") or []})
            invalid_text = ", ".join(_share_text(v) for v in invalid) or "-"
            if not tested and part is None:
                rows.append([entity, component, _share_text(kept), "not shrunk", "-", "-"])
            elif passed:
                rows.append([entity, component, _share_text(kept), _share_text(max(passed)),
                             _points(kept - max(passed)), invalid_text])
            else:
                rows.append([entity, component, _share_text(kept), "none tried below", "-", invalid_text])
    return rows


def reduction_section(summary: Mapping[str, Any], hourly_rate: Optional[float],
                      reductions: Optional[Sequence[Mapping[str, Any]]] = None) -> List[str]:
    plan, reduction = summary["plan"], summary.get("reduction") or {}
    selection = reduction.get("final_selection")
    reference = reduction.get("reference")
    sentence = se.describe_minimal_cause(
        selection or {}, summary.get("differences") or [], reference=reference,
        bisection_steps=reduction.get("bisection_steps"), reduced=bool(reduction.get("reduced")),
        required_failures=reduction.get("required_failures", 4), attempts=reduction.get("attempts", 5),
        parts=reduction.get("parts"))
    lines = ["## Result", "",
             "- Stop reason: `{}`".format(reduction.get("stop_reason")),
             "- Failing start: {}; reference (nearest passing start): {}; candidate references tried: {}".format(
                 _failing_text(plan), reference,
                 ", ".join("{} ({})".format(r["id"], r["decision"]) for r in reduction.get("references_tried") or []) or "-"),
             "- Entity-minimal: {}".format("yes" if reduction.get("entity_minimal") else "no"),
             "- Checkpoint: {}".format(_checkpoint_text(summary.get("checkpoint"))), "",
             "### Minimal cause", ""]
    lines += [sentence if selection else "No minimal cause was established (stop reason `{}`).".format(
        reduction.get("stop_reason")), ""]
    if reduction.get("note"):
        lines += ["Note: {}".format(reduction["note"]), ""]
    lines += ["Final selection: {}. This is a local minimum found by reruns, not proof of the globally "
              "smallest cause.".format(_selection_text(selection)), ""]
    sizes = size_rows(summary, reductions)
    if sizes:
        lines += _table(["entity", "part", "kept size", "largest size that passed", "precision", "invalid sizes"],
                        sizes) + [""]
        lines += ["Sizes are shares of the full difference between the two starts. Kept size: verified to make the "
                  "policy fail (at least 4 of 5 attempts). Largest size that passed: the largest smaller size tried "
                  "that did not fail that often, over every reduction Job. Precision: the gap between the two. "
                  "Invalid sizes were interpenetrating scenes and say nothing about the policy.", ""]
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
    lines += hypothesis_vs_result_section(summary)
    candidates = reduction.get("candidates") or []
    lines += ["## Candidates", "",
              "Every rerun, in order. Phases: `gate` (the failing start must fail 4 of 5, the reference pass 5 of 5), "
              "`probe` (one difference alone), `ddmin` (smaller and smaller groups of differences), `shrink` (smaller "
              "shares of each kept difference). A selection's number is its share: `robot (joints 0.75)` applies 75% "
              "of the arm's offset to the reference. Outcomes: S success, F policy failure, I invalid scene. "
              "`skipped`: attempts not run because the answer was already certain; `late`: attempts already running "
              "when it was decided, shown but not counted. See the Reference page (docs/reference.md).", ""]
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
                 hourly_rate: Optional[float] = None,
                 reductions: Optional[Sequence[Mapping[str, Any]]] = None) -> str:
    if summary["mode"] == "scenario-screen":
        title = "# Scenario screen: {}".format(summary.get("suite"))
        lines = [title, "", "Stop reason: `{}`; complete: {}; Job seconds: {}. Checkpoint: {}.".format(
            summary.get("stop_reason"), summary.get("complete"), summary.get("total_seconds"),
            _checkpoint_text(summary.get("checkpoint"))), ""]
        lines += screen_section(summary)
        return "\n".join(lines) + "\n"
    if summary["mode"] != "scenario-reduce":
        raise ReportError("only screen and reduce summaries are reported")
    plan = summary.get("plan")
    if not isinstance(plan, dict):
        raise ReportError("the summary has no plan")
    lines = ["# Scenario reduction: {}".format(plan["instruction"]), ""]
    lines += summary_section(summary)
    lines += ["Suite `{}`, task {}. Reference runs decide everything below; the model only proposes an order "
              "and a hypothesis.".format(plan["suite"], plan["task_id"]), ""]
    if screen is not None:
        lines += screen_section(screen)
    lines += reduction_section(summary, hourly_rate, reductions)
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
    parser.add_argument("--plan", type=Path, help="plan.json to fill an order or hypothesis the summary lacks")
    parser.add_argument("--out", type=Path, help="report path (default: beside the summary)")
    parser.add_argument("--case-out", type=Path, help="case record path (reduce summaries)")
    parser.add_argument("--candidate-out", type=Path, help="write the replay candidate file here")
    parser.add_argument("--hourly-rate", type=float, default=None)
    parser.add_argument("--force", action="store_true")
    try:
        args = parser.parse_args(argv)
        summary = load_summary(args.summary)
        if args.plan is not None:
            summary = merge_plan(summary, args.plan)
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
