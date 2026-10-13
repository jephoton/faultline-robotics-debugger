"""Job modes for LIBERO-10 scenario screening and reduction (ADR 0028, plan 2026-10-13).

Three Serverless modes share the M3/M6 machinery in :mod:`robot_debug.batch_experiment`
(one prefetch, one faultline server with ``max_batch_size = 12``, an untimed warm-up,
concurrent single-episode evaluators, the SQLite scrub and the closed-evidence export)
and one pool of 12 evaluator workers:

``scenario-smoke``
    Shows that the suite checkpoint loads, benchmark starts are selectable and
    exportable, a hybrid of two starts restores with matching hashes, and an
    overlapping start is detected as ``invalid_scene``.

``scenario-screen``
    One unperturbed attempt per (task, start), then every start that failed gets
    confirmation attempts through the early-decided 4-of-5 gate. The summary has
    the shape ``scripts/plan_scenario_reduction.py`` reads.

``scenario-reduce``
    Runs :func:`robot_debug.scenario_reduce.run_scenario_reduction` for one failing
    start and its nearest passing references on the same pool.

Classification. An episode that reports ``invalid_scene`` (aggregate metrics, and the
scenario sidecar) is a *valid* record with outcome ``invalid_scene``: it never
cancels the pool and never counts as a policy failure. Every other record that is not
``valid`` cancels the pool, exactly as in M3 and M6.

The code that runs in the Job stays Python 3.8 compatible.
"""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from robot_debug import batch_experiment as be
from robot_debug import scenario_state as ss
from robot_debug.scene_inspect import validity_companion
from robot_debug.decided_gate import run_gates
from robot_debug.job_process import InfrastructureError, RunCancelled
from robot_debug.m6_experiment import ASSUMED_OVERHEAD_SECONDS, DEADLINE_ROUNDING_SECONDS, EvaluatorPool
from robot_debug.scenario_hypothesis import hypothesis_verdict
from robot_debug.scenario_import import (
    build_candidate, load_scenario_candidate, write_scenario_candidate)
from robot_debug.scenario_reduce import run_scenario_reduction

SCENARIO_MODES = ("scenario-smoke", "scenario-screen", "scenario-reduce")
SCENARIO_SUITES = ("libero_10", "libero_object")
DEFAULT_SUITE = "libero_10"
SCENARIO_WORKERS = 12
SCENARIO_MAX_BATCH_SIZE = 12
SUMMARY_NAME = "scenario_summary.json"
OUTCOMES = ("success", "policy_failure", "invalid_scene")

# Names of the files a stage writes into its own output directory.
STATE_FILE = "start_state.json"
LAYOUT_FILE = "layout.json"
SIDECAR_FILE = "scenario_start.json"

# ---- timing assumptions behind the recommended deadlines ---------------------------
# LIBERO-10 episodes run up to 520 steps. With 12 evaluators sharing one server, about
# 130 s of wall time for an episode that fails (it uses all steps) and about 80 s for a
# typical success. These are planning figures (M3 measured 44 s per LIBERO-Object wave).
ASSUMED_FAILING_EPISODE_SECONDS = 130.0
ASSUMED_SUCCESS_EPISODE_SECONDS = 80.0
# The screen's planning figure for the share of starts whose first attempt fails.
ASSUMED_SCREEN_FAILING_FRACTION = 0.2
# One reduction round (two candidates of up to five attempts) is about one wave.
ASSUMED_REDUCE_ROUND_SECONDS = 100.0
# The reduction's gate round (failing start, reference, full hybrid: up to 15 attempts).
REDUCE_GATE_WAVES = 2
REDUCE_REFERENCE_FALLBACK_ROUNDS = 1
MAX_DEADLINE_SECONDS = 3000       # the runtime's hard cap (validate_workload_config)
MIN_DEADLINE_SECONDS = 1000       # the prepare script's floor for batch-style Jobs

# ---- configuration bounds ---------------------------------------------------------------
MAX_TASK_ID = 99
MAX_SCREEN_TASKS = 10
MAX_SCREEN_STARTS = 50
MAX_START_INDEX = 49
MAX_SCREEN_EPISODES = 600
MAX_CONFIRM_ATTEMPTS = 8
MAX_REDUCE_ATTEMPTS = 8
MAX_REDUCE_BISECTION = 6
MAX_REDUCE_CANDIDATES = 30
MAX_REDUCE_CONCURRENCY = 3
MAX_REDUCE_REFERENCES = 3
MAX_REFERENCES_IN_PLAN = 5
MAX_ORDER = 64
MAX_TEXT = 4000
MAX_RAW = 8000
MAX_INSTRUCTION = 500

COMMON_OPTIONAL = {"suite"}
MODE_REQUIRED = {
    "scenario-smoke": set(),
    "scenario-screen": {"task_ids", "start_indices"},
    "scenario-reduce": {"task_id", "instruction", "layout", "failing", "references", "order",
                        "order_source", "hypothesis"},
}
MODE_OPTIONAL = {
    "scenario-smoke": {"task_id"},
    "scenario-screen": {"attempts", "confirm_attempts", "required_failures"},
    "scenario-reduce": {"attempts", "required_failures", "bisection_steps", "max_candidates",
                        "concurrency", "max_references"},
}
_HYPOTHESIS_KEYS = {"text", "ranking", "source", "model", "tier", "fallback_reason", "completed",
                    "provenance", "raw_content"}


class ScenarioConfigError(ValueError):
    """A scenario workload field is out of bounds; the message is a fixed reason."""


def _fail(message: str) -> None:
    raise ScenarioConfigError(message)


