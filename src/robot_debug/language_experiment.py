"""Job modes for instruction paraphrases (ADR 0032, breadth pack).

Two Serverless modes share the scenario machinery (one prefetch, one faultline server with
``max_batch_size = 12``, an untimed warm-up, concurrent single-episode evaluators, early-decided
repeatability gates, the SQLite scrub and the closed-evidence export) and one pool of 12 workers:

``paraphrase-screen``
    The original instruction is run twice as a control and each paraphrase once, from one benchmark
    start. A paraphrase that failed is confirmed through the early-decided 4-of-5 gate, and a
    reproducing one is topped up to five attempts.

``paraphrase-reduce``
    Given the original and one reproducing paraphrase, delta debugging over the word edits between
    them (:func:`robot_debug.paraphrase.word_edits`) finds a 1-minimal set of edits that still makes
    the policy fail. Gates first: the original wording must pass 5 of 5 and the full paraphrase must
    fail 4 of 5. Candidates are the original with a subset of the edits applied
    (:func:`robot_debug.paraphrase.apply_edits`), cached by text and run through the same gates.

Every episode receives its instruction through the benchmark options ``instruction`` and
``instruction_out`` (the simulator side, ``DiagnosticLIBEROBenchmark``). The generated evaluator
config comes from the shared config writer, which has no such options, so
:func:`with_instruction` appends the two lines to the config's ``params:`` block (the last block of
the generated file) after the writer has run. The benchmark writes the text it actually used to
``instruction_out``; the Job reads that sidecar back and refuses an episode whose text differs from
the one requested (stop reason ``instruction_mismatch``).

The summary is ``language/language_summary.json``. The code that runs in the Job stays Python 3.8
compatible.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from robot_debug import batch_experiment as be
from robot_debug import paraphrase as pp
from robot_debug import scenario_experiment as se
from robot_debug.m6_experiment import ASSUMED_OVERHEAD_SECONDS, DEADLINE_ROUNDING_SECONDS
from robot_debug.decided_gate import run_gates
from robot_debug.scenario_reduce import _Reducer, _Stop, ddmin

LANGUAGE_MODES = ("paraphrase-screen", "paraphrase-reduce")
LANGUAGE_SUITES = ("libero_object", "libero_10", "libero_spatial", "libero_goal")
DEFAULT_SUITE = "libero_object"
SUMMARY_NAME = "language_summary.json"
INSTRUCTION_FILE = "instruction.json"
SUITE_TASK_COUNT = {suite: 10 for suite in LANGUAGE_SUITES}
WORKERS = se.SCENARIO_WORKERS
MAX_START_INDEX = 49
MAX_PARAPHRASES = 12
CONTROL_ATTEMPTS = 2
MAX_CONFIRM_ATTEMPTS = 8
DEFAULT_CONFIRM_ATTEMPTS = 4
MAX_EDITS = 40
DEFAULT_REDUCE_ATTEMPTS = 5
MAX_REDUCE_ATTEMPTS = 8
DEFAULT_REDUCE_CANDIDATES = 24
MAX_REDUCE_CANDIDATES = 60
MAX_REDUCE_CONCURRENCY = 3
DEFAULT_REDUCE_CONCURRENCY = 3
MAX_SCREEN_EPISODES = 600
ORIGINAL_LABEL = "orig"

COMMON_OPTIONAL = {"suite"}
MODE_REQUIRED = {
    "paraphrase-screen": {"task_id", "init_state_index", "original", "paraphrases"},
    "paraphrase-reduce": {"task_id", "init_state_index", "original", "paraphrase", "edits"},
}
MODE_OPTIONAL = {
    "paraphrase-screen": {"attempts", "confirm_attempts", "required_failures"},
    "paraphrase-reduce": {"attempts", "required_failures", "max_candidates", "concurrency"},
}


class LanguageConfigError(ValueError):
    """A paraphrase workload field is out of bounds; the message is a fixed reason."""


def _fail(message: str) -> None:
    raise LanguageConfigError(message)


def _int(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        _fail("{} must be an integer from {} to {}".format(name, low, high))
    return value


def _instruction(value: Any, name: str) -> str:
    """An already clean instruction (1 to 200 printable ASCII characters, single spaces)."""

    try:
        clean = pp.clean_instruction(value)
    except pp.ParaphraseError:
        _fail("{} must be 1 to {} printable ASCII characters".format(name, pp.MAX_CHARS))
    if clean != value or not pp.has_words(clean):
        _fail("{} must be trimmed, single-spaced ASCII text".format(name))
    return clean


def _same(first: str, second: str) -> bool:
    return "".join(first.lower().split()) == "".join(second.lower().split())


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def validate_mode_fields(mode: str, config: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the mode-specific fields (``config`` already has exactly the allowed keys).

    Returns the validated fields with defaults filled in, always including ``suite``.
    """

    suite = config.get("suite", DEFAULT_SUITE)
    if type(suite) is not str or suite not in LANGUAGE_SUITES:
        _fail("suite must be one of {}".format(", ".join(LANGUAGE_SUITES)))
    fields = {"suite": suite}  # type: Dict[str, Any]
    fields["task_id"] = _int(config["task_id"], "task_id", 0, SUITE_TASK_COUNT[suite] - 1)
    fields["init_state_index"] = _int(config["init_state_index"], "init_state_index", 0, MAX_START_INDEX)
    fields["original"] = _instruction(config["original"], "original")
    if mode == "paraphrase-screen":
        paraphrases = config["paraphrases"]
        if type(paraphrases) is not list or not 1 <= len(paraphrases) <= MAX_PARAPHRASES:
            _fail("paraphrases must be a list of 1 to {} instructions".format(MAX_PARAPHRASES))
        seen = [fields["original"]]
        checked = []
        for item in paraphrases:
            text = _instruction(item, "a paraphrase")
            if any(_same(text, other) for other in seen):
                _fail("paraphrases must differ from each other and from the original")
            seen.append(text)
            checked.append(text)
        fields["paraphrases"] = checked
        fields["attempts"] = _int(config.get("attempts", 1), "attempts", 1, 1)
        fields["confirm_attempts"] = _int(
            config.get("confirm_attempts", DEFAULT_CONFIRM_ATTEMPTS), "confirm_attempts", 0, MAX_CONFIRM_ATTEMPTS)
        total = fields["attempts"] + fields["confirm_attempts"]
        fields["required_failures"] = _int(
            config.get("required_failures", min(4, total)), "required_failures", 1, total)
        if fields["confirm_attempts"] and fields["required_failures"] < 2:
            _fail("required_failures must be at least 2 when paraphrases are confirmed")
        if CONTROL_ATTEMPTS + len(checked) * total > MAX_SCREEN_EPISODES:
            _fail("the screen exceeds the episode bound")
    else:
        text = _instruction(config["paraphrase"], "paraphrase")
        if _same(text, fields["original"]):
            _fail("the paraphrase must differ from the original")
        fields["paraphrase"] = text
        try:
            edits = pp.validate_edits(fields["original"], config["edits"])
            rebuilt = pp.apply_edits(fields["original"], edits)
        except pp.ParaphraseError:
            _fail("edits are not valid word edits of the original")
        if not 1 <= len(edits) <= MAX_EDITS:
            _fail("edits must hold 1 to {} word edits".format(MAX_EDITS))
        if pp.tokenize(rebuilt) != pp.tokenize(text):
            _fail("the edits do not turn the original into the paraphrase")
        fields["edits"] = edits
        fields["attempts"] = _int(config.get("attempts", DEFAULT_REDUCE_ATTEMPTS), "attempts", 1,
                                  MAX_REDUCE_ATTEMPTS)
        fields["required_failures"] = _int(
            config.get("required_failures", min(4, fields["attempts"])), "required_failures", 1,
            fields["attempts"])
        fields["max_candidates"] = _int(config.get("max_candidates", DEFAULT_REDUCE_CANDIDATES),
                                        "max_candidates", 1, MAX_REDUCE_CANDIDATES)
        fields["concurrency"] = _int(config.get("concurrency", DEFAULT_REDUCE_CONCURRENCY), "concurrency", 1,
                                     MAX_REDUCE_CONCURRENCY)
    return fields


