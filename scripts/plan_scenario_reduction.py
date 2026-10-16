"""Plan a scenario reduction from a screen summary (runs on the workstation).

Reads the summary written by the ``scenario-screen`` Job, takes one start that
fails reproducibly, picks the nearest starts of the same task that passed the
screen as references, tabulates the differences, asks Nemotron (Token Factory)
for a ranking and a hypothesis, and writes the config for the
``scenario-reduce`` Job. The Token Factory call happens here, so no key ever
enters a Job; the key is read from the environment or ``--env-file`` and is
never printed or stored. ``--no-llm`` skips the call and uses the fixed order
(largest difference first); any model problem falls back to it too and the
reason is recorded in the config.

ASSUMED SCREEN SUMMARY SCHEMA (the Job-mode author must produce this shape)::

    {"suite": "libero_10",
     "tasks": {
       "<task_id>": {
         "instruction": "<language instruction of the task>",
         "layout": {<layout sidecar JSON: schema_version, suite, task_id,
                     state_length, nq, nv, joints[...]>},
         "starts": {
           "<start_index>": {"outcomes": ["success" | "policy_failure" |
                                          "invalid_scene", ...],
                             "state": [<flat MuJoCo state vector, floats>]}}}}}

``outcomes`` lists every screen attempt of the start in order (one for a start
that passed, five for a start that failed its first attempt and was confirmed).
Other keys (steps, videos, timings) are ignored. Task and start keys may be
JSON strings or integers.

OUTPUT CONFIG (schema_version 1)::

    {"schema_version": 1, "suite", "task_id", "instruction", "layout",
     "failing": {"start_index", "outcomes", "state"},
     "references": [{"start_index", "distance", "outcomes", "state",
                     "differences": [<scenario_state.differences rows>]}, ...],
     "order": [<entity names, first to test first>],
     "order_source": "model" | "fixed_order",
     "hypothesis": {"text", "ranking", "source", "model", "tier",
                    "fallback_reason", "completed", "provenance", "raw_content"}}

``references`` is nearest first; the reducer takes
``[{"id": r["start_index"], "differences": r["differences"]} for r in references]``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Dict, Mapping, Optional


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY_ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from robot_debug import scenario_state as ss
from robot_debug.scenario_hypothesis import nearest_reference
from robot_debug.token_factory import (
    TokenFactoryError,
    load_api_key,
    request_scenario_hypothesis,
)

SCHEMA_VERSION = 1
REQUIRED_FAILURES = 4
SCREEN_ATTEMPTS = 5
RAW_LIMIT = 8000       # the reduce workload accepts at most this many characters of the model reply
TRUNCATION_MARKER = "\n[truncated; the full reply is in the .hypothesis-raw.txt file beside the plan]"


class PlanError(ValueError):
    """A fixed, non-secret planning error."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise PlanError("invalid arguments")


def _parser() -> argparse.ArgumentParser:
    parser = Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("summary", type=Path, help="screen summary JSON")
    parser.add_argument("--task", type=int, required=True)
    parser.add_argument("--start", type=int, required=True, help="the failing start index")
    parser.add_argument("--out", type=Path, required=True, help="reduce config to write")
    parser.add_argument("--env-file", type=Path, help="dotenv file holding NEBIUS_API_KEY")
    parser.add_argument("--no-llm", action="store_true", help="skip Nemotron; use the fixed order")
    parser.add_argument("--references", type=int, default=3, help="nearest passing starts to keep (1-5)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing config")
    return parser


def _printable(text: str) -> str:
    """Unix newlines, and no control characters other than newline and tab."""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(" " if (ord(ch) < 32 and ch not in "\n\t") or ord(ch) == 127 else ch for ch in text)


