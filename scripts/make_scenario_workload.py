"""Write a validated workload JSON for a scenario Job mode (runs on the workstation).

    make_scenario_workload.py smoke  --run-id ID --out FILE [--task-id 0] [--suite libero_10]
    make_scenario_workload.py screen --run-id ID --out FILE --tasks 0-9 --starts 0-9
    make_scenario_workload.py reduce --run-id ID --out FILE --plan PLAN.json [--max-candidates 30]

The deadline defaults to the recommended one for the mode (``--deadline`` overrides it).
``reduce`` takes the config written by ``plan_scenario_reduction.py``. The result goes
through the same validation the Job applies, so a bad file is refused here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Sequence

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from robot_debug import scenario_experiment as se
from robot_debug.job_runtime import JobRuntimeError, validate_workload_config

MAX_WORKLOAD_BYTES = 64 * 1024


class UsageError(ValueError):
    """A fixed, non-secret usage problem."""


def parse_indices(text: str) -> List[int]:
    """``"0-9"``, ``"0,3,5"`` or ``"0-2,7"`` as a list of integers."""

    values: List[int] = []
    try:
        for part in text.split(","):
            if "-" in part:
                low, high = part.split("-", 1)
                values.extend(range(int(low), int(high) + 1))
            else:
                values.append(int(part))
    except ValueError:
        raise UsageError("indices must look like 0-9 or 0,3,5") from None
    return values


def build(args: argparse.Namespace) -> Dict[str, Any]:
    if args.mode == "smoke":
        config = {"mode": "scenario-smoke", "suite": args.suite, "task_id": args.task_id}
    elif args.mode == "screen":
        config = {"mode": "scenario-screen", "suite": args.suite, "task_ids": parse_indices(args.tasks),
                  "start_indices": parse_indices(args.starts), "attempts": 1,
                  "confirm_attempts": args.confirm_attempts}
    else:
        try:
            plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise UsageError("the plan is unreadable") from None
        options = {key: value for key, value in (
            ("max_candidates", args.max_candidates), ("concurrency", args.concurrency),
            ("bisection_steps", args.bisection_steps)) if value is not None}
        try:
            config = se.build_reduce_workload(plan, run_id=args.run_id, deadline_seconds=args.deadline, **options)
        except (KeyError, TypeError, ValueError):
            raise UsageError("the plan is not a scenario reduction plan") from None
        return validate_workload_config(config)
    config.update(schema_version=1, run_id=args.run_id)
    config["deadline_seconds"] = args.deadline or se.recommended_deadline_seconds(config["mode"], config)
    return validate_workload_config(config)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    for name in ("smoke", "screen", "reduce"):
        child = sub.add_parser(name)
        child.add_argument("--run-id", required=True)
        child.add_argument("--out", type=Path, required=True)
        child.add_argument("--deadline", type=int, default=None)
        child.add_argument("--force", action="store_true")
        if name != "reduce":
            child.add_argument("--suite", default=se.DEFAULT_SUITE)
    sub.choices["smoke"].add_argument("--task-id", type=int, default=0)
    sub.choices["screen"].add_argument("--tasks", required=True)
    sub.choices["screen"].add_argument("--starts", required=True)
    sub.choices["screen"].add_argument("--confirm-attempts", type=int, default=4)
    reduce = sub.choices["reduce"]
    reduce.add_argument("--plan", type=Path, required=True)
    reduce.add_argument("--max-candidates", type=int, default=None)
    reduce.add_argument("--concurrency", type=int, default=None)
    reduce.add_argument("--bisection-steps", type=int, default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = _parser().parse_args(argv)
        workload = build(args)
        text = json.dumps(workload, indent=1, sort_keys=True, allow_nan=False) + "\n"
        if len(text.encode("utf-8")) > MAX_WORKLOAD_BYTES:
            raise UsageError("the workload exceeds 64 KiB")
        try:
            with args.out.open("w" if args.force else "x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except FileExistsError:
            raise UsageError("the output file exists (use --force)") from None
        print(json.dumps({"mode": workload["mode"], "run_id": workload["run_id"],
                          "deadline_seconds": workload["deadline_seconds"], "suite": workload["suite"]},
                         sort_keys=True))
        return 0
    except (UsageError, JobRuntimeError, ValueError) as error:
        print(json.dumps({"error": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
