"""Fail-closed scenario start candidates for the LIBERO mode 1 reduction (ADR 0028).

A candidate is one JSON document that names a LIBERO suite and task and carries
one flat MuJoCo start state of that task's own scene (``[time] + qpos + qvel``,
as ``env.get_sim_state()`` returns it). It generalises the two pinned external
demos (ADR 0016) to any state of a supported suite while keeping the same
discipline: exact keys, strict types, finite numbers, bounded sizes and a
SHA-256 over the state that uses the external reset's packing, so the two hashes
are comparable. No scene XML travels in a candidate; the task's own environment
supplies it, so the state length must equal that environment's.

Runs inside the simulator image (Python 3.8) as well as on the workstation, so
this module stays dependency-free and 3.8-compatible.
"""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import unicodedata
from typing import Any, Dict, Iterable, List, Mapping

from robot_debug.external_reset import ExternalResetError, state_sha256

SCHEMA_VERSION = 1
ALLOWED_SUITES = ("libero_object", "libero_10")
CANDIDATE_KEYS = frozenset(
    {"schema_version", "suite", "task_id", "state", "source", "state_sha256"})
MAX_STATE_LENGTH = 4096
MAX_FILE_BYTES = 512 * 1024
MAX_TASK_ID = 1000
MAX_INDEX = 100_000
MAX_APPLIED = 256
MAX_JSON_DEPTH = 4
MAX_JSON_NODES = 4096
MAX_STRING = 256
_INTEGER_LIMIT = 2 ** 53
_HEX = frozenset("0123456789abcdef")


class ScenarioImportError(ValueError):
    """A safe failure at the scenario boundary; it never echoes candidate content."""


class ScenarioStartError(RuntimeError):
    """The simulator did not reproduce a validated scenario state (an infrastructure failure)."""


def _fail(message: str = "invalid scenario candidate") -> None:
    raise ScenarioImportError(message)


def _is_int(value: Any) -> bool:
    return type(value) is int


def _index(value: Any, limit: int) -> int:
    if not _is_int(value) or value < 0 or value > limit:
        _fail()
    return value


def _clean_string(value: str) -> None:
    if len(value) > MAX_STRING or any(unicodedata.category(ch) == "Cc" for ch in value):
        _fail()


def _check_json_value(value: Any, depth: int, budget: List[int]) -> None:
    budget[0] += 1
    if budget[0] > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
        _fail()
    kind = type(value)
    if value is None or kind is bool:
        return
    if kind is int:
        if abs(value) > _INTEGER_LIMIT:
            _fail()
    elif kind is float:
        if not math.isfinite(value):
            _fail()
    elif kind is str:
        _clean_string(value)
    elif kind is list:
        for item in value:
            _check_json_value(item, depth + 1, budget)
    elif kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                _fail()
            _clean_string(key)
            _check_json_value(item, depth + 1, budget)
    else:
        _fail()


def _validate_source(source: Any) -> Dict[str, Any]:
    if type(source) is not dict or type(source.get("kind")) is not str:
        _fail()
    if source["kind"] == "benchmark":
        if set(source) != {"kind", "init_state_index"}:
            _fail()
        return {"kind": "benchmark", "init_state_index": _index(source["init_state_index"], MAX_INDEX)}
    if source["kind"] == "hybrid":
        if set(source) != {"kind", "reference", "failing", "applied"}:
            _fail()
        applied = source["applied"]
        if type(applied) is not list or len(applied) > MAX_APPLIED:
            _fail()
        _check_json_value(applied, 1, [0])
        return {
            "kind": "hybrid",
            "reference": _index(source["reference"], MAX_INDEX),
            "failing": _index(source["failing"], MAX_INDEX),
            "applied": copy.deepcopy(applied),
        }
    _fail()
    raise AssertionError("unreachable")


def _validated_state(state: Any) -> List[float]:
    if type(state) is not list or not 1 <= len(state) <= MAX_STATE_LENGTH:
        _fail()
    values = []
    for item in state:
        if type(item) not in (int, float):
            _fail()
        try:
            number = float(item)
        except (OverflowError, ValueError):
            _fail()
        if not math.isfinite(number):
            _fail()
        values.append(number)
    return values