# ---------------------------------------------------------------------------
# Deadline estimate
# ---------------------------------------------------------------------------


def planned_episodes(mode: str, config: Mapping[str, Any]) -> int:
    """Worst-case valid episodes the mode may run (the warm-up not included)."""

    if mode == "paraphrase-screen":
        total = int(config.get("attempts", 1)) + int(config.get("confirm_attempts", DEFAULT_CONFIRM_ATTEMPTS))
        return CONTROL_ATTEMPTS + len(config["paraphrases"]) * total
    attempts = int(config.get("attempts", DEFAULT_REDUCE_ATTEMPTS))
    return 2 * attempts + int(config.get("max_candidates", DEFAULT_REDUCE_CANDIDATES)) * attempts


def recommended_deadline_seconds(mode: str, config: Mapping[str, Any]) -> int:
    """A Job ``deadline_seconds`` from the scenario timing assumptions.

    The screen is planned for the worst case in which every paraphrase fails its first attempt:
    one wave of first attempts, the confirmation waves, one top-up wave. The reduction is planned
    like the scenario reduction (gate waves plus candidate rounds with the held-fifth-attempt
    factor). Rounded up to whole minutes, never below the 1000 s floor, refused above the 3000 s cap.
    """

    if mode == "paraphrase-screen":
        first = CONTROL_ATTEMPTS + len(config["paraphrases"]) * int(config.get("attempts", 1))
        confirm = len(config["paraphrases"]) * int(config.get("confirm_attempts", DEFAULT_CONFIRM_ATTEMPTS))
        work = (se._waves(first) + se._waves(confirm) + 1) * se.ASSUMED_FAILING_EPISODE_SECONDS
    elif mode == "paraphrase-reduce":
        rounds = int(math.ceil(int(config.get("max_candidates", DEFAULT_REDUCE_CANDIDATES))
                               / float(config.get("concurrency", DEFAULT_REDUCE_CONCURRENCY))))
        work = ((se.REDUCE_GATE_WAVES + rounds) * se.ASSUMED_REDUCE_ROUND_SECONDS
                * se.ASSUMED_HELD_FIFTH_FACTOR)
    else:
        raise ValueError("unsupported language mode")
    total = (sum(ASSUMED_OVERHEAD_SECONDS.values()) + work + be.ITEM_TIMEOUT_SECONDS
             + se.ASSUMED_FAILING_EPISODE_SECONDS)
    rounded = int(max(se.MIN_DEADLINE_SECONDS, math.ceil(total / DEADLINE_ROUNDING_SECONDS)
                      * DEADLINE_ROUNDING_SECONDS))
    if rounded > se.MAX_DEADLINE_SECONDS:
        raise ValueError("this workload needs more than the {} s cap; shrink it".format(
            se.MAX_DEADLINE_SECONDS))
    return rounded


# ---------------------------------------------------------------------------
# Passing the instruction to the benchmark
# ---------------------------------------------------------------------------


def with_instruction(config_path: Path, instruction: str, instruction_out: Path) -> None:
    """Append the benchmark options ``instruction`` and ``instruction_out`` to a generated config.

    The shared config writer ends the file with the benchmark's ``params:`` block (indented six
    spaces); the two lines are added to that block. Refuses a file whose shape is not that.
    """

    text = Path(config_path).read_text(encoding="utf-8")
    lines = text.rstrip("\n").split("\n")
    if "    params:" not in lines or not lines[-1].startswith("      ") or "\r" in text:
        raise ValueError("the generated config does not end with a params block")
    if any(line.startswith("      instruction") for line in lines):
        raise ValueError("the generated config already has an instruction")
    lines.append("      instruction: {}".format(json.dumps(instruction, ensure_ascii=True)))
    lines.append("      instruction_out: {}".format(json.dumps(str(instruction_out), ensure_ascii=True)))
    Path(config_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_instruction_sidecar(path: Path) -> str:
    """The ``instruction_used`` of the sidecar the benchmark wrote (a record, or a list of one record)."""

    data = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=se._reject_constant)
    if isinstance(data, list):
        if len(data) != 1:
            raise ValueError("the instruction sidecar must hold exactly one record")
        data = data[0]
    if not isinstance(data, dict) or type(data.get("instruction_used")) is not str:
        raise ValueError("the instruction sidecar has no instruction_used")
    return data["instruction_used"]


