"""Render an M3 batched-inference summary as Markdown for the experiment note.

Usage: ``python scripts/report_batch_experiment.py batch_summary.json [--output FILE]``.
Reads one local JSON file written by the ``m3-batch`` workload modes; no network
access. The explanation is rule-based and every threshold is a stated heuristic,
not a measured law: the table is the evidence, the text only helps read it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

# Heuristic readings of the server busy share (time inside model calls / phase wall time).
SATURATED_SHARE = 0.85
IDLE_SHARE = 0.50
SCALING_SLACK = 0.80

_VERDICT_TEXT = {
    "works": "outcomes match and batched throughput is at least 15% above unbatched.",
    "no_measurable_gain": "batched throughput stayed under +15% of unbatched.",
    "outcome_drift": "a nominal run failed or a reduced-mask run succeeded, so throughput cannot be claimed.",
    "incomplete": "the unbatched/batched pair did not both finish the full manifest.",
}


class ReportError(ValueError):
    """The summary is missing or malformed."""


def load_summary(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReportError("summary could not be read: {}".format(type(error).__name__)) from error
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ReportError("summary has an unsupported schema")
    for key in ("mode", "phases", "passing_worker_counts", "comparisons"):
        if key not in data:
            raise ReportError("summary is missing {}".format(key))
    if not isinstance(data["phases"], list) or not isinstance(data["comparisons"], list):
        raise ReportError("summary phases and comparisons must be lists")
    return data


def _cell(value: Any, digits: int = 1) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return "{:.{}f}".format(value, digits)
    return str(value)


def _percent(value: Any) -> str:
    return "-" if value is None else "{:.0f}%".format(100.0 * float(value))


def _timing(phase: Mapping[str, Any]) -> Mapping[str, Any]:
    return phase.get("timing") or {}


def phase_table(phases: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = [
        "| Phase | Workers | Batch | Status | Valid | Warm (s) | Episodes/min | Drift | Calls | Mean batch | p95 batch "
        "| Inference p50/p95 (ms) | Wait p50/p95 (ms) | Model-call busy |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for phase in phases:
        timing = _timing(phase)
        drift = ", ".join(phase.get("drift_ids") or []) or "none"
        lines.append(
            "| {label} | {w} | {b} | {status} | {valid}/{planned} | {warm} | {epm} | {drift} | {calls} | {mean} | {p95} "
            "| {ip50}/{ip95} | {wp50}/{wp95} | {busy} |".format(
                label=phase.get("label", "-"), w=phase.get("workers", "-"), b=phase.get("max_batch_size", "-"),
                status=phase.get("status", "-"), valid=phase.get("valid_count", 0),
                planned=phase.get("planned", "-"), warm=_cell(phase.get("warm_elapsed_seconds")),
                epm=_cell(phase.get("episodes_per_minute"), 2), drift=drift, calls=_cell(timing.get("calls")),
                mean=_cell(timing.get("mean_batch_size"), 2), p95=_cell(timing.get("p95_batch_size"), 1),
                ip50=_cell(timing.get("inference_ms_p50")), ip95=_cell(timing.get("inference_ms_p95")),
                wp50=_cell(timing.get("wait_ms_p50")), wp95=_cell(timing.get("wait_ms_p95")),
                busy=_percent(timing.get("model_call_busy_share")),
            )
        )
    return lines


def comparison_table(comparisons: Sequence[Mapping[str, Any]], bar: float) -> List[str]:
    lines = [
        "| Workers | Unbatched (episodes/min) | Batched (episodes/min) | Speedup | Bar | Result |",
        "| ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in comparisons:
        speedup = item.get("speedup")
        lines.append(
            "| {w} | {u} | {b} | {s} | {bar:.2f}x | {r} |".format(
                w=item.get("workers"), u=_cell(item.get("unbatched_episodes_per_minute"), 2),
                b=_cell(item.get("batched_episodes_per_minute"), 2),
                s="-" if speedup is None else "{:.3f}x".format(speedup), bar=bar,
                r=item.get("verdict") or item.get("status", "-"),
            )
        )
    return lines


def bottleneck_explanation(summary: Mapping[str, Any]) -> List[str]:
    """Plain-language reading of where the time goes, from the unbatched phases."""

    phases = summary["phases"]
    unbatched = sorted(
        (p for p in phases if p.get("max_batch_size") == 1 and p.get("status") == "complete"
         and p.get("episodes_per_minute")),
        key=lambda p: p["workers"],
    )
    lines: List[str] = []
    if not unbatched:
        return ["There is no completed unbatched phase, so this run cannot say where the bottleneck sits."]
    top = unbatched[-1]
    timing = _timing(top)
    share = timing.get("model_call_busy_share")
    if share is None:
        lines.append(
            "The {} worker unbatched phase has no server timing, so the server's share of the time is unknown.".format(
                top["workers"])
        )
    elif share >= SATURATED_SHARE:
        lines.append(
            "With {w} workers the model server spent about {s} of the phase inside model calls. It is close to "
            "saturated: every extra worker mostly waits in the server's queue, which is the situation batching can "
            "help.".format(w=top["workers"], s=_percent(share))
        )
    elif share <= IDLE_SHARE:
        lines.append(
            "With {w} workers the model server spent only about {s} of the phase inside model calls. It was idle "
            "much of the time, so the simulator and evaluator processes on the CPU, not the GPU, set the pace; "
            "batching has little to speed up.".format(w=top["workers"], s=_percent(share))
        )
    else:
        lines.append(
            "With {w} workers the model server spent about {s} of the phase inside model calls: busy, but not "
            "saturated. Both the CPU-side simulators and the server limit throughput, so batching may help only "
            "modestly.".format(w=top["workers"], s=_percent(share))
        )
    wait, inference = timing.get("wait_ms_p50"), timing.get("inference_ms_p50")
    if wait is not None and inference:
        lines.append(
            "A typical request waited {w:.0f} ms before inference started and then took {i:.0f} ms; "
            "queueing {r} the inference time itself.".format(
                w=wait, i=inference, r="exceeded" if wait > inference else "stayed below")
        )
    if len(unbatched) >= 2:
        low = unbatched[0]
        ratio = top["episodes_per_minute"] / low["episodes_per_minute"]
        ideal = top["workers"] / float(low["workers"])
        if ratio < SCALING_SLACK * ideal:
            lines.append(
                "Going from {a} to {b} workers raised throughput {r:.2f}x against an ideal {i:.1f}x, so adding workers "
                "had stopped paying off.".format(a=low["workers"], b=top["workers"], r=ratio, i=ideal)
            )
        else:
            lines.append(
                "Going from {a} to {b} workers raised throughput {r:.2f}x against an ideal {i:.1f}x, so scaling was "
                "still close to linear.".format(a=low["workers"], b=top["workers"], r=ratio, i=ideal)
            )
    for item in phases:
        if item.get("max_batch_size", 1) > 1 and item.get("status") == "complete":
            mean = _timing(item).get("mean_batch_size")
            if mean is not None:
                lines.append(
                    "In the {w} worker batched phase the server averaged {m:.2f} requests per model call "
                    "(limit {b}).{extra}".format(
                        w=item["workers"], m=mean, b=item["max_batch_size"],
                        extra=" Batching barely engaged because requests rarely overlapped." if mean < 1.5 else "")
                )
    lines.append(
        "These readings use fixed rules of thumb (saturated at {:.0f}% busy, idle below {:.0f}%); the table above is "
        "the evidence.".format(100 * SATURATED_SHARE, 100 * IDLE_SHARE)
    )
    return lines


def verdict_lines(summary: Mapping[str, Any]) -> List[str]:
    lines = []
    for item in summary["comparisons"]:
        verdict = item.get("verdict") or "incomplete"
        speedup = item.get("speedup")
        extra = "" if speedup is None else " ({:.3f}x)".format(speedup)
        drift = item.get("drift_ids") or []
        if drift:
            extra += " [drift: {}]".format(", ".join(drift))
        lines.append("- {} workers: `{}`{}: {}".format(
            item.get("workers"), verdict, extra, _VERDICT_TEXT.get(verdict, "")))
    if not lines:
        lines.append("- No worker count has both an unbatched and a batched phase in this run.")
    passing = summary.get("passing_worker_counts") or []
    lines.append("")
    lines.append("Worker counts that passed: {}.".format(", ".join(str(w) for w in passing) if passing else "none"))
    lines.append("Parity gate: `{}`.".format(summary.get("parity_gate", "not_run")))
    return lines


def parity_lines(summary: Mapping[str, Any]) -> List[str]:
    parity = summary.get("parity")
    if parity is None:
        return ["Parity: not run in this Job ({}).".format(summary.get("parity_note") or "see the smoke Job")]
    lines = [
        "Parity: **{}**; largest item difference {} against a tolerance of {}.{}".format(
            "passed" if parity.get("passed") else "failed", _cell(parity.get("max_abs_diff"), 4),
            _cell(parity.get("tolerance"), 3), " Error: {}".format(parity["error"]) if parity.get("error") else "")
    ]
    if parity.get("compared_before_gripper_rounding"):
        per_dim = parity.get("per_dim_max_abs_diff") or []
        lines.append(
            "It was judged on every action dimension before the gripper rounding step (per-dimension maxima: {}); "
            "{} gripper flips after rounding (information only, not part of the verdict).".format(
                ", ".join("{:.3f}".format(value) for value in per_dim) or "-",
                parity.get("gripper_flips_after_rounding", "-"))
        )
    return lines


def setup_lines(summary: Mapping[str, Any]) -> List[str]:
    lines = []
    warmup = summary.get("warmup")
    if warmup:
        lines.append(
            "Warm-up episode `{}`: {}, {} in {} s (excluded from every phase).".format(
                warmup.get("case_id"), warmup.get("status"), warmup.get("outcome") or "no outcome",
                _cell(warmup.get("duration_seconds"))))
    if summary.get("prefetch_seconds") is not None:
        lines.append("Prefetch took {} s (not part of any phase).".format(_cell(summary["prefetch_seconds"])))
    removed = summary.get("sqlite_companions_removed")
    if removed:
        lines.append("{} stray SQLite companion files were removed before export.".format(removed))
    return lines


def render_report(summary: Mapping[str, Any]) -> str:
    bar = float(summary.get("speedup_bar", 1.15))
    lines = [
        "# M3 batched-inference results ({})".format(summary["mode"]),
        "",
        "Manifest `{}`: {} items per phase, task 0, nominal then reduced-mask repeats. Known outcomes: nominal "
        "succeeds, reduced mask fails.".format(summary.get("manifest_hash", "-"), summary.get("items_per_phase", "-")),
    ]
    if summary.get("stop_reason"):
        lines += ["", "Stopped early: `{}`.".format(summary["stop_reason"])]
    lines += [""] + parity_lines(summary)
    setup = setup_lines(summary)
    if setup:
        lines += [""] + setup
    smoke = summary.get("smoke")
    if smoke:
        lines += [
            "",
            "Smoke gate: **{}** (parity {}, batched phase complete {}, no drift {}, largest batch seen {}).".format(
                "passed" if smoke.get("passed") else "not passed", smoke.get("parity_passed"),
                smoke.get("batched_phase_complete"), smoke.get("no_outcome_drift"),
                smoke.get("max_batch_size_observed")),
        ]
    lines += ["", "## Phases", ""] + phase_table(summary["phases"])
    if summary["comparisons"]:
        lines += ["", "## Batched against unbatched", ""] + comparison_table(summary["comparisons"], bar)
    lines += ["", "## Verdict per worker count", ""] + verdict_lines(summary)
    lines += ["", "## Where the bottleneck sits", ""]
    lines += ["- " + sentence for sentence in bottleneck_explanation(summary)]
    lines += [
        "",
        "Scope: GR00T N1.7 on LIBERO-Object task 0 with this harness and one L40S. This is a replay-throughput "
        "measurement, not a statement about search speed, other policies or batching in general.",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render a batched-inference summary as Markdown.")
    parser.add_argument("summary", type=Path, help="batch_summary.json from an m3-batch Job")
    parser.add_argument("--output", type=Path, help="write here instead of standard output")
    args = parser.parse_args(argv)
    try:
        text = render_report(load_summary(args.summary))
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