def sanitise_reply(value: Any):
    """``(workload copy, full text)`` of a model reply.

    The workload copy has Unix newlines and no control characters, is ``None`` when empty and
    is cut to ``RAW_LIMIT`` characters ending in a marker; the full reply is kept for a sidecar.
    """

    if not isinstance(value, str):
        return None, None
    clean = _printable(value)
    if not clean.strip():
        return None, value
    if len(clean) > RAW_LIMIT:
        clean = clean[:RAW_LIMIT - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
    return clean, value


def _get(mapping: Mapping[Any, Any], key: int) -> Any:
    for candidate in (key, str(key)):
        if candidate in mapping:
            return mapping[candidate]
    return None


def load_summary(path: Path) -> Dict[str, Any]:
    try:
        summary = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PlanError("screen summary is unreadable") from None
    if type(summary) is not dict or type(summary.get("tasks")) is not dict \
            or type(summary.get("suite")) is not str:
        raise PlanError("screen summary needs suite and tasks")
    return summary


def build_plan(
    summary: Mapping[str, Any],
    task_id: int,
    start_index: int,
    *,
    use_llm: bool = True,
    env_file: Optional[Path] = None,
    references: int = 3,
    request: Callable[..., dict] = request_scenario_hypothesis,
    load_key: Callable[[Optional[Path]], str] = load_api_key,
) -> Dict[str, Any]:
    """The reduce config for one failing start (see the module docstring)."""

    return build_plan_with_reply(summary, task_id, start_index, use_llm=use_llm, env_file=env_file,
                                 references=references, request=request, load_key=load_key)[0]


def build_plan_with_reply(
    summary: Mapping[str, Any],
    task_id: int,
    start_index: int,
    *,
    use_llm: bool = True,
    env_file: Optional[Path] = None,
    references: int = 3,
    request: Callable[..., dict] = request_scenario_hypothesis,
    load_key: Callable[[Optional[Path]], str] = load_api_key,
    imported: Optional[Mapping[str, Any]] = None,
):
    """``(config, full model reply or None)``; the config carries only the sanitised reply.

    ``imported`` plans a failing start the user brought instead of one from the screen: a mapping with
    ``state`` (the flat start state), ``source`` (the scenario candidate's source) and the digests
    ``file_sha256`` and ``state_sha256``. ``start_index`` must then be ``None``. The imported start has not
    been screened (the reduce Job's own failing gate decides whether it fails), so ``failing.outcomes`` is
    empty, ``failing.start_index`` is ``None``, and the nearest passing screened start is its reference.
    """

    if not 1 <= references <= 5:
        raise PlanError("references must be between 1 and 5")
    task = _get(summary["tasks"], task_id)
    if type(task) is not dict or type(task.get("starts")) is not dict:
        raise PlanError("the task is not in the screen summary")
    instruction = task.get("instruction")
    if type(instruction) is not str or not instruction.strip():
        raise PlanError("the task has no instruction")
    try:
        layout = ss.validate_layout(task.get("layout"))
    except ss.ScenarioStateError:
        raise PlanError("the task layout is invalid") from None
    if imported is None:
        failing = _get(task["starts"], start_index)
        if type(failing) is not dict:
            raise PlanError("the failing start is not in the screen summary")
        if failing.get("validity") == "invalid_scene":
            raise PlanError("the failing start is an interpenetrating scene, not a policy failure")
        outcomes = failing.get("outcomes")
        if not isinstance(outcomes, list) or len(outcomes) < SCREEN_ATTEMPTS \
                or outcomes[:SCREEN_ATTEMPTS].count("policy_failure") < REQUIRED_FAILURES:
            raise PlanError("the start did not fail at least 4 of 5 screen attempts")
    else:
        if start_index is not None:
            raise PlanError("an imported start has no start index")
        failing, outcomes = {"state": imported.get("state")}, []

    # A start whose recorded contact scan found interpenetrating bodies cannot be a reference.
    results = {task_id: {k: v.get("outcomes") for k, v in task["starts"].items()
                         if isinstance(v, dict) and v.get("validity") != "invalid_scene"}}
    states = {task_id: {k: v.get("state") for k, v in task["starts"].items()
                        if isinstance(v, dict)}}
    try:
        failing_state = ss.validate_state(failing.get("state"), layout)
    except (ss.ScenarioStateError, ValueError):
        if imported is not None:
            raise PlanError("the imported start's state does not fit this task's scene (wrong task or suite?)") \
                from None
        raise PlanError("start states do not match the task layout") from None
    try:
        ranked = nearest_reference(task_id, start_index, results, states, layout,
                                   count=references + 5, failing_state=failing_state)
    except (ss.ScenarioStateError, ValueError):
        raise PlanError("start states do not match the task layout") from None
    chosen = []
    for entry in ranked:
        state = ss.validate_state(_get(task["starts"], entry["start_index"])["state"], layout)
        table = ss.differences(failing_state, state, layout)
        if not table:
            continue          # indistinguishable from the failing start: nothing to reduce
        chosen.append({**entry, "state": state.tolist(), "differences": table})
        if len(chosen) == references:
            break
    if not chosen:
        raise PlanError("no passing start with differences was found for this task")

    primary = chosen[0]["differences"]
    fixed = ss.fixed_order(primary)
    if not use_llm:
        hypothesis = _fixed_hypothesis(fixed, "llm_disabled")
    else:
        try:
            api_key = load_key(env_file)
        except TokenFactoryError as error:
            hypothesis = _fixed_hypothesis(fixed, str(error))
        else:
            hypothesis = request(instruction, primary, api_key, fixed_order=fixed)

    raw_for_workload, raw_full = sanitise_reply(hypothesis.get("raw_content"))
    text = hypothesis["hypothesis"]
    config = {
        "schema_version": SCHEMA_VERSION,
        "suite": summary["suite"],
        "task_id": task_id,
        "instruction": instruction.strip(),
        "layout": layout,
        "failing": _failing_block(start_index, outcomes, failing_state, imported),
        "references": chosen,
        "order": list(hypothesis["ranking"]),
        "order_source": hypothesis["source"],
        "hypothesis": {
            "text": _printable(text) if isinstance(text, str) else text, "ranking": list(hypothesis["ranking"]),
            "source": hypothesis["source"], "model": hypothesis.get("model"),
            "tier": hypothesis.get("tier"), "fallback_reason": hypothesis.get("fallback_reason"),
            "completed": list(hypothesis.get("completed", [])),
            "provenance": hypothesis.get("provenance"), "raw_content": raw_for_workload,
        },
    }
    return config, raw_full


def _failing_block(start_index: Optional[int], outcomes: Any, state: Any,
                   imported: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    block = {"start_index": start_index, "outcomes": list(outcomes), "state": state.tolist()}
    if imported is not None:
        block["source"] = dict(imported["source"])
        block["import"] = {"file_sha256": imported["file_sha256"], "state_sha256": imported["state_sha256"]}
    return block


def _fixed_hypothesis(order, reason: str) -> Dict[str, Any]:
    return {"source": "fixed_order", "ranking": list(order), "hypothesis": None, "completed": [],
            "model": None, "tier": None, "fallback_reason": reason, "provenance": None,
            "raw_content": None}


def write_config(config: Mapping[str, Any], out: Path, *, force: bool = False) -> None:
    text = json.dumps(config, indent=1, sort_keys=True, allow_nan=False) + "\n"
    out = Path(out)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w" if force else "x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError:
        raise PlanError("the output file exists (use --force to replace it)") from None
    except OSError:
        raise PlanError("the config could not be written") from None


def write_raw_reply(reply: str, out: Path, *, force: bool = False) -> None:
    """Keep the untruncated model reply beside the plan (never in the workload)."""

    target = Path(out).with_name(Path(out).name + ".hypothesis-raw.txt")
    try:
        with target.open("w" if force else "x", encoding="utf-8", newline="") as handle:
            handle.write(reply)
    except FileExistsError:
        raise PlanError("the raw reply file exists (use --force to replace it)") from None
    except OSError:
        raise PlanError("the raw reply could not be written") from None


def main(argv=None, *, request: Callable[..., dict] = request_scenario_hypothesis,
         load_key: Callable[[Optional[Path]], str] = load_api_key) -> int:
    try:
        args = _parser().parse_args(argv)
        summary = load_summary(args.summary)
        config, full_reply = build_plan_with_reply(
            summary, args.task, args.start, use_llm=not args.no_llm, env_file=args.env_file,
            references=args.references, request=request, load_key=load_key)
        write_config(config, args.out, force=args.force)
        if full_reply:
            write_raw_reply(full_reply, args.out, force=args.force)
        print(json.dumps({
            "task_id": config["task_id"], "failing_start": args.start,
            "references": [r["start_index"] for r in config["references"]],
            "entities": config["order"], "order_source": config["order_source"],
            "model": config["hypothesis"]["model"],
            "fallback_reason": config["hypothesis"]["fallback_reason"],
        }, sort_keys=True))
        return 0
    except PlanError as error:
        print(json.dumps({"error": str(error)}, sort_keys=True))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"error": "planning interrupted"}, sort_keys=True))
        return 130
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        print(json.dumps({"error": "planning failed"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