def read_task_language(path: Path) -> Optional[str]:
    """The task's own instruction the benchmark recorded beside the override (``None`` if absent)."""

    data = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=se._reject_constant)
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    value = data.get("task_language") if isinstance(data, dict) else None
    return value if type(value) is str else None


def same_wording(a: Optional[str], b: Optional[str]) -> bool:
    """Whether two instructions are the same wording, ignoring case and spacing."""

    if a is None or b is None:
        return False
    return " ".join(a.lower().split()) == " ".join(b.lower().split())


class InstructionChannel:
    """Wraps the shared config writer and evidence reader so each episode carries its instruction.

    ``write_config`` takes the item's ``instruction`` out of the keyword arguments, lets the shared
    writer produce the config, appends the benchmark options and remembers the request. ``read`` reads
    the evidence and the sidecar and refuses an episode whose instruction differs from the request.
    """

    def __init__(self, write_config: Callable[..., None]) -> None:
        self._write_config = write_config
        self.requested = {}  # type: Dict[str, str]
        self.mismatches = []  # type: List[str]
        self._lock = threading.Lock()

    def write_config(self, **kwargs: Any) -> None:
        instruction = kwargs.pop("instruction")
        output = Path(kwargs["output_dir"])
        self._write_config(**kwargs)
        with_instruction(kwargs["config_path"], instruction, output / INSTRUCTION_FILE)
        with self._lock:
            self.requested[output.name] = instruction

    def read(self, output_dir: Path, batch_root: Path) -> Dict[str, Any]:
        evidence = se.read_evidence(output_dir, batch_root)
        name = Path(output_dir).name
        sidecar = Path(output_dir) / INSTRUCTION_FILE
        used = read_instruction_sidecar(sidecar)
        with self._lock:
            wanted = self.requested.get(name)
        if wanted is None or used != wanted:
            with self._lock:
                self.mismatches.append(name)
            raise ValueError("the policy did not receive the requested instruction")
        evidence["instruction"] = used
        evidence["task_language"] = read_task_language(sidecar)
        return evidence


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _attempt_summary(record: Mapping[str, Any]) -> Dict[str, Any]:
    seconds = None
    if isinstance(record.get("ended_seconds"), (int, float)) and isinstance(record.get("started_seconds"), (int, float)):
        seconds = round(record["ended_seconds"] - record["started_seconds"], 3)
    return {"case_id": record["case_id"], "attempt": record.get("attempt"), "outcome": record["outcome"],
            "steps": record.get("steps"), "video": (record.get("artifacts") or {}).get("video"),
            "instruction_used": record.get("instruction"), "task_language": record.get("task_language"),
            "seconds": seconds}


# ---- screen -------------------------------------------------------------------------