def validate_scenario_candidate(value: Any) -> Dict[str, Any]:
    """Validate and detach one scenario candidate; raises ``ScenarioImportError`` otherwise."""

    if type(value) is not dict or set(value) != CANDIDATE_KEYS:
        _fail()
    if not _is_int(value["schema_version"]) or value["schema_version"] != SCHEMA_VERSION:
        _fail()
    suite = value["suite"]
    if type(suite) is not str or suite not in ALLOWED_SUITES:
        _fail()
    task_id = _index(value["task_id"], MAX_TASK_ID)
    state = _validated_state(value["state"])
    source = _validate_source(value["source"])
    digest = value["state_sha256"]
    if type(digest) is not str or len(digest) != 64 or any(ch not in _HEX for ch in digest):
        _fail()
    try:
        computed = state_sha256(state)
    except ExternalResetError:
        _fail()
    if computed != digest:
        _fail()
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": suite,
        "task_id": task_id,
        "state": state,
        "source": source,
        "state_sha256": digest,
    }


def check_scenario_target(candidate: Mapping[str, Any], *, suite: str, task_id: int, state_length: int) -> None:
    """The candidate must belong to this suite and task and fit the environment's state."""

    if (candidate["suite"] != suite or candidate["task_id"] != task_id
            or len(candidate["state"]) != state_length):
        _fail("scenario candidate does not match the evaluated suite, task or state length")


def build_candidate(suite: Any, task_id: Any, state: Any, source: Any) -> Dict[str, Any]:
    """Build a validated candidate; numpy arrays and integer entries are normalised to floats."""

    if isinstance(state, (str, bytes)):
        _fail()
    if hasattr(state, "tolist"):
        state = state.tolist()
    try:
        items = list(state)
    except TypeError:
        _fail()
    values = []
    for item in items:
        if isinstance(item, bool):
            _fail()
        try:
            values.append(float(item))
        except (TypeError, ValueError, OverflowError):
            _fail()
    values = _validated_state(values)
    try:
        digest = state_sha256(values)
    except ExternalResetError:
        _fail()
    return validate_scenario_candidate({
        "schema_version": SCHEMA_VERSION,
        "suite": suite,
        "task_id": task_id,
        "state": values,
        "source": source,
        "state_sha256": digest,
    })


def candidate_from_benchmark(suite: Any, task_id: Any, init_state_index: Any, state: Iterable[Any]) -> Dict[str, Any]:
    """A candidate for one benchmark init state (``source.kind == "benchmark"``)."""

    return build_candidate(
        suite, task_id, state, {"kind": "benchmark", "init_state_index": init_state_index})


def _canonical_text(candidate: Mapping[str, Any]) -> str:
    return json.dumps(candidate, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _reject_constant(_name: str) -> None:
    raise ValueError("non-standard JSON constant")


def _object_pairs(pairs: Any) -> Dict[str, Any]:
    result = {}  # type: Dict[str, Any]
    for key, item in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = item
    return result


def load_scenario_candidate(path: Any) -> Dict[str, Any]:
    """Read, strictly parse and validate one candidate file (bounded size, no duplicates, no NaN)."""

    target = Path(path)
    try:
        if not target.is_file():
            _fail()
        with open(str(target), "rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise ScenarioImportError("scenario candidate is unreadable") from None
    if not data or len(data) > MAX_FILE_BYTES:
        _fail()
    try:
        document = json.loads(
            data.decode("utf-8"), object_pairs_hook=_object_pairs, parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ScenarioImportError("invalid scenario candidate") from None
    return validate_scenario_candidate(document)


def write_scenario_candidate(path: Any, candidate: Mapping[str, Any]) -> None:
    """Validate and write one candidate atomically (nothing is written when it is invalid)."""

    checked = validate_scenario_candidate(candidate)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial.json")
    with open(str(temporary), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical_text(checked))
    os.replace(str(temporary), str(target))
