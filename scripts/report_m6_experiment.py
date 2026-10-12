"""Render M6 summaries as Markdown for the experiment note.

Usage: ``python scripts/report_m6_experiment.py SUMMARY.json [SUMMARY.json ...] [--output FILE]``.
Each file is an ``m6_summary.json`` written by an ``m6-smoke`` or ``m6-threshold``
Job. A smoke summary yields the wrist-camera table and a one-level look at each
scalar family; a threshold summary yields the threshold table. Local files only,
no network access.

The plain-language reading is rule-based and states counts, not conclusions: the
tables are the evidence and nothing here is a causal or general claim (ADR 0026).
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

from robot_debug.image_perturbation import physical_value  # noqa: E402

M6_MODES = ("m6-smoke", "m6-threshold")
WRIST_CONDITIONS = (
    ("nominal", "Nominal control (no perturbation)"),
    ("agentview_mask_wrist_black", "Reduced agent-view mask + wrist image black"),
    ("wrist_mask_only", "Same rectangle on the wrist image only"),
)
FAMILY_LABELS = {
    "darken": "Darkening",
    "noise": "Gaussian noise",
    "blur": "Gaussian blur",
    "contrast": "Contrast reduction",
}
_PHYSICAL_FORMAT = {
    "brightness_factor": "brightness x{:.2f}",
    "noise_sigma": "noise sigma {:.1f} of 255",
    "blur_sigma_px": "blur sigma {:.2f} px",
    "contrast_factor": "contrast x{:.2f}",
}
_STOP_TEXT = {
    "threshold_found": "threshold found",
    "no_reproducible_failure": "no reproducible failure up to s = 1.0",
    "budget_exhausted": "attempt budget exhausted",
    "deadline_exhausted": "Job deadline reached",
    "infrastructure_error": "infrastructure error",
    "nominal_failed": "not run: nominal controls failed",
    "not_run": "not run",
}


class ReportError(ValueError):
    """The summary is missing or malformed."""


def load_summary(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReportError("summary could not be read: {}".format(type(error).__name__)) from error
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("mode") not in M6_MODES:
        raise ReportError("summary is not an M6 summary of a supported schema")
    if not isinstance(data.get("conditions"), dict) or not isinstance(data.get("families"), dict):
        raise ReportError("summary conditions and families must be objects")
    if data["mode"] == "m6-threshold" and not isinstance(data.get("config"), dict):
        raise ReportError("a threshold summary needs its config")
    return data


def _cell(value: Any, digits: int = 1) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return "{:.{}f}".format(value, digits)
    return str(value)


def _severity(value: Any) -> str:
    return "-" if value is None else "{:g}".format(value)


def physical_text(physical: Optional[Mapping[str, Any]]) -> str:
    if not physical:
        return "-"
    template = _PHYSICAL_FORMAT.get(str(physical.get("name")))
    if template is None or not isinstance(physical.get("value"), (int, float)):
        return "-"
    return template.format(physical["value"])


def _counts(row: Mapping[str, Any]) -> Dict[str, int]:
    outcomes = row.get("outcomes") or {}
    successes = int(outcomes.get("success", 0))
    failures = int(outcomes.get("policy_failure", 0))
    planned = row.get("planned")
    valid = int(row.get("valid", successes + failures))
    return {
        "success": successes, "failure": failures, "valid": valid,
        "missing": 0 if planned is None else max(0, int(planned) - valid),
    }


def wrist_table(conditions: Mapping[str, Any]) -> List[str]:
    lines = [
        "| Condition | Runs | Successes | Policy failures | Not completed | Median duration (s) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, label in WRIST_CONDITIONS:
        row = conditions.get(key)
        if row is None:
            continue
        counts = _counts(row)
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            label, counts["valid"] + counts["missing"], counts["success"], counts["failure"],
            counts["missing"], _cell(row.get("median_duration_seconds"))))
    return lines


def wrist_reading(conditions: Mapping[str, Any]) -> List[str]:
    sentences: List[str] = []
    nominal = conditions.get("nominal")
    if nominal is not None:
        counts = _counts(nominal)
        if counts["valid"] and counts["failure"] == 0 and counts["missing"] == 0:
            sentences.append("All {} nominal runs succeeded, so the unperturbed path is intact.".format(counts["valid"]))
        else:
            sentences.append(
                "**The nominal controls did not all succeed ({} successes, {} failures, {} not completed); "
                "treat every other row as unusable until this is understood.**".format(
                    counts["success"], counts["failure"], counts["missing"]))
    for key, label, meaning in (
        ("agentview_mask_wrist_black", "Reduced agent-view mask with the wrist image blacked out", {
            "all_failed": "both cameras were degraded in these runs",
            "all_succeeded": "the policy completed the task even with the wrist image black",
        }),
        ("wrist_mask_only", "The same rectangle on the wrist image only", {
            "all_failed": "this wrist rectangle alone was enough to cause failure here",
            "all_succeeded": "this wrist rectangle alone did not cause failure here",
        }),
    ):
        row = conditions.get(key)
        if row is None:
            continue
        counts = _counts(row)
        if counts["valid"] == 0:
            sentences.append("{}: no completed runs.".format(label))
        elif counts["failure"] == counts["valid"]:
            sentences.append("{} failed in all {} completed runs ({}).".format(
                label, counts["valid"], meaning["all_failed"]))
        elif counts["success"] == counts["valid"]:
            sentences.append("{} succeeded in all {} completed runs ({}).".format(
                label, counts["valid"], meaning["all_succeeded"]))
        else:
            sentences.append("{} failed in {} of {} completed runs.".format(
                label, counts["failure"], counts["valid"]))
    sentences.append(
        "These counts describe this rectangle and these two conditions on one task; they do not by "
        "themselves show which camera the policy relies on.")
    return sentences


def smoke_family_table(conditions: Mapping[str, Any], families: Sequence[str]) -> List[str]:
    lines = [
        "| Family | Severity | Physical value | Successes | Policy failures | Median duration (s) |",
        "| --- | ---: | --- | ---: | ---: | ---: |",
    ]
    for family in families:
        for key, row in conditions.items():
            if not key.startswith(family + "_"):
                continue
            severity = float(key.split("_", 1)[1])
            counts = _counts(row)
            lines.append("| {} | {:g} | {} | {} | {} | {} |".format(
                FAMILY_LABELS.get(family, family), severity,
                physical_text(physical_value(family, severity)), counts["success"], counts["failure"],
                _cell(row.get("median_duration_seconds"))))
    return lines


def _levels_text(levels: Sequence[Mapping[str, Any]]) -> str:
    parts = []
    for level in levels:
        failures = level.get("failures")
        done = len(level.get("outcomes") or ())
        parts.append("{:g}: {}/{}{}".format(
            level["severity"], "?" if failures is None else failures, done,
            "" if level.get("complete") else " (incomplete)"))
    return "; ".join(parts) if parts else "-"


def _ordered(families: Mapping[str, Any], order: Sequence[str]) -> List[str]:
    """Family names in the configured order (stored JSON is key-sorted), unknown ones last."""

    known = [name for name in order if name in families]
    return known + [name for name in families if name not in known]


def threshold_table(families: Mapping[str, Any], order: Sequence[str] = ()) -> List[str]:
    lines = [
        "| Family | Smallest reproducibly failing severity | Physical value | Last non-reproducing level "
        "| Levels tried | Episodes | Stop reason |",
        "| --- | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for family in _ordered(families, order):
        result = families[family]
        threshold = result.get("threshold_severity")
        if threshold is None and result.get("stop_reason") == "no_reproducible_failure":
            shown = "none up to 1.0"
        else:
            shown = _severity(threshold)
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            FAMILY_LABELS.get(family, family), shown, physical_text(result.get("threshold_physical")),
            _severity(result.get("lower_bound")) if result.get("levels") else "-",
            len(result.get("levels") or ()), result.get("attempts_used", 0),
            _STOP_TEXT.get(str(result.get("stop_reason")), str(result.get("stop_reason")))))
    return lines


def level_table(families: Mapping[str, Any], order: Sequence[str] = ()) -> List[str]:
    lines = ["| Family | Levels in the order tried (severity: failures/attempts) |", "| --- | --- |"]
    for family in _ordered(families, order):
        lines.append("| {} | {} |".format(
            FAMILY_LABELS.get(family, family), _levels_text(families[family].get("levels") or ())))
    return lines


def threshold_reading(families: Mapping[str, Any], config: Mapping[str, Any]) -> List[str]:
    sentences: List[str] = []
    gate = "{} of {}".format(config["required_failures"], config["attempts"])
    for family in _ordered(families, config.get("families") or ()):
        result = families[family]
        label = FAMILY_LABELS.get(family, family)
        stop = result.get("stop_reason")
        threshold = result.get("threshold_severity")
        lower = result.get("lower_bound")
        if stop == "threshold_found" and threshold is not None:
            sentences.append(
                "{}: reliably fails ({} attempts failing) from s = {:g} ({}); s = {:g} did not reproduce, so the "
                "boundary under this rule lies in ({:g}, {:g}].".format(
                    label, gate, threshold, physical_text(result.get("threshold_physical")),
                    lower, lower, threshold))
        elif stop == "no_reproducible_failure":
            sentences.append(
                "{}: no level up to s = 1.0 reached {} failures, so the policy is robust to this family in the "
                "tested range (not a claim beyond it).".format(label, gate))
        elif stop == "nominal_failed":
            sentences.append("{}: not evaluated, the nominal controls did not all succeed.".format(label))
        else:
            detail = ""
            if threshold is not None:
                detail = " The best reproducing level seen so far is s = {:g} (coarse, not refined).".format(threshold)
            sentences.append("{}: incomplete ({}).{}".format(
                label, _STOP_TEXT.get(str(stop), str(stop)), detail))
    return sentences


def timing_lines(summary: Mapping[str, Any]) -> List[str]:
    lines = []
    valid = summary.get("valid_count")
    warm = summary.get("warm_elapsed_seconds")
    if isinstance(valid, int) and isinstance(warm, (int, float)) and warm > 0:
        lines.append("{} valid episodes in {:.0f} s of timed work ({:.1f} episodes/min on one 12-worker server).".format(
            valid, warm, valid / warm * 60.0))
    timing = summary.get("timing")
    if timing:
        lines.append("Mean batch size {} (largest {}); model busy share {}.".format(
            _cell(timing.get("mean_batch_size"), 2), timing.get("max_batch_size_observed"),
            "-" if timing.get("model_call_busy_share") is None
            else "{:.0f}%".format(100.0 * timing["model_call_busy_share"])))
    if summary.get("prefetch_seconds") is not None:
        lines.append("Prefetch took {} s (not part of the timed work).".format(_cell(summary["prefetch_seconds"])))
    warmup = summary.get("warmup")
    if warmup:
        lines.append("Untimed warm-up: `{}`, {}, {} s.".format(
            warmup.get("case_id"), warmup.get("status"), _cell(warmup.get("duration_seconds"))))
    if summary.get("not_started"):
        lines.append("Items that never started: {}.".format(
            ", ".join("{} {}".format(count, reason) for reason, count in sorted(summary["not_started"].items()))))
    removed = summary.get("sqlite_companions_removed")
    if removed:
        lines.append("{} stray SQLite companion files were removed before export.".format(removed))
    return lines


def render_smoke(summary: Mapping[str, Any]) -> List[str]:
    conditions = summary["conditions"]
    lines = ["## Wrist-camera conditions (smoke Job)", ""]
    if summary.get("stop_reason"):
        lines += ["Stopped early: `{}`.".format(summary["stop_reason"]), ""]
    lines += wrist_table(conditions) + [""]
    lines += ["- " + sentence for sentence in wrist_reading(conditions)]
    families = [name for name in FAMILY_LABELS if any(key.startswith(name + "_") for key in conditions)]
    if families:
        lines += ["", "## Scalar families at one severity (smoke Job)", ""]
        lines += smoke_family_table(conditions, families)
        lines += ["", "A single level per family only shows that each family reaches the policy and can be run; "
                  "it does not locate a threshold."]
    return lines + ["", *timing_lines(summary)]


def render_threshold(summary: Mapping[str, Any]) -> List[str]:
    config = summary["config"]
    families = summary["families"]
    nominal = summary.get("nominal_controls") or {}
    lines = ["## Threshold search per family (main Job)", ""]
    if summary.get("stop_reason"):
        lines += ["Stopped early: `{}`.".format(summary["stop_reason"]), ""]
    lines += [
        "Rule: sweep s in {} in increasing order; a level is a reproducible failure at {} policy failures "
        "among {} attempts; then bisect {} times between the last non-reproducing level and the first "
        "reproducing one. Nominal controls: {} of {} succeeded.".format(
            ", ".join("{:g}".format(level) for level in config["sweep"]),
            "{} of {}".format(config["required_failures"], config["attempts"]), config["attempts"],
            config["bisection_steps"], (nominal.get("outcomes") or {}).get("success", 0),
            nominal.get("planned", "-")),
        "",
    ]
    order = config.get("families") or ()
    lines += threshold_table(families, order) + ["", *level_table(families, order), ""]
    lines += ["- " + sentence for sentence in threshold_reading(families, config)]
    return lines + ["", *timing_lines(summary)]


def render_report(summaries: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# M6 results: camera reliance and scalar image families",
        "",
        "Scope: GR00T N1.7 on LIBERO-Object task 0 with seed 7, on one L40S. Thresholds are budget-local "
        "(the attempts per level and bisection steps stated below) and describe reliable failure, not the "
        "onset of any failure. Image-space transforms approximate, not simulate, lighting and sensor effects.",
        "",
    ]
    for summary in summaries:
        if summary["mode"] == "m6-smoke":
            lines += render_smoke(summary)
        else:
            lines += render_threshold(summary)
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render M6 summaries as Markdown.")
    parser.add_argument("summary", type=Path, nargs="+", help="m6_summary.json from an m6-smoke or m6-threshold Job")
    parser.add_argument("--output", type=Path, help="write here instead of standard output")
    args = parser.parse_args(argv)
    try:
        text = render_report([load_summary(path) for path in args.summary])
    except ReportError as error:
        print("report rejected: {}".format(error), file=sys.stderr)
        return 2
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