class ParaphraseScreenDriver:
    mode = "paraphrase-screen"

    def __init__(self, config: Mapping[str, Any], suite: str, batch_root: Path) -> None:
        self.config, self.suite, self.batch_root = config, suite, Path(batch_root)
        self.task_id, self.start = config["task_id"], config["init_state_index"]
        self.attempts = config["attempts"]
        self.confirm = config["confirm_attempts"]
        self.required = config["required_failures"]
        self.original = config["original"]
        self.instructions = [(ORIGINAL_LABEL, self.original)] + [
            ("p{:02d}".format(number), text) for number, text in enumerate(config["paraphrases"], 1)]
        self.texts = dict(self.instructions)
        self.records = {label: [] for label, _ in self.instructions}  # type: Dict[str, List[Dict[str, Any]]]
        self.decisions = {}  # type: Dict[str, Optional[str]]
        self.skipped = {}  # type: Dict[str, int]
        self.body = {"task_id": self.task_id, "init_state_index": self.start, "original": self.original,
                     "control": None, "instructions": [], "reproducing": [], "phase1": None,
                     "confirm": None, "topup": None}  # type: Dict[str, Any]

    def _item(self, label: str, attempt: int, phase: str) -> Dict[str, Any]:
        """Attempt number ``attempt`` (0-based) of the instruction ``label``."""

        return se._item("{}-a{:02d}".format(label, attempt + 1), "language",
                        {"task_id": self.task_id, "init_state_index": self.start,
                         "instruction": self.texts[label]},
                        None, label=label, attempt=attempt + 1, phase=phase, text=self.texts[label])

    def warmup_item(self) -> Dict[str, Any]:
        return self._item(ORIGINAL_LABEL, 0, "warmup")

    def run(self, ctx: Any) -> Optional[str]:
        first = [self._item(ORIGINAL_LABEL, number, "control") for number in range(CONTROL_ATTEMPTS)]
        for label, _ in self.instructions[1:]:
            first += [self._item(label, number, "screen") for number in range(self.attempts)]
        records = se._run_records(ctx, first)
        self._absorb(records)
        reason = ctx.stop_reason(records)
        self.body["phase1"] = {"episodes": len(first), "valid": sum(r["status"] == "valid" for r in records)}
        ctx.progress("paraphrase_screen_phase1_done", **self.body["phase1"])
        if reason is not None or not self.confirm:
            return reason
        failing = [label for label, _ in self.instructions[1:]
                   if any(r["outcome"] == "policy_failure" for r in self.records[label] if r["status"] == "valid")]
        candidates = [{"key": label, "item": {"label": label}, "kind": "failure"} for label in failing]
        need = max(1, self.required - self.attempts)

        def make_item(spec: Dict[str, Any]) -> Dict[str, Any]:
            return self._item(spec["label"], self.attempts + spec["attempt"], "confirm")

        executor = se.PoolExecutor(ctx.pool, make_item)
        run = run_gates(executor, candidates, attempts=self.confirm, required_failures=need,
                        max_in_flight=ctx.workers, remaining=ctx.remaining, drain=True)
        for candidate in candidates:
            key = candidate["key"]
            self._absorb(run.records[key])
            self.decisions[key] = run.decisions[key]
            self.skipped[key] = run.skipped[key]
        self.body["confirm"] = {"paraphrases": len(candidates), "decisions": dict(run.decisions),
                                "skipped_attempts": run.skipped_total, "stop": run.stop}
        ctx.progress("paraphrase_screen_confirm_done", **self.body["confirm"])
        if run.stop is not None:
            return ctx.failure() or run.stop
        extra = []
        total = self.attempts + self.confirm
        for label in failing:
            if self.decisions.get(label) != "reproduces":
                continue
            done = {r["attempt"] for r in self.records[label] if r["status"] == "valid"}
            extra += [self._item(label, number - 1, "topup") for number in range(1, total + 1) if number not in done]
        topup = se._run_records(ctx, extra) if extra else []
        self._absorb(topup)
        self.body["topup"] = {"episodes": len(extra)}
        return ctx.stop_reason(topup)

    def _absorb(self, records: Sequence[Mapping[str, Any]]) -> None:
        for record in records:
            if record.get("label") in self.records and record.get("status") == "valid":
                self.records[record["label"]].append(dict(record))

    # -- summary ----------------------------------------------------------------------

    def finish(self, stop_reason: Optional[str], records: Sequence[Mapping[str, Any]]) -> None:
        rows = []
        for label, text in self.instructions:
            ordered = sorted(self.records[label], key=lambda r: r["attempt"])
            outcomes = [r["outcome"] for r in ordered]
            row = {
                "label": label, "kind": "original" if label == ORIGINAL_LABEL else "paraphrase", "text": text,
                "outcomes": outcomes, "failures": outcomes.count("policy_failure"),
                "decision": self.decisions.get(label), "skipped_attempts": self.skipped.get(label, 0),
                "edit_count": None if label == ORIGINAL_LABEL else len(pp.word_edits(self.original, text)),
                "attempts": [_attempt_summary(r) for r in ordered],
            }
            rows.append(row)
        control = rows[0]
        self.body["instructions"] = rows
        languages = [a.get("task_language") for a in control["attempts"] if a.get("task_language")]
        task_language = languages[0] if languages else None
        self.body["control"] = {"outcomes": control["outcomes"], "attempts": CONTROL_ATTEMPTS,
                                "passed": len(control["outcomes"]) == CONTROL_ATTEMPTS
                                and all(item == "success" for item in control["outcomes"]),
                                # The spec's "original" must be the task's own wording, or a typo would
                                # turn the control into a paraphrase (October 15 review).
                                "task_language": task_language,
                                "original_matches_task": None if task_language is None
                                else same_wording(self.original, task_language)}
        reproducing = [row for row in rows[1:] if row["decision"] == "reproduces"]
        reproducing.sort(key=lambda row: (-row["failures"], row["edit_count"], row["label"]))
        self.body["reproducing"] = [row["label"] for row in reproducing]
        self.body["reproducing_paraphrases"] = [
            {"label": row["label"], "text": row["text"], "failures": row["failures"],
             "outcomes": row["outcomes"], "edit_count": row["edit_count"]} for row in reproducing]

    def complete(self, stop_reason: Optional[str]) -> bool:
        got = all(self.records[label] for label, _ in self.instructions)
        return stop_reason is None and got and len(self.records[ORIGINAL_LABEL]) == CONTROL_ATTEMPTS


# ---- reduce ---------------------------------------------------------------------------


def run_paraphrase_reduction(
    executor: Any,
    prepare: Callable[[Dict[str, Any]], Tuple[str, Dict[str, Any]]],
    edit_ids: Sequence[int],
    *,
    attempts: int = DEFAULT_REDUCE_ATTEMPTS,
    required_failures: int = 4,
    max_candidates: int = DEFAULT_REDUCE_CANDIDATES,
    concurrency: int = DEFAULT_REDUCE_CONCURRENCY,
    max_in_flight: Optional[int] = None,
    remaining: Optional[Callable[[], Optional[float]]] = None,
    wait_timeout: float = 5.0,
) -> Dict[str, Any]:
    """Delta debugging over the word edits between an original instruction and a failing paraphrase.

    ``prepare(spec) -> (key, item)`` describes a candidate (``key`` caches by instruction text):
    ``{"role": "reference"}`` is the original wording, ``{"role": "failing"}`` the full paraphrase
    and ``{"role": "hybrid", "selection": [edit ids]}`` the original with those edits applied.
    The original must pass ``attempts`` of ``attempts`` and the full paraphrase must reproduce
    (``required_failures`` of ``attempts``); then ddmin over ``edit_ids`` (the empty set is the
    passing original and is never offered). ``max_candidates`` bounds the hybrid candidates run
    (cached ones are free). Returns a JSON-clean record with stop reasons ``reduced``,
    ``failing_not_reproducible``, ``reference_not_passing``, ``budget_exhausted``,
    ``deadline_exhausted`` and ``infrastructure_error``.
    """

    ids = list(edit_ids)
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("edit_ids must be a non-empty list of distinct ids")
    reducer = _Reducer(executor, prepare, attempts=attempts, required_failures=required_failures,
                       max_candidates=max_candidates, concurrency=concurrency, max_in_flight=max_in_flight,
                       remaining=remaining, wait_timeout=wait_timeout)
    result = {
        "stop_reason": None, "reduced": False, "error": None, "note": None, "attempts": attempts,
        "required_failures": required_failures, "max_candidates": max_candidates, "concurrency": concurrency,
        "edit_ids": list(ids), "final_edits": None, "final_candidate": None, "gates": None,
    }  # type: Dict[str, Any]
    state = {"current": None}  # type: Dict[str, Any]
    try:
        _reduce(reducer, ids, result, state)
        result["stop_reason"] = "reduced"
        result["reduced"] = True
    except _Stop as stop:
        result["stop_reason"] = stop.reason
        if stop.reason == "infrastructure_error":
            result["error"] = stop.detail
        if stop.reason == "failing_not_reproducible":
            result["note"] = stop.detail
    try:
        reducer.finish_late()
    except Exception:  # noqa: BLE001 - late records are best effort
        pass
    current = state["current"]
    if current is not None:
        result["final_edits"] = sorted(current)
        key, _ = reducer.prepare({"role": "hybrid", "selection": sorted(current)})
        record = reducer.cache.get("failure:" + key)
        if record is not None and record["gate_met"]:
            result["final_candidate"] = record["index"]
    result["candidates"] = reducer.candidates
    hybrids = [c for c in reducer.candidates if c["role"] == "hybrid"]
    gates = [c for c in reducer.candidates if c["role"] != "hybrid"]

    def run_count(group: Sequence[Mapping[str, Any]]) -> int:
        return sum(len(c["outcomes"]) + len(c["late_outcomes"]) for c in group)

    result["candidates_tested"] = len(hybrids)
    result["attempts_run_gates"] = run_count(gates)
    result["attempts_run_hybrid"] = run_count(hybrids)
    result["attempts_run"] = result["attempts_run_gates"] + result["attempts_run_hybrid"]
    result["attempts_skipped"] = sum(c["skipped"] for c in reducer.candidates)
    result["attempts_stop_withdrawn"] = sum(c["stop_withdrawn"] for c in reducer.candidates)
    return result