def _int(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        _fail("{} must be an integer from {} to {}".format(name, low, high))
    return value


def _text(value: Any, name: str, limit: int, nullable: bool = False) -> Optional[str]:
    if value is None and nullable:
        return None
    if type(value) is not str or not value.strip() or len(value) > limit:
        _fail("{} must be a non-empty string of at most {} characters".format(name, limit))
    if any(ord(ch) < 32 and ch not in "\n\t" or ord(ch) == 127 for ch in value):
        _fail("{} contains control characters".format(name))
    return value


def _index_list(value: Any, name: str, limit: int, high: int) -> List[int]:
    if type(value) is not list or not 1 <= len(value) <= limit:
        _fail("{} must be a short non-empty list of integers".format(name))
    if any(type(item) is not int or not 0 <= item <= high for item in value) or len(set(value)) != len(value):
        _fail("{} must hold distinct integers from 0 to {}".format(name, high))
    return list(value)


def _validate_outcomes(value: Any, name: str) -> List[str]:
    if type(value) is not list or len(value) > 20 or any(item not in OUTCOMES for item in value):
        _fail("{} must be a short list of known outcomes".format(name))
    return list(value)


def validate_mode_fields(mode: str, config: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the mode-specific fields (``config`` already has exactly the allowed keys).

    Returns the validated fields with defaults filled in, always including ``suite``.
    """

    suite = config.get("suite", DEFAULT_SUITE)
    if type(suite) is not str or suite not in SCENARIO_SUITES:
        _fail("suite must be one of {}".format(", ".join(SCENARIO_SUITES)))
    fields = {"suite": suite}  # type: Dict[str, Any]
    if mode == "scenario-smoke":
        fields["task_id"] = _int(config.get("task_id", 0), "task_id", 0, MAX_TASK_ID)
    elif mode == "scenario-screen":
        fields["task_ids"] = _index_list(config["task_ids"], "task_ids", MAX_SCREEN_TASKS, MAX_TASK_ID)
        fields["start_indices"] = _index_list(
            config["start_indices"], "start_indices", MAX_SCREEN_STARTS, MAX_START_INDEX)
        fields["attempts"] = _int(config.get("attempts", 1), "attempts", 1, 1)
        fields["confirm_attempts"] = _int(
            config.get("confirm_attempts", 4), "confirm_attempts", 0, MAX_CONFIRM_ATTEMPTS)
        total = fields["attempts"] + fields["confirm_attempts"]
        fields["required_failures"] = _int(
            config.get("required_failures", min(4, total)), "required_failures", 1, total)
        if fields["confirm_attempts"] and fields["required_failures"] < 2:
            _fail("required_failures must be at least 2 when starts are confirmed")
        worst = len(fields["task_ids"]) * len(fields["start_indices"]) * total
        if worst > MAX_SCREEN_EPISODES:
            _fail("the screen exceeds the episode bound")
    else:
        fields.update(_validate_reduce_fields(suite, config))
    return fields


def _validate_reduce_fields(suite: str, config: Mapping[str, Any]) -> Dict[str, Any]:
    fields = {}  # type: Dict[str, Any]
    fields["task_id"] = _int(config["task_id"], "task_id", 0, MAX_TASK_ID)
    fields["instruction"] = _text(config["instruction"], "instruction", MAX_INSTRUCTION).strip()
    try:
        layout = ss.validate_layout(config["layout"])
    except ss.ScenarioStateError:
        _fail("layout is invalid")
    if layout["suite"] != suite or layout["task_id"] != fields["task_id"]:
        _fail("layout does not belong to the suite and task")
    fields["layout"] = copy.deepcopy(layout)

    def state_of(value: Any) -> List[float]:
        try:
            return ss.validate_state(value, layout).tolist()
        except ss.ScenarioStateError:
            _fail("a start state does not match the layout")
        raise AssertionError("unreachable")

    failing = config["failing"]
    if type(failing) is not dict or set(failing) != {"start_index", "outcomes", "state"}:
        _fail("failing needs exactly start_index, outcomes and state")
    fields["failing"] = {
        "start_index": _int(failing["start_index"], "failing start_index", 0, MAX_START_INDEX),
        "outcomes": _validate_outcomes(failing["outcomes"], "failing outcomes"),
        "state": state_of(failing["state"]),
    }
    references = config["references"]
    if type(references) is not list or not 1 <= len(references) <= MAX_REFERENCES_IN_PLAN:
        _fail("references must be a short non-empty list")
    seen = {fields["failing"]["start_index"]}
    checked = []
    for entry in references:
        if type(entry) is not dict or set(entry) != {
                "start_index", "distance", "outcomes", "state", "differences"}:
            _fail("a reference needs exactly start_index, distance, outcomes, state and differences")
        index = _int(entry["start_index"], "reference start_index", 0, MAX_START_INDEX)
        if index in seen:
            _fail("reference start indices must be distinct from each other and the failing start")
        seen.add(index)
        distance = entry["distance"]
        if type(distance) not in (int, float) or not math.isfinite(distance) or distance < 0:
            _fail("reference distance must be a non-negative number")
        if type(entry["differences"]) is not list or len(entry["differences"]) > 200:
            _fail("reference differences must be a list")
        checked.append({
            "start_index": index, "distance": float(distance),
            "outcomes": _validate_outcomes(entry["outcomes"], "reference outcomes"),
            "state": state_of(entry["state"]), "differences": copy.deepcopy(entry["differences"]),
        })
    fields["references"] = checked
    order = config["order"]
    if type(order) is not list or len(order) > MAX_ORDER or any(
            type(name) is not str or not name or len(name) > 128 for name in order):
        _fail("order must be a list of entity names")
    fields["order"] = list(order)
    if config["order_source"] not in ("model", "fixed_order"):
        _fail("order_source must be model or fixed_order")
    fields["order_source"] = config["order_source"]
    hypothesis = config["hypothesis"]
    if type(hypothesis) is not dict or set(hypothesis) != _HYPOTHESIS_KEYS:
        _fail("hypothesis needs exactly its documented keys")
    ranking = hypothesis["ranking"]
    completed = hypothesis["completed"]
    for name, value in (("ranking", ranking), ("completed", completed)):
        if type(value) is not list or len(value) > MAX_ORDER or any(type(item) is not str for item in value):
            _fail("hypothesis {} must be a list of entity names".format(name))
    checked_hypothesis = {
        "text": _text(hypothesis["text"], "hypothesis text", MAX_TEXT, nullable=True),
        "ranking": list(ranking), "completed": list(completed),
        "source": _text(hypothesis["source"], "hypothesis source", 64),
        "model": _text(hypothesis["model"], "hypothesis model", 200, nullable=True),
        "tier": _text(hypothesis["tier"], "hypothesis tier", 64, nullable=True),
        "fallback_reason": _text(hypothesis["fallback_reason"], "hypothesis fallback_reason", 500,
                                 nullable=True),
        "raw_content": _text(hypothesis["raw_content"], "hypothesis raw_content", MAX_RAW, nullable=True),
    }
    provenance = hypothesis["provenance"]
    try:
        if len(json.dumps(provenance, allow_nan=False)) > MAX_TEXT:
            raise ValueError
    except (TypeError, ValueError):
        _fail("hypothesis provenance must be small JSON")
    checked_hypothesis["provenance"] = copy.deepcopy(provenance)
    fields["hypothesis"] = checked_hypothesis
    fields["attempts"] = _int(config.get("attempts", 5), "attempts", 1, MAX_REDUCE_ATTEMPTS)
    fields["required_failures"] = _int(
        config.get("required_failures", min(4, fields["attempts"])), "required_failures", 1,
        fields["attempts"])
    fields["bisection_steps"] = _int(config.get("bisection_steps", 4), "bisection_steps", 0,
                                     MAX_REDUCE_BISECTION)
    fields["max_candidates"] = _int(config.get("max_candidates", MAX_REDUCE_CANDIDATES),
                                    "max_candidates", 1, MAX_REDUCE_CANDIDATES)
    fields["concurrency"] = _int(config.get("concurrency", 2), "concurrency", 1, MAX_REDUCE_CONCURRENCY)
    fields["max_references"] = _int(config.get("max_references", MAX_REDUCE_REFERENCES),
                                    "max_references", 1, MAX_REDUCE_REFERENCES)
    return fields


# ---------------------------------------------------------------------------
# Deadline estimate
# ---------------------------------------------------------------------------


def _waves(episodes: int, workers: int = SCENARIO_WORKERS) -> int:
    return int(math.ceil(episodes / float(workers))) if episodes > 0 else 0


def planned_episodes(mode: str, config: Mapping[str, Any]) -> int:
    """Worst-case valid episodes the mode may run (the warm-up not included)."""

    if mode == "scenario-smoke":
        return 6
    if mode == "scenario-screen":
        total = config.get("attempts", 1) + config.get("confirm_attempts", 4)
        return len(config["task_ids"]) * len(config["start_indices"]) * total
    attempts = config.get("attempts", 5)
    gates = 3 * attempts
    return gates + int(config.get("max_candidates", MAX_REDUCE_CANDIDATES)) * attempts


def recommended_deadline_seconds(mode: str, config: Mapping[str, Any]) -> int:
    """A Job ``deadline_seconds`` from the documented timing assumptions.

    One-off overheads (as for M6), plus the work in whole waves of 12 episodes, plus
    the no-start guard (an item is never started with less than the item timeout left,
    so the last one needs that plus one failing-episode wall time). Rounded up to whole
    minutes, never below the 1000 s floor, and refused above the runtime's 3000 s cap.
    """

    if mode == "scenario-smoke":
        work = 2 * ASSUMED_FAILING_EPISODE_SECONDS             # starts, then the derived scenes
    elif mode == "scenario-screen":
        first = len(config["task_ids"]) * len(config["start_indices"]) * config.get("attempts", 1)
        mixed = (ASSUMED_SCREEN_FAILING_FRACTION * ASSUMED_FAILING_EPISODE_SECONDS
                 + (1.0 - ASSUMED_SCREEN_FAILING_FRACTION) * ASSUMED_SUCCESS_EPISODE_SECONDS)
        failing_starts = int(math.ceil(first * ASSUMED_SCREEN_FAILING_FRACTION))
        confirm = failing_starts * config.get("confirm_attempts", 4)
        work = (_waves(first) * mixed + _waves(confirm) * ASSUMED_FAILING_EPISODE_SECONDS
                + ASSUMED_FAILING_EPISODE_SECONDS)             # the last term: the top-up wave
    elif mode == "scenario-reduce":
        rounds = int(math.ceil(config.get("max_candidates", MAX_REDUCE_CANDIDATES)
                               / float(config.get("concurrency", 2))))
        work = (REDUCE_GATE_WAVES + rounds + REDUCE_REFERENCE_FALLBACK_ROUNDS) * ASSUMED_REDUCE_ROUND_SECONDS
    else:
        raise ValueError("unsupported scenario mode")
    total = (sum(ASSUMED_OVERHEAD_SECONDS.values()) + work + be.ITEM_TIMEOUT_SECONDS
             + ASSUMED_FAILING_EPISODE_SECONDS)
    rounded = int(max(MIN_DEADLINE_SECONDS, math.ceil(total / DEADLINE_ROUNDING_SECONDS)
                      * DEADLINE_ROUNDING_SECONDS))
    if rounded > MAX_DEADLINE_SECONDS:
        raise ValueError("this workload needs more than the {} s cap; shrink it".format(MAX_DEADLINE_SECONDS))
    return rounded


# ---------------------------------------------------------------------------
# The pool: tickets that can be withdrawn, and waiting for any of several
# ---------------------------------------------------------------------------


class ScenarioTicket:
    """One submitted attempt; satisfies :class:`robot_debug.decided_gate.Ticket`."""

    def __init__(self, item: Mapping[str, Any], pool: "ScenarioPool") -> None:
        self.item = item
        self.event = threading.Event()
        self.record = None  # type: Optional[Dict[str, Any]]
        self._pool = pool
        self._lock = threading.Lock()
        self._state = "queued"

    def done(self) -> bool:
        return self.event.is_set()

    def claim(self) -> bool:
        """Called by a worker before it starts the item; False if it was withdrawn."""

        with self._lock:
            if self._state == "queued":
                self._state = "started"
                return True
            return False

    def withdraw(self) -> bool:
        """Cancel an attempt that has not started; its record becomes ``decided_skipped``."""

        with self._lock:
            if self._state != "queued":
                return False
            self._state = "withdrawn"
            self._pool._skipped(self, "decided_skipped")
            self.event.set()
        self._pool.notify()
        return True


class ScenarioPool(EvaluatorPool):
    """The M6 evaluator pool plus withdrawable tickets and ``wait_any`` (the gate Executor)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._changed = threading.Condition()

    def submit(self, item: Mapping[str, Any]) -> ScenarioTicket:  # type: ignore[override]
        ticket = ScenarioTicket(item, self)
        self._queue.put(ticket)  # type: ignore[arg-type]
        return ticket

    def notify(self) -> None:
        with self._changed:
            self._changed.notify_all()

    def wait_any(self, tickets: Sequence[ScenarioTicket], timeout: float) -> None:
        """Return when at least one ticket is done, or after ``timeout`` seconds."""

        end = time.monotonic() + max(0.0, timeout)
        with self._changed:
            while not any(ticket.event.is_set() for ticket in tickets):
                left = end - time.monotonic()
                if left <= 0:
                    return
                self._changed.wait(min(left, 0.5))  # short slices: a KeyboardInterrupt is delivered

    def _work(self) -> None:
        while True:
            ticket = self._queue.get()
            if ticket is None:
                return
            try:
                if not ticket.claim():
                    continue                   # withdrawn: its record is already set
                if self.cancel.is_set():
                    self._skipped(ticket, "cancelled")
                elif self._remaining() < self._item_timeout:
                    self.deadline_stop.set()
                    self._skipped(ticket, "deadline_skipped")
                else:
                    record = self._evaluate(ticket.item)
                    with self._lock:
                        self.results.append(record)
                    if record["status"] != "valid":
                        self.cancel.set()
                    ticket.record = record
            except BaseException:
                self.cancel.set()
                self._skipped(ticket, "infrastructure_error")
            finally:
                ticket.event.set()
                self.notify()


class PoolExecutor:
    """Adapts the pool to the gate scheduler's ``Executor`` protocol.

    ``make_item(spec)`` turns the scheduler's ``{**candidate item, "attempt": i}`` into
    a pool item (unique ``case_id``, config, meta).
    """

    def __init__(self, pool: ScenarioPool, make_item: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        self.pool = pool
        self._make_item = make_item

    def submit(self, item: Dict[str, Any]) -> ScenarioTicket:
        return self.pool.submit(self._make_item(item))

    def wait_any(self, tickets: Sequence[ScenarioTicket], timeout: float) -> None:
        self.pool.wait_any(tickets, timeout)


# ---------------------------------------------------------------------------
# One episode: configuration, evidence and classification
# ---------------------------------------------------------------------------


def _reject_constant(value: str) -> None:
    raise ValueError("non-standard JSON constant: " + value)


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_reject_constant)


def _relative(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def read_evidence(output_dir: Path, batch_root: Path) -> Dict[str, Any]:
    """What one stage left behind: the aggregate's task text and metrics, the sidecar, the video.

    Raises ``ValueError``/``OSError`` when the evidence is missing or malformed.
    """

    output_dir = Path(output_dir)
    aggregates = sorted(output_dir.rglob("*_aggregate.json"))
    if len(aggregates) != 1:
        raise ValueError("expected exactly one aggregate")
    aggregate = _load_json(aggregates[0])
    task = aggregate["tasks"][0]
    episode = task["episodes"][0]
    metrics = episode.get("metrics")
    flagged = bool(metrics.get("invalid_scene")) if isinstance(metrics, Mapping) else False
    sidecar = None
    sidecar_path = output_dir / SIDECAR_FILE
    if sidecar_path.is_file():
        records = _load_json(sidecar_path)
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise ValueError("the scenario sidecar must hold exactly one record")
        sidecar = records[0]
    videos = sorted(output_dir.rglob("*.mp4"))
    instruction = task.get("task")
    return {
        "metric_invalid_scene": flagged,
        "instruction": instruction if isinstance(instruction, str) else None,
        "sidecar": sidecar,
        "video": _relative(videos[0], batch_root) if videos else None,
    }


_START_VALIDITY_KEYS = ("validity", "deepest_penetration_m", "deepest_pair", "invalid_contacts")


def _read_start_validity(state_file: Path) -> Dict[str, Any]:
    """The contact scan recorded beside an exported benchmark start; refuses a missing or odd record."""

    document = _load_json(Path(validity_companion(str(state_file))))
    if not isinstance(document, dict) or document.get("validity") not in ("valid", "invalid_scene"):
        raise ValueError("the start validity record is malformed")
    return {key: document.get(key) for key in _START_VALIDITY_KEYS}


_RESTORE_KEYS = (
    "validity", "candidate_state_sha256", "pre_settle_state_sha256", "post_settle_state_sha256",
    "settling_steps", "deepest_penetration_m", "deepest_pair", "invalid_contacts",
    "settle_displacement_m",
)


def make_scenario_evaluate(
    *,
    suite: str,
    project_root: Path,
    write_config: Callable[..., None],
    load_result: Callable[[Path], Any],
    run_item: Callable[..., Any],
    cancel: threading.Event,
    item_timeout: float,
    clock: Callable[[], float],
    ready_at: float,
    configs_dir: Path,
    runs_dir: Path,
    batch_root: Path,
    stage_prefix: str = "scn-",
    read: Optional[Callable[[Path, Path], Dict[str, Any]]] = None,
) -> Callable[..., Dict[str, Any]]:
    """The one-item evaluator of the scenario modes.

    Items are ``{"case_id", "kind", "config", "exports", "meta"}``. ``config`` holds the
    start selector (``task_id`` plus ``init_state_index`` or ``scenario_start``);
    ``exports`` asks for ``state_out`` and ``layout_out`` files in the stage output.
    The record's ``status`` is ``valid`` for a completed policy result *and* for an
    ``invalid_scene`` episode, whose outcome is ``invalid_scene``.
    """

    default_configs, default_runs = configs_dir, runs_dir
    reader = read or read_evidence

    def evaluate(
        item: Mapping[str, Any], *, case_id: Optional[str] = None,
        configs_dir: Path = default_configs, runs_dir: Path = default_runs,
    ) -> Dict[str, Any]:
        case_id = str(item["case_id"]) if case_id is None else case_id
        record = {
            "case_id": case_id, "kind": item["kind"], "status": "infrastructure_error",
            "outcome": None, "started_seconds": round(clock() - ready_at, 3),
        }  # type: Dict[str, Any]
        if item.get("meta"):
            record.update(item["meta"])
        try:
            config_path = configs_dir / (case_id + ".yaml")
            output = runs_dir / case_id
            kwargs = dict(item["config"])
            kwargs.setdefault("suite", suite)
            exports = item.get("exports") or {}
            if exports.get("state_out"):
                kwargs["state_out"] = output / STATE_FILE
            if exports.get("layout_out"):
                kwargs["layout_out"] = output / LAYOUT_FILE
            if kwargs.get("scenario_start") is not None:
                kwargs["scenario_start"] = Path(kwargs["scenario_start"])
            write_config(
                config_path=config_path, output_dir=output, project_root=project_root,
                stage_name=stage_prefix + case_id, episode_indices=(0,), **kwargs)
            run_item(["vla-eval", "run", "--config", str(config_path)],
                     item_timeout=item_timeout, cancel=cancel)
            result = load_result(output)
            base = getattr(result, "outcome", None)
            if base not in ("success", "policy_failure") or getattr(result, "episode_index", 0) != 0:
                record["status"] = "invalid_evidence"
            else:
                evidence = reader(output, batch_root)
                sidecar = evidence["sidecar"]
                flagged = bool(evidence["metric_invalid_scene"])
                if "scenario_start" in kwargs:
                    consistent = sidecar is not None and flagged == (sidecar.get("validity") == "invalid_scene")
                else:
                    consistent = sidecar is None and not flagged
                if not consistent:
                    record["status"] = "invalid_evidence"
                else:
                    outcome = "invalid_scene" if flagged else base
                    record.update(status="valid", outcome=outcome, steps=getattr(result, "steps", None))
                    artifacts = {"video": evidence["video"]}
                    if exports.get("state_out"):
                        artifacts["state"] = _relative(output / STATE_FILE, batch_root)
                        try:
                            record["start_validity"] = _read_start_validity(output / STATE_FILE)
                        except (OSError, ValueError):
                            record.update(status="invalid_evidence", outcome=None)
                    if exports.get("layout_out"):
                        artifacts["layout"] = _relative(output / LAYOUT_FILE, batch_root)
                    record["artifacts"] = artifacts
                    if evidence.get("instruction"):
                        record["instruction"] = evidence["instruction"]
                    if sidecar is not None:
                        record["restore"] = {key: sidecar.get(key) for key in _RESTORE_KEYS}
        except RunCancelled:
            record["status"] = "cancelled"
        except InfrastructureError as error:
            timed_out = isinstance(error.__cause__, subprocess.TimeoutExpired)
            record["status"] = "timed_out" if timed_out else "infrastructure_error"
        except Exception:
            record["status"] = "infrastructure_error"
        record["ended_seconds"] = round(clock() - ready_at, 3)
        return record

    return evaluate


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------


class _Context:
    """What a driver may use while it runs."""

    def __init__(self, *, pool: ScenarioPool, failure: Callable[[], Optional[str]],
                 remaining: Callable[[], float], progress: Callable[..., None], batch_root: Path,
                 suite: str, workers: int) -> None:
        self.pool, self.failure, self.remaining = pool, failure, remaining
        self.progress, self.batch_root, self.suite, self.workers = progress, batch_root, suite, workers

    def stop_reason(self, records: Sequence[Mapping[str, Any]]) -> Optional[str]:
        """The stop reason if any record is neither valid nor withdrawn, else ``None``."""

        bad = [r for r in records if r.get("status") not in ("valid", "decided_skipped")]
        if not bad:
            return None
        return self.failure() or (
            "deadline_exhausted" if self.pool.deadline_stop.is_set() else "phase_incomplete")


def _item(case_id: str, kind: str, config: Mapping[str, Any], exports: Optional[Mapping[str, Any]] = None,
          **meta: Any) -> Dict[str, Any]:
    return {"case_id": case_id, "kind": kind, "config": dict(config),
            "exports": dict(exports or {}), "meta": dict(meta, condition=kind)}


def _run_records(ctx: _Context, items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    tickets = [ctx.pool.submit(item) for item in items]
    ctx.pool.wait(tickets)
    return [ticket.record for ticket in tickets]  # type: ignore[misc]


def _first_valid(records: Sequence[Mapping[str, Any]], key: Optional[str] = None,
                 outcome: Optional[str] = None) -> Optional[Mapping[str, Any]]:
    for record in records:
        if record.get("status") != "valid":
            continue
        if key is not None and record.get("key") != key:
            continue
        if outcome is not None and record.get("outcome") != outcome:
            continue
        return record
    return None


# ---- smoke ------------------------------------------------------------------------

# Objects likely to be hollow containers: not used as the "overlapped" pair in the smoke.
_CONTAINER_TOKENS = ("basket", "bowl", "tray", "plate", "pot", "pan", "mug", "cup", "drawer", "cabinet",
                     "microwave", "stove", "rack", "caddy")


def _overlap_pair(layout: Mapping[str, Any]) -> Optional[Tuple[str, str]]:
    free = [e for e in ss.entities(layout) if e.kind == "object" and e.free is not None]
    solid = [e for e in free if not any(token in e.name for token in _CONTAINER_TOKENS)]
    pool = solid if len(solid) >= 2 else free
    if len(pool) < 2:
        return None
    return pool[0].name, pool[1].name


def overlapping_state(state: Sequence[float], layout: Mapping[str, Any]) -> Tuple[List[float], Tuple[str, str]]:
    """The state with the second object's position set onto the first object's (interpenetrating)."""

    pair = _overlap_pair(layout)
    if pair is None:
        raise ss.ScenarioStateError("the scene has fewer than two free objects")
    by_name = {entity.name: entity for entity in ss.entities(layout)}
    values = ss.validate_state(state, layout).copy()
    first = 1 + by_name[pair[0]].free["qpos_adr"]
    second = 1 + by_name[pair[1]].free["qpos_adr"]
    values[second:second + 3] = values[first:first + 3]
    return values.tolist(), pair


def objects_from_failing(layout: Mapping[str, Any]) -> Dict[str, Dict[str, float]]:
    """Selection that moves every object entity (all components) to the failing state, not the robot."""

    return {entity.name: {component: 1.0 for component in entity.components}
            for entity in ss.entities(layout) if entity.kind == "object"}


class SmokeDriver:
    mode = "scenario-smoke"

    def __init__(self, config: Mapping[str, Any], suite: str, batch_root: Path) -> None:
        self.config, self.suite, self.batch_root = config, suite, Path(batch_root)
        self.task_id = config["task_id"]
        self.body = {"checks": {}, "layout": None, "state_length": None, "scenes": [],
                     "overlap_pair": None}  # type: Dict[str, Any]

    def _start(self, name: str, index: int, *, layout: bool, state: bool = True) -> Dict[str, Any]:
        return _item(name, "start", {"task_id": self.task_id, "init_state_index": index},
                     {"state_out": state, "layout_out": layout}, start_index=index)

    def warmup_item(self) -> Dict[str, Any]:
        return self._start("init0-a", 0, layout=True)

    def run(self, ctx: _Context) -> Optional[str]:
        first = [self.warmup_item(), self._start("init0-b", 0, layout=False),
                 self._start("init1", 1, layout=False)]
        records = _run_records(ctx, first)
        reason = ctx.stop_reason(records)
        if reason is not None:
            self.body["scenes"] = [self._scene(r) for r in records]
            return reason
        runs = self.batch_root / "runs"
        try:
            layout = ss.validate_layout(_load_json(runs / "init0-a" / LAYOUT_FILE))
            starts = [load_scenario_candidate(runs / name / STATE_FILE)
                      for name in ("init0-a", "init0-b", "init1")]
            s0, s0_again, s1 = (candidate["state"] for candidate in starts)
            hybrid = ss.hybrid(s0, s1, objects_from_failing(layout), layout).tolist()
            overlap, pair = overlapping_state(s0, layout)
        except (OSError, ValueError):       # includes the layout, state and import errors
            self.body["scenes"] = [self._scene(r) for r in records]
            return ctx.failure() or "smoke_inputs_invalid"
        self.body["layout"] = layout
        self.body["state_length"] = layout["state_length"]
        self.body["overlap_pair"] = list(pair)
        directory = self.batch_root / "candidates"
        paths = {}
        for name, state, source in (
            ("restore-s0", s0, {"kind": "benchmark", "init_state_index": 0}),
            ("hybrid-objects-s1", hybrid, {"kind": "hybrid", "reference": 0, "failing": 1, "applied": [
                {"entity": entity, "component": "all", "t": 1.0}
                for entity in sorted(objects_from_failing(layout))]}),
            ("overlap-s0", overlap, {"kind": "hybrid", "reference": 0, "failing": 0, "applied": [
                {"entity": pair[1], "component": "position", "t": 1.0, "onto": pair[0]}]}),
        ):
            paths[name] = directory / (name + ".json")
            write_scenario_candidate(paths[name], build_candidate(self.suite, self.task_id, state, source))
        second = [_item(name, "scenario", {"task_id": self.task_id, "scenario_start": str(paths[name])},
                        scene=name) for name in ("restore-s0", "hybrid-objects-s1", "overlap-s0")]
        more = _run_records(ctx, second)
        records = records + more
        self.body["scenes"] = [self._scene(r) for r in records]
        by_case = {r["case_id"]: r for r in records}
        restore, mixed, overlapped = (by_case.get(n) for n in ("restore-s0", "hybrid-objects-s1", "overlap-s0"))

        def validity(record: Optional[Mapping[str, Any]]) -> Optional[str]:
            return ((record or {}).get("restore") or {}).get("validity")

        def hashes_match(record: Optional[Mapping[str, Any]], name: str) -> bool:
            restored = (record or {}).get("restore") or {}
            expected = load_scenario_candidate(paths[name])["state_sha256"]
            return (restored.get("candidate_state_sha256") == expected
                    and restored.get("pre_settle_state_sha256") == expected)

        checks = self.body["checks"]
        checks["state_export_repeatable"] = s0 == s0_again
        checks["state_length_matches_layout"] = len(s0) == layout["state_length"]
        checks["restore_hash_matches"] = hashes_match(restore, "restore-s0") and validity(restore) == "valid"
        checks["hybrid_restored_and_valid"] = (
            hashes_match(mixed, "hybrid-objects-s1") and validity(mixed) == "valid")
        checks["overlap_marked_invalid_scene"] = (
            (overlapped or {}).get("outcome") == "invalid_scene" and validity(overlapped) == "invalid_scene")
        checks["invalid_scene_not_a_policy_failure"] = (
            (overlapped or {}).get("status") == "valid" and (overlapped or {}).get("outcome") != "policy_failure")
        # A broken checkpoint (or a moved benchmark) must not look like a healthy smoke: at least one
        # unperturbed attempt of start 0 succeeds, and the exported benchmark starts are at rest.
        checks["nominal_success_seen"] = any(
            (by_case.get(name) or {}).get("outcome") == "success" for name in ("init0-a", "init0-b"))
        nq = layout["nq"]
        checks["benchmark_start_at_rest"] = all(
            state[0] == 0.0 and all(value == 0.0 for value in state[1 + nq:]) for state in (s0, s0_again, s1))
        ctx.progress("scenario_smoke_done", checks=dict(checks))
        return ctx.stop_reason(more)

    @staticmethod
    def _scene(record: Mapping[str, Any]) -> Dict[str, Any]:
        keys = ("case_id", "kind", "status", "outcome", "steps", "restore", "artifacts", "start_validity",
                "started_seconds", "ended_seconds")
        return {key: record.get(key) for key in keys if key in record}

    def complete(self, stop_reason: Optional[str]) -> bool:
        return stop_reason is None and bool(self.body["checks"]) and all(self.body["checks"].values())


# ---- screen ---------------------------------------------------------------------------


def _screen_case(task: int, start: int, attempt: int) -> str:
    return "t{:02d}-s{:02d}-a{:02d}".format(task, start, attempt + 1)


class ScreenDriver:
    mode = "scenario-screen"

    def __init__(self, config: Mapping[str, Any], suite: str, batch_root: Path) -> None:
        self.config, self.suite, self.batch_root = config, suite, Path(batch_root)
        self.attempts = config["attempts"]
        self.confirm = config["confirm_attempts"]
        self.required = config["required_failures"]
        self.starts = {}  # type: Dict[Tuple[int, int], Dict[str, Any]]
        self.body = {"suite": suite, "tasks": {}, "reproducible_failures": [], "phase1": None,
                     "confirm": None, "topup": None}  # type: Dict[str, Any]

    def _attempt_item(self, task: int, start: int, attempt: int, *, phase: str,
                      state: bool = False, layout: bool = False) -> Dict[str, Any]:
        return _item(_screen_case(task, start, attempt), "screen",
                     {"task_id": task, "init_state_index": start},
                     {"state_out": state, "layout_out": layout},
                     task_id=task, start_index=start, attempt=attempt + 1, phase=phase)

    def warmup_item(self) -> Dict[str, Any]:
        return self._attempt_item(self.config["task_ids"][0], self.config["start_indices"][0], 0,
                                  phase="warmup", state=True, layout=True)

    def run(self, ctx: _Context) -> Optional[str]:
        tasks, starts = self.config["task_ids"], self.config["start_indices"]
        first = []
        for task in tasks:
            for position, start in enumerate(starts):
                for attempt in range(self.attempts):
                    first.append(self._attempt_item(
                        task, start, attempt, phase="screen", state=attempt == 0, layout=position == 0 and attempt == 0))
        records = _run_records(ctx, first)
        self._absorb(records)
        reason = ctx.stop_reason(records)
        self.body["phase1"] = {"episodes": len(first), "valid": sum(r["status"] == "valid" for r in records)}
        ctx.progress("scenario_screen_phase1_done", **self.body["phase1"])
        if reason is not None or not self.confirm:
            return reason
        failing = [(task, start) for (task, start), data in sorted(self.starts.items())
                   if any(r["outcome"] == "policy_failure" for r in data["records"] if r["status"] == "valid")]
        candidates = [{"key": _screen_case(task, start, 0)[:-4],
                       "item": {"task_id": task, "start_index": start}, "kind": "failure"}
                      for task, start in failing]
        gate_attempts = self.confirm
        need = max(1, self.required - self.attempts_failed_at_first())

        def make_item(spec: Dict[str, Any]) -> Dict[str, Any]:
            return self._attempt_item(spec["task_id"], spec["start_index"],
                                      self.attempts + spec["attempt"], phase="confirm")

        executor = PoolExecutor(ctx.pool, make_item)
        run = run_gates(executor, candidates, attempts=gate_attempts, required_failures=need,
                        max_in_flight=ctx.workers, remaining=ctx.remaining, drain=True)
        decisions = {}
        for candidate in candidates:
            key = candidate["key"]
            task, start = candidate["item"]["task_id"], candidate["item"]["start_index"]
            self._absorb(run.records[key])
            self.starts[(task, start)]["decision"] = run.decisions[key]
            self.starts[(task, start)]["skipped"] = run.skipped[key]
            decisions[key] = run.decisions[key]
        self.body["confirm"] = {"starts": len(candidates), "decisions": decisions,
                                "skipped_attempts": run.skipped_total, "stop": run.stop}
        ctx.progress("scenario_screen_confirm_done", **self.body["confirm"])
        if run.stop is not None:
            return ctx.failure() or run.stop
        # Top up each reproducible start to the full attempt count, so a candidate for the
        # expensive reduction carries a complete record (at most one attempt per start).
        extra = []
        total = self.attempts + self.confirm
        for (task, start), data in sorted(self.starts.items()):
            if data.get("decision") != "reproduces":
                continue
            done = {r["attempt"] for r in data["records"] if r["status"] == "valid"}
            extra += [self._attempt_item(task, start, number - 1, phase="topup")
                      for number in range(1, total + 1) if number not in done]
        topup = _run_records(ctx, extra) if extra else []
        self._absorb(topup)
        self.body["topup"] = {"episodes": len(extra)}
        return ctx.stop_reason(topup)

    def attempts_failed_at_first(self) -> int:
        """The failures every confirmed start already has (the first-phase attempts that failed)."""

        return self.attempts

    def _absorb(self, records: Sequence[Mapping[str, Any]]) -> None:
        for record in records:
            if "task_id" not in record or "start_index" not in record:
                continue
            data = self.starts.setdefault(
                (record["task_id"], record["start_index"]),
                {"records": [], "decision": None, "skipped": 0})
            if record.get("status") in ("valid",):
                data["records"].append(dict(record))

    # -- summary ----------------------------------------------------------------------

    def finish(self, stop_reason: Optional[str]) -> None:
        tasks = {}  # type: Dict[str, Any]
        failures = []
        for (task, start), data in sorted(self.starts.items()):
            entry = tasks.setdefault(str(task), {"instruction": None, "layout": None, "starts": {}})
            ordered = sorted(data["records"], key=lambda r: r["attempt"])
            for record in ordered:
                if record.get("instruction") and not entry["instruction"]:
                    entry["instruction"] = record["instruction"]
            state = None
            first = next((r for r in ordered if r["attempt"] == 1 and r.get("artifacts", {}).get("state")), None)
            if first is not None:
                try:
                    candidate = load_scenario_candidate(self.batch_root / first["artifacts"]["state"])
                    state = candidate["state"]
                except (OSError, ValueError):
                    state = None
            if entry["layout"] is None:
                layout_record = next((r for r in ordered if r.get("artifacts", {}).get("layout")), None)
                if layout_record is not None:
                    try:
                        entry["layout"] = ss.validate_layout(
                            _load_json(self.batch_root / layout_record["artifacts"]["layout"]))
                    except (OSError, ValueError):
                        entry["layout"] = None
            outcomes = [r["outcome"] for r in ordered]
            scan = (first or {}).get("start_validity") or {}
            entry["starts"][str(start)] = {
                "outcomes": outcomes,
                "validity": scan.get("validity"),
                "deepest_penetration_m": scan.get("deepest_penetration_m"),
                "deepest_pair": scan.get("deepest_pair"),
                "steps": [r.get("steps") for r in ordered],
                "state": state,
                "decision": data["decision"],
                "skipped_attempts": data["skipped"],
                "attempts": [{"case_id": r["case_id"], "attempt": r["attempt"], "outcome": r["outcome"],
                              "steps": r.get("steps"), "video": (r.get("artifacts") or {}).get("video")}
                             for r in ordered],
            }
            if data["decision"] == "reproduces":
                failures.append({"task_id": task, "start_index": start, "outcomes": outcomes,
                                 "failures": outcomes.count("policy_failure")})
        self.body["tasks"] = tasks
        self.body["reproducible_failures"] = failures

    def complete(self, stop_reason: Optional[str]) -> bool:
        expected = len(self.config["task_ids"]) * len(self.config["start_indices"])
        got = sum(1 for data in self.starts.values() if data["records"])
        return stop_reason is None and got == expected


# ---- reduce ---------------------------------------------------------------------------


def _hash_name(value: str) -> str:
    return value[:16]


class ReduceDriver:
    mode = "scenario-reduce"

    def __init__(self, config: Mapping[str, Any], suite: str, batch_root: Path) -> None:
        self.config, self.suite, self.batch_root = config, suite, Path(batch_root)
        self.layout = config["layout"]
        self.task_id = config["task_id"]
        self.failing_index = config["failing"]["start_index"]
        self.failing_state = ss.validate_state(config["failing"]["state"], self.layout)
        self.reference_states = {ref["start_index"]: ss.validate_state(ref["state"], self.layout)
                                 for ref in config["references"]}
        self.differences_match_plan = True
        self.references = []  # type: List[Dict[str, Any]]
        for ref in config["references"]:
            table = ss.differences(self.failing_state, self.reference_states[ref["start_index"]], self.layout)
            if table != ref["differences"] and json.loads(json.dumps(table)) != ref["differences"]:
                self.differences_match_plan = False
            self.references.append({"id": ref["start_index"], "differences": table})
        self._memo = {}  # type: Dict[str, Tuple[str, Dict[str, Any]]]
        self.keys = {}  # type: Dict[str, Dict[str, Any]]
        self.body = {}  # type: Dict[str, Any]

    # -- candidates -------------------------------------------------------------------

    def _write(self, role: str, state: Sequence[float], source: Mapping[str, Any]) -> Tuple[str, Path]:
        key = ss.state_hash(state)
        path = self.batch_root / "candidates" / "{}-{}.json".format(role, _hash_name(key))
        if not path.exists():
            write_scenario_candidate(path, build_candidate(self.suite, self.task_id, state, source))
        return key, path

    def prepare(self, spec: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
        role = spec["role"]
        memo_key = json.dumps(spec, sort_keys=True, default=str)
        if memo_key in self._memo:
            key, item = self._memo[memo_key]
            return key, copy.deepcopy(item)
        if role == "failing":
            key, path = self._write("failing", self.failing_state.tolist(),
                                    {"kind": "benchmark", "init_state_index": self.failing_index})
            case, meta = "fail-" + _hash_name(key), {"role": "failing", "key": key}
        elif role == "reference":
            rid = spec["reference"]
            key, path = self._write("reference", self.reference_states[rid].tolist(),
                                    {"kind": "benchmark", "init_state_index": rid})
            case, meta = "ref{:02d}-{}".format(rid, _hash_name(key)), {"role": "reference", "key": key,
                                                                       "reference": rid}
        elif role == "hybrid":
            rid = spec["reference"]
            selection = ss.normalise_selection(copy.deepcopy(spec["selection"]), self.layout)
            state = ss.hybrid(self.reference_states[rid], self.failing_state, selection, self.layout).tolist()
            applied = [{"entity": entity, "component": component, "t": t}
                       for entity, parts in selection.items() for component, t in parts.items()]
            key, path = self._write("hybrid", state, {
                "kind": "hybrid", "reference": rid, "failing": self.failing_index, "applied": applied})
            case, meta = "hyb-" + _hash_name(key), {"role": "hybrid", "key": key, "reference": rid}
        else:
            raise ValueError("unknown candidate role")
        item = _item(case, "reduce-" + role, {"task_id": self.task_id, "scenario_start": str(path)}, **meta)
        self._memo[memo_key] = (key, item)
        self.keys[key] = {"role": role, "path": path}
        return key, copy.deepcopy(item)

    @staticmethod
    def attempt_item(spec: Dict[str, Any]) -> Dict[str, Any]:
        number = int(spec["attempt"]) + 1
        item = {key: copy.deepcopy(value) for key, value in spec.items() if key != "attempt"}
        item["case_id"] = "{}-a{:02d}".format(spec["case_id"], number)
        item["meta"] = dict(spec.get("meta") or {}, attempt=number)
        return item

    def warmup_item(self) -> Dict[str, Any]:
        _key, item = self.prepare({"role": "failing"})
        return item

    def run(self, ctx: _Context) -> Optional[str]:
        executor = PoolExecutor(ctx.pool, self.attempt_item)
        result = run_scenario_reduction(
            executor, self.prepare, self.references, order=self.config["order"],
            attempts=self.config["attempts"], required_failures=self.config["required_failures"],
            bisection_steps=self.config["bisection_steps"], max_candidates=self.config["max_candidates"],
            concurrency=self.config["concurrency"], max_references=self.config["max_references"],
            max_in_flight=ctx.workers, remaining=ctx.remaining)
        self.body["reduction"] = result
        ctx.progress("scenario_reduce_done", stop_reason=result["stop_reason"],
                     candidates=result.get("candidates_tested"), skipped=result.get("attempts_skipped"))
        reason = result["stop_reason"]
        if reason in ("reduced",):
            return None
        if reason in ("failing_not_reproducible", "reference_not_passing"):
            return reason
        return ctx.failure() or reason

    def finish(self, stop_reason: Optional[str], records: Sequence[Mapping[str, Any]]) -> None:
        result = self.body.get("reduction")
        plan = {
            "suite": self.suite, "task_id": self.task_id, "instruction": self.config["instruction"],
            "failing_start": self.failing_index,
            "references": [ref["start_index"] for ref in self.config["references"]],
            "order": list(self.config["order"]), "order_source": self.config["order_source"],
            "hypothesis": copy.deepcopy(self.config["hypothesis"]),
        }
        self.body.update(plan=plan, differences_match_plan=self.differences_match_plan,
                         videos={}, minimal_candidate=None, differences=None, hypothesis_verdict=None)
        if result is None:
            return
        chosen = result.get("reference")
        if chosen is not None:
            self.body["differences"] = next(
                (ref["differences"] for ref in self.references if ref["id"] == chosen), None)
        candidates = result.get("candidates") or []
        by_index = {c["index"]: c for c in candidates}

        def video(role: str, candidate: Optional[Mapping[str, Any]], outcome: str) -> None:
            if candidate is None:
                return
            record = _first_valid(records, key=candidate["key"], outcome=outcome)
            if record is not None:
                self.body["videos"][role] = {
                    "case_id": record["case_id"], "outcome": record["outcome"],
                    "video": (record.get("artifacts") or {}).get("video"), "key": candidate["key"]}

        video("original", next((c for c in candidates if c["role"] == "failing"), None), "policy_failure")
        video("reference", next((c for c in candidates if c["role"] == "reference"
                                 and c["reference"] == chosen and c["gate_met"]), None), "success")
        final = by_index.get(result.get("final_candidate"))
        if final is not None:
            video("minimal", final, "policy_failure")
            record_path = self.keys.get(final["key"], {}).get("path")
            if record_path is not None:
                try:
                    self.body["minimal_candidate"] = load_scenario_candidate(record_path)
                except (OSError, ValueError):
                    self.body["minimal_candidate"] = None
        selection = result.get("final_selection")
        ranking = self.config["hypothesis"]["ranking"] or self.config["order"]
        if result.get("reduced") and selection and ranking:
            try:
                self.body["hypothesis_verdict"] = hypothesis_verdict(ranking, selection)
            except ValueError:
                self.body["hypothesis_verdict"] = None

    def complete(self, stop_reason: Optional[str]) -> bool:
        result = self.body.get("reduction") or {}
        return stop_reason is None and bool(result.get("reduced"))


DRIVERS = {"scenario-smoke": SmokeDriver, "scenario-screen": ScreenDriver, "scenario-reduce": ReduceDriver}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def write_summary(root: Path, summary: Mapping[str, Any]) -> None:
    target = Path(root) / SUMMARY_NAME
    temporary = Path(root) / ("." + SUMMARY_NAME + ".tmp")
    payload = json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary.write_bytes(payload.encode("utf-8"))
    os.replace(str(temporary), str(target))


_BIG_CONFIG_KEYS = ("layout", "failing", "references", "hypothesis", "instruction", "order")


def _config_echo(config: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in config.items() if key not in _BIG_CONFIG_KEYS}


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def run_scenario(
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
    workers: int = SCENARIO_WORKERS,
    read: Optional[Callable[[Path, Path], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run one scenario mode against a single freshly started 12-worker server; returns the summary.

    ``config`` is the validated mode configuration. The injected ``run_item``, ``failure``
    and ``remaining`` are the bounded runner and latch from ``run_workload``.
    """

    if mode not in SCENARIO_MODES:
        raise ValueError("unsupported scenario mode")
    if write_config is None or load_result is None:
        from scripts import run_failure_search

        write_config = write_config or run_failure_search._write_config
        load_result = load_result or (
            lambda output: run_failure_search._load_stage_results(output, expected_count=1)[0])
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
        "warm_elapsed_seconds": None, "records": [], "not_started": {},
    }  # type: Dict[str, Any]
    started_at = clock()
    scrub = {"companions_removed": 0}

    def build() -> Dict[str, Any]:
        records = sorted(state["records"], key=lambda r: r["case_id"])
        summary = {
            "schema_version": 1, "mode": mode, "suite": suite, "workers": workers,
            "max_batch_size": SCENARIO_MAX_BATCH_SIZE, "config": _config_echo(config),
            "stop_reason": state["stop_reason"],
            "complete": driver.complete(state["stop_reason"]),
            "attempted": len([r for r in records if r.get("started", True)]),
            "valid_count": len([r for r in records if r["status"] == "valid"]),
            "outcomes": _count_outcomes(records),
            "warmup": state["warmup"], "server_argv": state["server_argv"],
            "memory_start": state["memory_start"], "memory_end": state["memory_end"],
            "timing": state["timing"], "startup_seconds": state["startup_seconds"],
            "warm_elapsed_seconds": state["warm_elapsed_seconds"], "total_seconds": state["total_seconds"],
            "not_started": dict(state["not_started"]),
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
    pool = None  # type: Optional[ScenarioPool]
    launch_t = None  # type: Optional[float]
    try:
        if be.run_prefetch(prefetch, clock, progress, extra):
            state["stop_reason"] = "prefetch_failed"
        else:
            state["memory_start"] = dict(snapshot())
            progress("scenario_start", mode=mode, suite=suite, workers=workers, **dict(state["memory_start"]))
            phase_started = clock()
            try:
                with be.started_server(
                    model_factory=model_factory, set_model=set_model, log_root=log_root,
                    max_batch_size=SCENARIO_MAX_BATCH_SIZE, timing_log=timing_path,
                    launch_deadline=launch_deadline,
                ) as (_model, server_argv):
                    state["server_argv"] = server_argv
                    ready_at = clock()
                    state["startup_seconds"] = be._round(ready_at - phase_started)
                    evaluate = make_scenario_evaluate(
                        suite=suite, project_root=project_root, write_config=write_config,
                        load_result=load_result, run_item=run_item, cancel=cancel,
                        item_timeout=item_timeout, clock=clock, ready_at=ready_at,
                        configs_dir=configs, runs_dir=runs, batch_root=batch_root, read=read)
                    pool = ScenarioPool(workers=workers, evaluate=evaluate, remaining=remaining,
                                        item_timeout=item_timeout, cancel=cancel)
                    try:
                        warm, _warm_seconds, skipped = be.run_warmup(
                            evaluate=evaluate, first=driver.warmup_item(), batch_root=batch_root,
                            remaining=remaining, item_timeout=item_timeout, clock=clock,
                            known_outcomes={})
                        state["warmup"] = warm
                        progress("scenario_warmup_done", status=warm.get("status"),
                                 outcome=warm.get("outcome"), duration_seconds=warm.get("duration_seconds"))
                        if skipped:
                            state["stop_reason"] = "deadline_exhausted"
                        elif warm["status"] != "valid":
                            state["stop_reason"] = failure() or "warmup_failed"
                            cancel.set()
                        if state["stop_reason"] is None:
                            launch_t = server_clock()
                            pool.start()
                            ctx = _Context(pool=pool, failure=failure, remaining=remaining, progress=progress,
                                           batch_root=batch_root, suite=suite, workers=workers)
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
        if isinstance(driver, ScreenDriver):
            driver.finish(state["stop_reason"])
        elif isinstance(driver, ReduceDriver):
            driver.finish(state["stop_reason"], state["records"])
        summary = save()
    progress("scenario_summary", mode=mode, stop_reason=summary["stop_reason"],
             complete=summary["complete"], valid=summary["valid_count"], outcomes=summary["outcomes"])
    return summary


def _count_outcomes(records: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts = {}  # type: Dict[str, int]
    for record in records:
        if record["status"] == "valid":
            counts[record["outcome"]] = counts.get(record["outcome"], 0) + 1
    return dict(sorted(counts.items()))


# ---------------------------------------------------------------------------
# The reduced scenario as a case
# ---------------------------------------------------------------------------

CASE_SCHEMA_VERSION = 1


def _fmt(value: float, digits: int = 1) -> str:
    text = "{:.{}f}".format(value, digits)
    return text[:-2] if text.endswith(".0") and digits == 1 else text


def describe_minimal_cause(
    final_selection: Mapping[str, Mapping[str, float]],
    differences: Sequence[Mapping[str, Any]],
    *,
    reference: Any = None,
    bisection_steps: Optional[int] = None,
    reduced: bool = True,
    required_failures: int = 4,
    attempts: int = 5,
) -> str:
    """The minimal cause in one plain sentence.

    Sizes are the final fraction ``t`` of each part's original difference between the
    failing start and the reference, so "of the original" is the measured size.
    """

    rows = {row["entity"]: row for row in differences}
    pieces = []
    for entity, parts in final_selection.items():
        row = rows.get(entity) or {}
        for component, fraction in parts.items():
            if component == "position":
                full = ((row.get("position") or {}).get("distance_m") or 0.0) * 100.0
                pieces.append("moving {} by {} cm (of the original {} cm)".format(
                    entity, _fmt(full * fraction), _fmt(full)))
            elif component == "rotation":
                full = (row.get("rotation") or {}).get("angle_deg") or 0.0
                pieces.append("rotating {} by {} degrees (of the original {})".format(
                    entity, _fmt(full * fraction, 0), _fmt(full, 0)))
            else:
                count = len(row.get("joints") or ())
                pieces.append("moving {} joint{} of {} {}% of the way to their failing values".format(
                    count or "its", "" if count == 1 else "s", entity, _fmt(fraction * 100.0, 0)))
    if not pieces:
        return "No smaller cause than the whole arrangement was established."
    if len(pieces) > 1:
        body = ", ".join(pieces[:-1]) + " and " + pieces[-1]
    else:
        body = pieces[0]
    body = body[0].upper() + body[1:]
    verb = "is" if len(pieces) == 1 else "are"
    sentence = "{} {} enough to make the policy fail".format(body, verb)
    if reference is not None:
        sentence += " from the passing start {}".format(reference)
    sentence += " (at least {} of {} attempts)".format(required_failures, attempts)
    if bisection_steps:
        sentence += "; sizes are resolved to within 1/{} of the original difference".format(2 ** bisection_steps)
    if not reduced:
        sentence += "; the reduction stopped early, so this is the smallest cause found so far"
    return sentence + "."


def build_case(summary: Mapping[str, Any]) -> Dict[str, Any]:
    """A portable case record for a ``scenario-reduce`` summary.

    Holds what the later UI step renders: the suite, task and instruction, the failing
    start and reference, the minimal selection and its sentence, the replay recipe (a
    scenario candidate file, restorable with ``scenario_start``), the original, minimal
    and reference videos, the hypothesis with its mechanical verdict, and an empty
    explanation slot. Raises ``ValueError`` for anything but a ``scenario-reduce`` summary.
    """

    import hashlib

    if not isinstance(summary, Mapping) or summary.get("mode") != "scenario-reduce" \
            or not isinstance(summary.get("plan"), Mapping):
        raise ValueError("a scenario-reduce summary is required")
    plan, reduction = summary["plan"], summary.get("reduction") or {}
    selection = reduction.get("final_selection")
    reference = reduction.get("reference")
    ranking = (plan["hypothesis"].get("ranking") or plan.get("order") or [])
    verdict = None
    if reduction.get("reduced") and selection and ranking:
        try:
            verdict = hypothesis_verdict(ranking, selection)
        except ValueError:
            verdict = None
    identity = json.dumps(
        {"suite": plan["suite"], "task_id": plan["task_id"], "failing": plan["failing_start"],
         "reference": reference, "selection": selection}, sort_keys=True, separators=(",", ":"))
    candidate = summary.get("minimal_candidate")
    hypothesis = plan["hypothesis"]
    return {
        "schema_version": CASE_SCHEMA_VERSION,
        "kind": "scenario_reduction",
        "case_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "suite": plan["suite"],
        "task_id": plan["task_id"],
        "instruction": plan["instruction"],
        "failing_start": plan["failing_start"],
        "reference_start": reference,
        "stop_reason": reduction.get("stop_reason"),
        "reduced": bool(reduction.get("reduced")),
        "minimal": {
            "selection": selection,
            "sentence": describe_minimal_cause(
                selection or {}, summary.get("differences") or [], reference=reference,
                bisection_steps=reduction.get("bisection_steps"), reduced=bool(reduction.get("reduced")),
                required_failures=reduction.get("required_failures", 4), attempts=reduction.get("attempts", 5)),
            "parts": reduction.get("parts"),
            "entity_minimal": reduction.get("entity_minimal"),
        },
        "replay": {
            "candidate": candidate,
            "config": {"suite": plan["suite"], "task_id": plan["task_id"],
                       "scenario_start": {"candidate": "<path of the candidate file>"}},
            "gate": {"attempts": reduction.get("attempts", 5),
                     "required_failures": reduction.get("required_failures", 4)},
        },
        "videos": copy.deepcopy(summary.get("videos") or {}),
        "hypothesis": {
            "text": hypothesis.get("text"), "ranking": list(ranking), "source": hypothesis.get("source"),
            "model": hypothesis.get("model"), "fallback_reason": hypothesis.get("fallback_reason"),
            "verdict": verdict,
        },
        "explanation": None,
        "measurements": {
            "candidates_tested": reduction.get("candidates_tested"),
            "attempts_run": reduction.get("attempts_run"),
            "attempts_skipped": reduction.get("attempts_skipped"),
            "total_seconds": summary.get("total_seconds"),
        },
    }


# ---------------------------------------------------------------------------
# Building workloads
# ---------------------------------------------------------------------------


def build_reduce_workload(plan: Mapping[str, Any], *, run_id: str, deadline_seconds: Optional[int] = None,
                          **options: Any) -> Dict[str, Any]:
    """The ``scenario-reduce`` workload JSON for a plan written by ``plan_scenario_reduction.py``.

    ``options`` may set attempts, required_failures, bisection_steps, max_candidates,
    concurrency and max_references. The deadline defaults to the recommended one.
    """

    allowed = {"attempts", "required_failures", "bisection_steps", "max_candidates", "concurrency",
               "max_references"}
    if set(options) - allowed:
        raise ValueError("unknown reduce option")
    keys = ("suite", "task_id", "instruction", "layout", "failing", "references", "order", "order_source",
            "hypothesis")
    workload = {key: copy.deepcopy(plan[key]) for key in keys}
    workload.update(options)
    workload.update(schema_version=1, mode="scenario-reduce", run_id=run_id)
    if deadline_seconds is None:
        deadline_seconds = recommended_deadline_seconds("scenario-reduce", options)
    workload["deadline_seconds"] = deadline_seconds
    return workload


__all__ = [
    "DEFAULT_SUITE",
    "PoolExecutor",
    "SCENARIO_MODES",
    "SCENARIO_SUITES",
    "SCENARIO_WORKERS",
    "ScenarioConfigError",
    "ScenarioPool",
    "SUMMARY_NAME",
    "build_case",
    "build_reduce_workload",
    "describe_minimal_cause",
    "make_scenario_evaluate",
    "planned_episodes",
    "read_evidence",
    "recommended_deadline_seconds",
    "run_scenario",
    "validate_mode_fields",
]
