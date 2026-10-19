"""Write the Markdown report and the case record for a paraphrase diagnosis (ADR 0032).

    report_paraphrase.py SCREEN_SUMMARY.json [--reduction REDUCE_SUMMARY.json]
        [--out REPORT.md] [--case-out CASE.json] [--hourly-rate USD]

``SCREEN_SUMMARY.json`` is the ``language_summary.json`` of a ``paraphrase-screen`` Job and
``REDUCE_SUMMARY.json`` the one of the ``paraphrase-reduce`` Job that followed it. Without a
reduction the report is the screen table alone (nothing reproduced, or the control did not pass).

The report states what the simulator showed (outcomes of reruns), the original wording against the
minimal failing wording with the decisive edits marked, every screened instruction and every
reduction candidate with its outcomes and decision, and the limits of the claim: one benchmark
start, one checkpoint, one rewording family, a local minimum found by reruns and no causal proof.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from robot_debug import language_experiment as le
from robot_debug import paraphrase as pp

LETTERS = {"success": "S", "policy_failure": "F", "invalid_scene": "I"}


class ReportError(ValueError):
    """A fixed, non-secret problem with the input."""


def load_summary(path: Path, mode: str) -> Dict[str, Any]:
    try:
        summary = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ReportError("the summary is unreadable") from None
    if not isinstance(summary, dict) or summary.get("schema_version") != 1 or summary.get("mode") != mode:
        raise ReportError("not a {} summary".format(mode))
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


def _tidy(text: str) -> str:
    return re.sub(r" ([,.;:!?)\]])", r"\1", re.sub(r"([(\[]) ", r"\1", text))


def mark_edits(original: str, edits: Sequence[Mapping[str, Any]]) -> str:
    """The original wording with each edit shown as ``~~old~~ **new**`` (insertions as ``**new**``)."""

    tokens = pp.tokenize(original)
    pieces = []  # type: List[str]
    index = 0
    for edit in sorted(edits, key=lambda item: item["start"]):
        pieces.extend(tokens[index:edit["start"]])
        if edit["original"]:
            pieces.append("~~" + " ".join(edit["original"]) + "~~")
        if edit["replacement"]:
            pieces.append("**" + " ".join(edit["replacement"]) + "**")
        index = edit["end"]
    pieces.extend(tokens[index:])
    return _tidy(" ".join(pieces))


def _seconds(value: Any) -> str:
    return "-" if not isinstance(value, (int, float)) else "{:.0f} s".format(value)


def _cost(seconds: Any, rate: Optional[float]) -> str:
    if not isinstance(seconds, (int, float)) or rate is None:
        return ""
    return " (about US${:.2f} at US${:.4f}/h)".format(seconds / 3600.0 * rate, rate)


def _faithful(screen: Mapping[str, Any]) -> bool:
    """Whether some reproducing paraphrase kept every object and target word of the original."""

    original = screen.get("original")
    for row in screen.get("instructions") or []:
        if row.get("kind") == "paraphrase" and row.get("label") in (screen.get("reproducing") or []):
            if not isinstance(original, str) or pp.meaning_check(original, str(row.get("text"))) == pp.MEANING_KEPT:
                return True
    return False


def screen_section(screen: Mapping[str, Any]) -> List[str]:
    lines = ["## Screen", "",
             "Outcomes per instruction: S success, F policy failure. The original wording is the control "
             "(two attempts). Each paraphrase had one attempt; a paraphrase that failed was confirmed "
             "(it reproduces when at least 4 of 5 attempts fail).", ""]
    rows = []
    original = screen.get("original")
    dropped = []  # type: List[str]
    for row in screen.get("instructions") or []:
        meaning = "-"
        if row.get("kind") == "paraphrase" and isinstance(original, str) and isinstance(row.get("text"), str):
            meaning = pp.meaning_check(original, row["text"])
            if meaning == pp.MEANING_DROPPED:
                dropped.append(str(row.get("label")))
        rows.append([row.get("label"), row.get("kind"), _letters(row.get("outcomes") or []),
                     row.get("decision") or ("control" if row.get("kind") == "original" else "passed"),
                     row.get("edit_count") if row.get("edit_count") is not None else "-", meaning,
                     row.get("text")])
    lines += _table(["label", "kind", "outcomes", "decision", "word edits", "meaning check", "instruction"], rows)
    control = screen.get("control") or {}
    reproducing = screen.get("reproducing") or []
    lines += ["", "Control (original wording): {} ({}).".format(
        _letters(control.get("outcomes") or []), "passed" if control.get("passed") else "did NOT pass both attempts"),
        "Paraphrases that failed at least 4 of 5 attempts: {}.".format(", ".join(reproducing) or "none"),
        "Attempts skipped by early decisions: {}.".format((screen.get("confirm") or {}).get("skipped_attempts", 0)), ""]
    lines += ["Meaning check: `kept` means every object or target word of the original (a word of four or more "
              "letters that is not an action verb, preposition or article) is still in the paraphrase; "
              "`object_or_target_dropped` means one is missing. Flagged paraphrases are screened but never chosen "
              "for reduction, because a failure there may come from a changed task, not from the wording.",
              "Flagged in this screen: {}.".format(", ".join(dropped) or "none")]
    flagged_failures = [label for label in reproducing if label in dropped]
    if flagged_failures:
        lines.append("Failed 4 of 5 but flagged, so not reduced: {}.".format(", ".join(flagged_failures)))
    lines.append("")
    return lines


def reduction_section(summary: Mapping[str, Any], rate: Optional[float]) -> List[str]:
    reduction = summary.get("reduction") or {}
    original, paraphrase = summary.get("original", ""), summary.get("paraphrase", "")
    minimal = summary.get("minimal")
    lines = ["## Reduction", "",
             "Delta debugging over the {} word edits between the original wording and the failing "
             "paraphrase. A candidate is the original wording with some of the edits applied; it "
             "reproduces when at least {} of {} attempts fail.".format(
                 len(summary.get("edits") or []), reduction.get("required_failures", 4), reduction.get("attempts", 5)), "",
             "- Original wording: `{}`".format(original), "- Full paraphrase: `{}`".format(paraphrase)]
    gates = reduction.get("gates") or {}
    lines += ["- Gates: the full paraphrase {} ; the original wording {}.".format(
        gates.get("paraphrase") or "not run", gates.get("original") or "not run"), ""]
    if isinstance(minimal, Mapping):
        meaning = pp.meaning_check(original, minimal.get("text", "")) if isinstance(original, str) else "-"
        lines += ["### Minimal failing wording", "",
                  "- Original: `{}`".format(original),
                  "- Minimal: `{}`".format(minimal.get("text")),
                  "- Marked: {}".format(mark_edits(original, minimal.get("edits") or [])),
                  "- Meaning check of the minimal wording: `{}`".format(meaning),
                  "- Edits kept ({} of {}): {}".format(len(minimal.get("edits") or []), len(summary.get("edits") or []),
                                                       "; ".join(minimal.get("labels") or []) or "none"),
                  "- {}".format("1-minimal: removing any one remaining edit makes the failure stop reproducing "
                                "(or was not tested)." if minimal.get("edit_minimal")
                                else "The reduction stopped early ({}); this is the smallest wording change "
                                     "verified so far.".format(reduction.get("stop_reason"))), ""]
    else:
        lines += ["No failing wording was verified (stop reason: {}).".format(reduction.get("stop_reason")), ""]
    rows = []
    for candidate in reduction.get("candidates") or []:
        selection = candidate.get("selection")
        rows.append([candidate.get("index"), candidate.get("phase"), candidate.get("role"),
                     "-" if selection is None else ", ".join(str(i) for i in selection) or "none",
                     _letters(candidate.get("outcomes") or []), candidate.get("decision") or "-",
                     candidate.get("text")])
    lines += ["### Every candidate", ""]
    lines += _table(["#", "phase", "role", "edits applied", "outcomes", "decision", "instruction"], rows)
    lines += ["", "Candidates tested: {}; attempts run: {}; skipped by early decisions: {}.".format(
        reduction.get("candidates_tested"), reduction.get("attempts_run"), reduction.get("attempts_skipped")), ""]
    videos = summary.get("videos") or {}
    if videos:
        lines += ["### Videos", ""]
        names = {"original": "Full paraphrase (fails)", "reference": "Original wording (passes)",
                 "minimal": "Minimal wording (fails)"}
        for role in ("reference", "original", "minimal"):
            entry = videos.get(role)
            if isinstance(entry, Mapping):
                lines.append("- {}: `{}` ({})".format(names[role], entry.get("video"), entry.get("outcome")))
        lines.append("")
    return lines


def summary_section(screen: Mapping[str, Any], reduction: Optional[Mapping[str, Any]] = None) -> List[str]:
    """Bullets before the detail: the control, how many rewordings the meaning check kept and dropped, and
    whether (and how small) a failing wording was found."""

    original = screen.get("original")
    control = screen.get("control") or {}
    passed = bool(control.get("passed"))
    lines = ["## Summary", "",
             "- Control: the original wording {} ({}).".format(
                 "passed" if passed else "did not pass both attempts, so a failure cannot be attributed to the "
                 "wording", _letters(control.get("outcomes") or []))]
    rewordings = [row for row in screen.get("instructions") or [] if row.get("kind") == "paraphrase"]
    dropped = [row for row in rewordings if isinstance(original, str) and isinstance(row.get("text"), str)
               and pp.meaning_check(original, row["text"]) == pp.MEANING_DROPPED]
    lines.append("- Rewordings: {} screened; {} kept by the meaning check, {} dropped (an object or target word "
                 "of the instruction was missing).".format(len(rewordings), len(rewordings) - len(dropped),
                                                           len(dropped)))
    reproducing = screen.get("reproducing") or []
    if reproducing:
        lines.append("- Failures: {} rewording{} failed at least 4 of 5 attempts ({}).".format(
            len(reproducing), "" if len(reproducing) == 1 else "s", ", ".join(str(l) for l in reproducing)))
    else:
        lines.append("- Failures: none. No rewording failed at least 4 of 5 attempts in this screen.")
    minimal = (reduction or {}).get("minimal")
    if isinstance(minimal, Mapping):
        reduced = bool(((reduction or {}).get("reduction") or {}).get("reduced"))
        edits = len(minimal.get("labels") or [])
        lines.append("- Smallest failing wording: {} word edit{} from the original; {}.".format(
            edits, "" if edits == 1 else "s",
            "each remaining edit is needed" if minimal.get("edit_minimal") else
            "the reduction stopped early, so this is the smallest change verified so far"))
        lines.append("- Minimal wording: \"{}\"{}".format(minimal.get("text"), "" if reduced else " (not fully reduced)"))
    elif reduction is not None:
        lines.append("- Smallest failing wording: none was verified by the reduction.")
    elif reproducing:
        lines.append("- Smallest failing wording: not reduced.")
    return lines + [""]


def build_report(screen: Mapping[str, Any], reduction: Optional[Mapping[str, Any]] = None,
                 hourly_usd: Optional[float] = None) -> str:
    if not isinstance(screen, Mapping) or screen.get("mode") != "paraphrase-screen":
        raise ReportError("a paraphrase-screen summary is required")
    if reduction is not None and (not isinstance(reduction, Mapping) or reduction.get("mode") != "paraphrase-reduce"):
        raise ReportError("not a paraphrase-reduce summary")
    base = reduction if reduction is not None else screen
    original = screen.get("original", "")
    lines = ["# Faultline paraphrase report", ""]
    lines += summary_section(screen, reduction)
    minimal = (reduction or {}).get("minimal")
    if reduction is not None and isinstance(minimal, Mapping):
        reduced = bool((reduction.get("reduction") or {}).get("reduced"))
        lines += [le.describe_minimal_wording(
            original, minimal.get("text", ""), minimal.get("labels") or [], reduced=reduced,
            required_failures=(reduction.get("reduction") or {}).get("required_failures", 4),
            attempts=(reduction.get("reduction") or {}).get("attempts", 5)), ""]
    elif screen.get("reproducing") and reduction is None and not _faithful(screen):
        lines += ["Paraphrases of \"{}\" made the policy fail at least 4 of 5 attempts, but each of them dropped "
                  "an object or target word of the instruction, so none was reduced: the failure may come from a "
                  "changed task rather than from the wording alone.".format(original), ""]
    elif not screen.get("reproducing"):
        lines += ["No paraphrase of \"{}\" made the policy fail at least 4 of 5 attempts in this screen: the "
                  "policy was robust to these {} rewordings at this start (a valid result, not a bug).".format(
                      original, len(screen.get("instructions") or []) - 1), ""]
    else:
        lines += ["A paraphrase reproduced in the screen, but no failing wording was verified by the "
                  "reduction.", ""]
    lines += ["## Setup", "",
              "- Suite: `{}`, task {}, benchmark start {}".format(
                  screen.get("suite"), screen.get("task_id"), screen.get("init_state_index")),
              "- Checkpoint: {}".format(_checkpoint_text(base.get("checkpoint"))),
              "- Screen Job time: {}{}".format(_seconds(screen.get("total_seconds")),
                                              _cost(screen.get("total_seconds"), hourly_usd))]
    if reduction is not None:
        lines.append("- Reduction Job time: {}{}".format(_seconds(reduction.get("total_seconds")),
                                                          _cost(reduction.get("total_seconds"), hourly_usd)))
    lines.append("")
    lines += screen_section(screen)
    if reduction is not None:
        lines += reduction_section(reduction, hourly_usd)
    lines += ["## What this does and does not show", ""]
    verified_minimal = isinstance(minimal, Mapping) and minimal.get("verified") is True
    if reduction is not None and verified_minimal:
        lines.append("- It shows that the reduced wording reproduced a policy failure at this benchmark start "
                     "and checkpoint in a simulator.")
    elif screen.get("reproducing"):
        lines.append("- The screen recorded the listed reproducing outcomes at this benchmark start and "
                     "checkpoint in a simulator; no reduced wording was verified.")
    else:
        lines.append("- The screen recorded no paraphrase that failed at least 4 of 5 attempts at this "
                     "benchmark start and checkpoint in a simulator.")
    lines += [
              "- The tested family is rewordings of one instruction written by a language model; it does not "
              "cover other tasks, starts, seeds or kinds of language change.",
              "- It is not a causal proof. The paraphrases were not checked by a person for meaning; the mechanical "
              "check only confirms that every object or target word of the original is still present, so a "
              "synonym for an object is flagged and a changed relation (for example, a different place to put "
              "it) is not."]
    if verified_minimal:
        if minimal.get("edit_minimal"):
            lines.append("- The reduced wording is an edit-minimal local result: removing any one remaining edit "
                         "stopped the failure from reproducing; a different, smaller change might exist.")
        else:
            lines.append("- The reduced wording is the smallest change verified so far; the reduction did not "
                         "verify that every remaining edit is needed.")
    else:
        lines.append("- No failing wording was verified by reduction, so no minimal wording is claimed.")
    lines.append("")
    return "\n".join(lines)


def build_case_record(screen: Mapping[str, Any], reduction: Mapping[str, Any]) -> Dict[str, Any]:
    try:
        return le.build_case(reduction, screen)
    except ValueError as error:
        raise ReportError(str(error)) from None


def write_text(path: Path, text: str, force: bool) -> None:
    path = Path(path)
    if path.exists() and not force:
        raise ReportError("{} already exists; pass --force to overwrite".format(path.name))
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Report a paraphrase diagnosis.")
    parser.add_argument("screen", type=Path)
    parser.add_argument("--reduction", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--case-out", type=Path)
    parser.add_argument("--hourly-rate", type=float)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        screen = load_summary(args.screen, "paraphrase-screen")
        reduction = load_summary(args.reduction, "paraphrase-reduce") if args.reduction else None
        text = build_report(screen, reduction, args.hourly_rate)
        if args.out:
            write_text(args.out, text, args.force)
        else:
            print(text)
        if args.case_out:
            if reduction is None:
                raise ReportError("--case-out needs --reduction")
            write_text(args.case_out, json.dumps(build_case_record(screen, reduction), indent=2, sort_keys=True,
                                                 allow_nan=False) + "\n", args.force)
    except ReportError as error:
        print("error: {}".format(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