def _reduce(reducer: _Reducer, ids: List[int], result: Dict[str, Any], state: Dict[str, Any]) -> None:
    reducer.phase = "gate"
    failing_record, reference_record = reducer.evaluate([{"role": "failing"}, {"role": "reference"}], batch=2)
    result["gates"] = {"paraphrase": failing_record["decision"], "original": reference_record["decision"]}
    if not failing_record["gate_met"]:
        raise _Stop("failing_not_reproducible", "full_paraphrase_" + str(failing_record["decision"]))
    if not reference_record["gate_met"]:
        raise _Stop("reference_not_passing")
    state["current"] = list(ids)
    reducer.phase = "ddmin"

    def find_first(sets: List[List[int]]) -> Optional[int]:
        return reducer.first_reproducing([{"role": "hybrid", "selection": sorted(chosen)} for chosen in sets])

    def track(sets: List[List[int]]) -> Optional[int]:
        index = find_first(sets)
        if index is not None:
            state["current"] = list(sets[index])
        return index

    if len(ids) >= 2:
        ddmin(ids, track)


class ParaphraseReduceDriver:
    mode = "paraphrase-reduce"

    def __init__(self, config: Mapping[str, Any], suite: str, batch_root: Path) -> None:
        self.config, self.suite, self.batch_root = config, suite, Path(batch_root)
        self.task_id, self.start = config["task_id"], config["init_state_index"]
        self.original, self.paraphrase = config["original"], config["paraphrase"]
        self.edits = [dict(edit) for edit in config["edits"]]
        self.by_id = {edit["id"]: edit for edit in self.edits}
        self.texts = {}  # type: Dict[str, str]
        self.body = {}  # type: Dict[str, Any]
        self._memo = {}  # type: Dict[str, Tuple[str, Dict[str, Any]]]

    def text_for(self, ids: Sequence[int]) -> str:
        """The instruction with the given edits applied (none: the original, all: the paraphrase)."""

        if not ids:
            return self.original
        if len(ids) == len(self.edits):
            return self.paraphrase
        return pp.apply_edits(self.original, [self.by_id[i] for i in sorted(ids)])

    def prepare(self, spec: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
        role = spec["role"]
        memo_key = json.dumps(spec, sort_keys=True, default=str)
        if memo_key in self._memo:
            key, item = self._memo[memo_key]
            return key, copy.deepcopy(item)
        if role == "reference":
            text, prefix = self.original, "orig"
        elif role == "failing":
            text, prefix = self.paraphrase, "full"
        elif role == "hybrid":
            text, prefix = self.text_for(list(spec["selection"])), "cand"
        else:
            raise ValueError("unknown candidate role")
        if len(text) > pp.MAX_CHARS:
            raise _Stop("infrastructure_error", "candidate_too_long")
        key = _text_hash(text)
        self.texts[key] = text
        item = se._item("{}-{}".format(prefix, key[:12]), "reduce-" + role,
                        {"task_id": self.task_id, "init_state_index": self.start, "instruction": text},
                        None, role=role, key=key, text=text)
        self._memo[memo_key] = (key, item)
        return key, copy.deepcopy(item)

    def warmup_item(self) -> Dict[str, Any]:
        return self.prepare({"role": "reference"})[1]

    def run(self, ctx: Any) -> Optional[str]:
        executor = se.PoolExecutor(ctx.pool, se.ReduceDriver.attempt_item)
        result = run_paraphrase_reduction(
            executor, self.prepare, [edit["id"] for edit in self.edits], attempts=self.config["attempts"],
            required_failures=self.config["required_failures"], max_candidates=self.config["max_candidates"],
            concurrency=self.config["concurrency"], max_in_flight=ctx.workers, remaining=ctx.remaining)
        self.body["reduction"] = result
        ctx.progress("paraphrase_reduce_done", stop_reason=result["stop_reason"],
                     candidates=result.get("candidates_tested"), skipped=result.get("attempts_skipped"))
        reason = result["stop_reason"]
        if reason == "reduced":
            return None
        if reason in ("failing_not_reproducible", "reference_not_passing"):
            return reason
        return ctx.failure() or reason

    def finish(self, stop_reason: Optional[str], records: Sequence[Mapping[str, Any]]) -> None:
        result = self.body.get("reduction")
        self.body.update(task_id=self.task_id, init_state_index=self.start, original=self.original,
                         paraphrase=self.paraphrase, edits=copy.deepcopy(self.edits), minimal=None, videos={})
        if result is None:
            return
        by_index = {c["index"]: c for c in result.get("candidates") or []}
        for candidate in by_index.values():
            candidate["text"] = self.texts.get(candidate["key"])

        def video(role: str, candidate: Optional[Mapping[str, Any]], outcome: str) -> None:
            if candidate is None:
                return
            record = se._first_valid(records, key=candidate["key"], outcome=outcome)
            if record is not None:
                self.body["videos"][role] = {
                    "case_id": record["case_id"], "outcome": record["outcome"],
                    "video": (record.get("artifacts") or {}).get("video"), "key": candidate["key"],
                    "text": candidate["text"]}

        candidates = list(by_index.values())
        # Roles follow the scenario case: "original" is the failure being explained (the full
        # paraphrase), "reference" the passing baseline (the original wording), "minimal" the result.
        video("original", next((c for c in candidates if c["role"] == "failing"), None), "policy_failure")
        video("reference", next((c for c in candidates if c["role"] == "reference" and c["gate_met"]), None),
              "success")
        final = by_index.get(result.get("final_candidate"))
        if final is not None:
            video("minimal", final, "policy_failure")
        edits = result.get("final_edits")
        if edits:
            kept = [self.by_id[i] for i in edits]
            self.body["minimal"] = {
                "edit_ids": list(edits), "edits": copy.deepcopy(kept), "text": self.text_for(edits),
                "labels": [pp.edit_label(edit) for edit in kept], "verified": final is not None,
                "edit_minimal": bool(result.get("reduced"))}

    def complete(self, stop_reason: Optional[str]) -> bool:
        result = self.body.get("reduction") or {}
        return stop_reason is None and bool(result.get("reduced"))


DRIVERS = {"paraphrase-screen": ParaphraseScreenDriver, "paraphrase-reduce": ParaphraseReduceDriver}


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

_BIG_CONFIG_KEYS = ("original", "paraphrase", "paraphrases", "edits")


def _config_echo(config: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in config.items() if key not in _BIG_CONFIG_KEYS}


def write_summary(root: Path, summary: Mapping[str, Any]) -> None:
    target = Path(root) / SUMMARY_NAME
    temporary = Path(root) / ("." + SUMMARY_NAME + ".tmp")
    payload = json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary.write_bytes(payload.encode("utf-8"))
    os.replace(str(temporary), str(target))


def run_language(
    *,
    mode: str,
    config: Mapping[str, Any],
    batch_root: Path,
    log_root: Path,
    project_root: Path,
    model_factory: Callable[..., Any],
    set_model: Callable[[Any], None],
    run_item: Callable[..., Any],
    failure: Callable[[], Optional[str]],
    remaining: Callable[[], float],
    launch_deadline: float,
    clock: Callable[[], float] = time.monotonic,
    progress: Callable[..., None] = lambda _event, **_fields: None,
    write_config: Optional[Callable[..., None]] = None,
    load_result: Optional[Callable[[Path], Any]] = None,
    item_timeout: float = be.ITEM_TIMEOUT_SECONDS,
    prefetch: Optional[Callable[[], Any]] = None,
    snapshot: Callable[[], Mapping[str, Any]] = be.memory_snapshot,
    server_clock: Callable[[], float] = time.monotonic,
    workers: int = WORKERS,
) -> Dict[str, Any]:
    """Run one paraphrase mode against a single freshly started 12-worker server; returns the summary.

    ``config`` is the validated mode configuration. The injected ``run_item``, ``failure`` and
    ``remaining`` are the bounded runner and latch from ``run_workload``.
    """

    if mode not in LANGUAGE_MODES:
        raise ValueError("unsupported language mode")
    if write_config is None or load_result is None:
        from scripts import run_failure_search

        write_config = write_config or run_failure_search._write_config
        load_result = load_result or (
            lambda output: run_failure_search._load_stage_results(output, expected_count=1)[0])
    channel = InstructionChannel(write_config)
    raw_progress = progress
    progress_lock = threading.Lock()

    def progress(event: str, **fields: Any) -> None:  # noqa: F811 - serialised copy of the argument
        with progress_lock:
            raw_progress(event, **fields)

    batch_root = Path(batch_root)
    batch_root.mkdir(parents=True, exist_ok=True)
    configs, runs = batch_root / "configs", batch_root / "runs"
    configs.mkdir(exist_ok=True)
    runs.mkdir(exist_ok=True)
    timing_path = batch_root / "server-timing.jsonl"
    suite = config["suite"]
    driver = DRIVERS[mode](config, suite, batch_root)
    extra = {"prefetch_seconds": None, "cleanup_unconfirmed": False}  # type: Dict[str, Any]
    state = {
        "stop_reason": None, "warmup": None, "server_argv": None, "memory_start": None,
        "memory_end": None, "timing": None, "startup_seconds": None, "total_seconds": None,
        "warm_elapsed_seconds": None, "records": [], "not_started": {}, "checkpoint": None,
    }  # type: Dict[str, Any]
    started_at = clock()
    scrub = {"companions_removed": 0}

    def build() -> Dict[str, Any]:
        records = sorted(state["records"], key=lambda r: r["case_id"])
        summary = {
            "schema_version": 1, "mode": mode, "suite": suite, "workers": workers,
            "checkpoint": state["checkpoint"],
            "max_batch_size": se.SCENARIO_MAX_BATCH_SIZE, "config": _config_echo(config),
            "stop_reason": state["stop_reason"],
            "complete": driver.complete(state["stop_reason"]),
            "attempted": len([r for r in records if r.get("started", True)]),
            "valid_count": len([r for r in records if r["status"] == "valid"]),
            "outcomes": se._count_outcomes(records),
            "warmup": state["warmup"], "server_argv": state["server_argv"],
            "memory_start": state["memory_start"], "memory_end": state["memory_end"],
            "timing": state["timing"], "startup_seconds": state["startup_seconds"],
            "warm_elapsed_seconds": state["warm_elapsed_seconds"], "total_seconds": state["total_seconds"],
            "not_started": dict(state["not_started"]),
            "instruction_mismatches": sorted(channel.mismatches),
            "sqlite_companions_removed": scrub["companions_removed"], "items": records,
        }  # type: Dict[str, Any]
        summary.update(driver.body)
        summary.update(extra)
        return summary

    def save() -> Dict[str, Any]:
        summary = build()
        write_summary(batch_root, summary)
        return summary

    cancel = threading.Event()
    pool = None  # type: Optional[se.ScenarioPool]
    launch_t = None  # type: Optional[float]
    try:
        if be.run_prefetch(prefetch, clock, progress, extra):
            state["stop_reason"] = "prefetch_failed"
        else:
            state["memory_start"] = dict(snapshot())
            progress("language_start", mode=mode, suite=suite, workers=workers, **dict(state["memory_start"]))
            phase_started = clock()
            try:
                with be.started_server(
                    model_factory=model_factory, set_model=set_model, log_root=log_root,
                    max_batch_size=se.SCENARIO_MAX_BATCH_SIZE, timing_log=timing_path,
                    launch_deadline=launch_deadline,
                ) as (_model, server_argv):
                    state["server_argv"] = server_argv
                    ready_at = clock()
                    state["startup_seconds"] = be._round(ready_at - phase_started)
                    evaluate = se.make_scenario_evaluate(
                        suite=suite, project_root=project_root, write_config=channel.write_config,
                        load_result=load_result, run_item=run_item, cancel=cancel,
                        item_timeout=item_timeout, clock=clock, ready_at=ready_at,
                        configs_dir=configs, runs_dir=runs, batch_root=batch_root,
                        stage_prefix="lang-", read=channel.read)
                    pool = se.ScenarioPool(workers=workers, evaluate=evaluate, remaining=remaining,
                                           item_timeout=item_timeout, cancel=cancel)
                    try:
                        warm, _warm_seconds, skipped = be.run_warmup(
                            evaluate=evaluate, first=driver.warmup_item(), batch_root=batch_root,
                            remaining=remaining, item_timeout=item_timeout, clock=clock,
                            known_outcomes={})
                        state["warmup"] = warm
                        progress("language_warmup_done", status=warm.get("status"),
                                 outcome=warm.get("outcome"), duration_seconds=warm.get("duration_seconds"))
                        if skipped:
                            state["stop_reason"] = "deadline_exhausted"
                        elif warm["status"] != "valid":
                            state["stop_reason"] = failure() or "warmup_failed"
                            cancel.set()
                        if state["stop_reason"] is None:
                            launch_t = server_clock()
                            pool.start()
                            ctx = se._Context(pool=pool, failure=failure, remaining=remaining,
                                              progress=progress, batch_root=batch_root, suite=suite,
                                              workers=workers)
                            state["stop_reason"] = driver.run(ctx)
                    except BaseException:
                        cancel.set()          # evaluators die before the server does
                        raise
                    finally:
                        pool.shutdown()
            except be.PhaseFailure as error:
                state["stop_reason"] = error.reason
            state["memory_end"] = dict(snapshot())
    except BaseException:
        cancel.set()
        raise
    finally:
        if pool is not None:
            state["records"] = list(pool.results)
            state["not_started"] = pool.not_started_counts()
        if channel.mismatches and state["stop_reason"] in (None, "infrastructure_error", "phase_incomplete"):
            state["stop_reason"] = "instruction_mismatch"
        for entry in state["records"]:
            if entry["status"] in ("cancelled", "timed_out") and entry.get("started", True):
                entry["run_dir_removed"] = be.remove_tree_within(runs / entry["case_id"], batch_root)
        scrub["companions_removed"] += be.purge_sqlite_companions(batch_root)
        state["total_seconds"] = be._round(clock() - started_at)
        finished = [r for r in state["records"] if r.get("ended_seconds") is not None]
        if finished:
            warm_elapsed = max(r["ended_seconds"] for r in finished) - min(r["started_seconds"] for r in finished)
            state["warm_elapsed_seconds"] = be._round(max(warm_elapsed, 1e-6))
            if launch_t is not None:
                state["timing"] = be.timing_stats(timing_path, state["warm_elapsed_seconds"], min_t=launch_t)
        state["checkpoint"] = se.checkpoint_record(suite, batch_root.parent, config.get("checkpoint_id"))
        driver.finish(state["stop_reason"], state["records"])
        summary = save()
    progress("language_summary", mode=mode, stop_reason=summary["stop_reason"],
             complete=summary["complete"], valid=summary["valid_count"], outcomes=summary["outcomes"])
    return summary


# ---------------------------------------------------------------------------
# Workloads (built on the workstation)
# ---------------------------------------------------------------------------


def build_screen_workload(*, run_id: str, suite: str, task_id: int, start: int, original: str,
                          paraphrases: Sequence[str], confirm_attempts: int = DEFAULT_CONFIRM_ATTEMPTS,
                          deadline_seconds: Optional[int] = None) -> Dict[str, Any]:
    """The ``paraphrase-screen`` workload JSON (the Token Factory key is never part of it)."""

    workload = {
        "schema_version": 1, "mode": "paraphrase-screen", "run_id": run_id, "suite": suite,
        "task_id": task_id, "init_state_index": start, "original": original,
        "paraphrases": list(paraphrases), "attempts": 1, "confirm_attempts": confirm_attempts,
    }  # type: Dict[str, Any]
    if deadline_seconds is None:
        deadline_seconds = recommended_deadline_seconds("paraphrase-screen", workload)
    workload["deadline_seconds"] = deadline_seconds
    return workload


def build_reduce_workload(*, run_id: str, suite: str, task_id: int, start: int, original: str,
                          paraphrase: str, max_candidates: int = DEFAULT_REDUCE_CANDIDATES,
                          deadline_seconds: Optional[int] = None) -> Dict[str, Any]:
    """The ``paraphrase-reduce`` workload JSON for a paraphrase that reproduced in the screen."""

    workload = {
        "schema_version": 1, "mode": "paraphrase-reduce", "run_id": run_id, "suite": suite,
        "task_id": task_id, "init_state_index": start, "original": original, "paraphrase": paraphrase,
        "edits": pp.word_edits(original, paraphrase), "max_candidates": max_candidates,
    }  # type: Dict[str, Any]
    if deadline_seconds is None:
        deadline_seconds = recommended_deadline_seconds("paraphrase-reduce", workload)
    workload["deadline_seconds"] = deadline_seconds
    return workload


# ---------------------------------------------------------------------------
# The reduced wording as a case
# ---------------------------------------------------------------------------

CASE_SCHEMA_VERSION = 1
MAX_CASE_EVIDENCE = 30


def describe_minimal_wording(original: str, text: str, labels: Sequence[str], *, reduced: bool,
                             required_failures: int = 4, attempts: int = 5) -> str:
    """The minimal wording change in one plain sentence."""

    if not labels:
        return "No smaller wording change than the whole paraphrase was established."
    if len(labels) > 1:
        body = "; ".join(labels[:-1]) + " and " + labels[-1]
    else:
        body = labels[0]
    sentence = ('Changing the wording of "{}" as follows is enough to make the policy fail: {} '
                '(giving "{}"; at least {} of {} attempts); the original wording passed {} of {}'.format(
                    original, body, text, required_failures, attempts, attempts, attempts))
    if not reduced:
        sentence += "; the reduction stopped early, so this is the smallest wording change found so far"
    return sentence + "."


def build_case(summary: Mapping[str, Any], screen: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """A portable case record for a ``paraphrase-reduce`` summary (and, optionally, its screen).

    Holds the original and the minimal wording, the edits that matter, the replay recipe (the
    instruction text to give the benchmark), the three video references and the candidates a reader
    needs. Raises ``ValueError`` for anything but a ``paraphrase-reduce`` summary with a verified
    reduced wording.
    """

    if not isinstance(summary, Mapping) or summary.get("mode") != "paraphrase-reduce":
        raise ValueError("a paraphrase-reduce summary is required")
    reduction = summary.get("reduction") or {}
    minimal = summary.get("minimal")
    if not isinstance(minimal, Mapping) or not minimal.get("verified"):
        raise ValueError("the summary has no verified wording")
    reduced = bool(reduction.get("reduced"))
    identity = json.dumps({"suite": summary["suite"], "task_id": summary["task_id"],
                           "start": summary["init_state_index"], "original": summary["original"],
                           "minimal": minimal["text"]}, sort_keys=True, separators=(",", ":"))
    evidence = []
    for candidate in reduction.get("candidates") or []:
        if len(evidence) >= MAX_CASE_EVIDENCE:
            break
        evidence.append({"index": candidate["index"], "phase": candidate.get("phase"),
                         "role": candidate.get("role"), "edits": copy.deepcopy(candidate.get("selection")),
                         "text": candidate.get("text"), "outcomes": list(candidate.get("outcomes") or []),
                         "decision": candidate.get("decision")})
    screen_rows = []
    for row in (screen or {}).get("instructions") or []:
        entry = {key: row.get(key) for key in (
            "label", "kind", "text", "outcomes", "failures", "decision", "edit_count")}
        entry["meaning_check"] = (pp.meaning_check(summary["original"], row["text"])
                                  if row.get("kind") == "paraphrase" and type(row.get("text")) is str else None)
        screen_rows.append(entry)
    return {
        "schema_version": CASE_SCHEMA_VERSION,
        "kind": "paraphrase_reduction",
        "case_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "suite": summary["suite"],
        "checkpoint": copy.deepcopy(summary.get("checkpoint")),
        "task_id": summary["task_id"],
        "start_index": summary["init_state_index"],
        "instruction": summary["original"],
        "paraphrase": summary["paraphrase"],
        "paraphrase_meaning_check": pp.meaning_check(summary["original"], summary["paraphrase"]),
        "stop_reason": reduction.get("stop_reason"),
        "reduced": reduced,
        "minimal": {
            "text": minimal["text"], "edits": copy.deepcopy(minimal["edits"]),
            "edit_ids": list(minimal["edit_ids"]), "labels": list(minimal["labels"]),
            "edits_total": len(summary.get("edits") or []),
            "sentence": describe_minimal_wording(
                summary["original"], minimal["text"], minimal["labels"], reduced=reduced,
                required_failures=reduction.get("required_failures", 4), attempts=reduction.get("attempts", 5)),
            "edit_minimal": bool(minimal.get("edit_minimal")),
            "meaning_check": pp.meaning_check(summary["original"], minimal["text"]),
        },
        "replay": {
            "config": {"suite": summary["suite"], "task_id": summary["task_id"],
                       "init_state_index": summary["init_state_index"], "instruction": minimal["text"]},
            "reference_instruction": summary["original"],
            "gate": {"attempts": reduction.get("attempts", 5),
                     "required_failures": reduction.get("required_failures", 4)},
        },
        "videos": copy.deepcopy(summary.get("videos") or {}),
        "screen": screen_rows,
        "evidence": evidence,
        "explanation": None,
        "measurements": {
            "candidates_tested": reduction.get("candidates_tested"),
            "attempts_run": reduction.get("attempts_run"),
            "attempts_skipped": reduction.get("attempts_skipped"),
            "total_seconds": summary.get("total_seconds"),
        },
    }


__all__ = [
    "DEFAULT_SUITE", "InstructionChannel", "LANGUAGE_MODES", "LANGUAGE_SUITES", "LanguageConfigError",
    "ParaphraseReduceDriver", "ParaphraseScreenDriver", "SUMMARY_NAME", "build_case",
    "build_reduce_workload", "build_screen_workload", "describe_minimal_wording", "planned_episodes",
    "read_instruction_sidecar", "recommended_deadline_seconds", "run_language",
    "run_paraphrase_reduction", "validate_mode_fields", "with_instruction",
]
