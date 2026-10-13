"""Reference choice and the hypothesis step of scenario reduction (ADR 0028).

Pure helpers around the reducer; nothing here talks to the network or the
simulator:

* ``nearest_reference``: the starts of the same task that passed the screen,
  nearest first by summed object distance (position in cm plus rotation in
  degrees / 10), so the reducer starts from the most similar passing scene;
* ``build_hypothesis_prompt``: the text sent to Nemotron: the task
  instruction and the difference table only (no images, no identifiers, no
  paths);
* ``parse_hypothesis_reply``: strict parsing of the model's
  ``{"ranking": [...], "hypothesis": "..."}``; anything unexpected raises
  ``HypothesisError`` with a short reason so the caller can fall back to the
  fixed order (largest difference first) and say why;
* ``hypothesis_verdict``: the mechanical comparison of the model's top-ranked
  entity with the entities that survived reduction (``confirmed``, ``partly``,
  ``refuted``). Only simulator reruns decide what is in the reduced case; the
  verdict is arithmetic, not an LLM judgement.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .scenario_state import ScenarioStateError, scenario_distance, validate_layout, validate_state

MAX_HYPOTHESIS_CHARS = 1200
_MAX_INSTRUCTION_CHARS = 400
_NAME = re.compile(r"[A-Za-z0-9_.\-]{1,64}\Z")

SYSTEM_PROMPT = (
    "You help a robotics engineer find why a simulated robot policy fails one task from "
    "a manipulation benchmark. The policy fails from one start state and succeeds from a "
    "nearby reference start. The user message is JSON with task_instruction and "
    "differences: one entry per entity (the robot, or one object) whose start pose differs "
    "from the reference. position_cm is how far the entity is moved, rotation_deg how far "
    "it is turned, joints the joint offsets. Return exactly one JSON object with keys "
    "ranking and hypothesis. ranking is an array containing every entity name from "
    "differences exactly once, most likely cause of the failure first. hypothesis is one "
    "short paragraph (under 600 characters) naming which difference you expect to matter "
    "and why, framed as a testable guess that the simulator will check; it is not a "
    "conclusion. Use only entity names and numbers that appear in the input."
)


class HypothesisError(ValueError):
    """A model reply was unusable. The message is a short, fixed reason code."""


def _lookup(mapping: Mapping[Any, Any], key: int) -> Any:
    for candidate in (key, str(key)):
        if candidate in mapping:
            return mapping[candidate]
    return None


def _outcomes_of(entry: Any) -> List[str]:
    if isinstance(entry, Mapping):
        entry = entry.get("outcomes")
    if isinstance(entry, (str, bytes)) or not isinstance(entry, Sequence):
        return []
    return [str(item) for item in entry]


def nearest_reference(
    task_id: int,
    failing_index: int,
    screen_results: Mapping[Any, Any],
    states: Mapping[Any, Any],
    layout: Mapping[str, Any],
    count: int = 3,
) -> List[Dict[str, Any]]:
    """Passing starts of ``task_id`` ranked by distance to the failing start.

    ``screen_results[task_id][start_index]`` holds the screen outcomes of a start
    (a list, or ``{"outcomes": [...]}``) and ``states[task_id][start_index]`` its
    flat start state; JSON-style string keys are accepted. A start qualifies when
    it has outcomes, every one a ``success``, and a state. Returns up to
    ``count`` entries ``{"start_index", "distance", "outcomes"}``, nearest first
    (ties by start index); an empty list when nothing passed.
    """

    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive integer")
    validate_layout(dict(layout))
    results = _lookup(screen_results, task_id)
    task_states = _lookup(states, task_id)
    if not isinstance(results, Mapping) or not isinstance(task_states, Mapping):
        raise ValueError("the task has no screen results or states")
    failing_state = _lookup(task_states, failing_index)
    if failing_state is None:
        raise ValueError("the failing start has no state")
    failing_state = validate_state(failing_state, layout)
    ranked = []
    for key in results:
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if index == failing_index:
            continue
        outcomes = _outcomes_of(results[key])
        state = _lookup(task_states, index)
        if not outcomes or any(item != "success" for item in outcomes) or state is None:
            continue
        distance = scenario_distance(failing_state, validate_state(state, layout), layout)
        ranked.append({"start_index": index, "distance": distance, "outcomes": outcomes})
    ranked.sort(key=lambda item: (item["distance"], item["start_index"]))
    return ranked[:count]


def _clean_text(value: str, limit: int) -> str:
    kept = "".join(" " if unicodedata.category(c) in ("Cc", "Cf") else c for c in value)
    return " ".join(kept.split())[:limit]


def build_hypothesis_prompt(instruction: str, differences: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    """The system and user messages for the hypothesis call.

    The user message carries the cleaned task instruction and, per entity, the
    rounded difference sizes. No images, start indices, hashes or paths are
    included. Raises ``ValueError`` for an empty table or an unusable entity name.
    """

    if type(instruction) is not str or not _clean_text(instruction, _MAX_INSTRUCTION_CHARS):
        raise ValueError("instruction must be a non-empty string")
    if isinstance(differences, (str, bytes)) or not differences:
        raise ValueError("differences must be a non-empty list")
    entries = []
    seen = set()
    for row in differences:
        name = row.get("entity") if isinstance(row, Mapping) else None
        if type(name) is not str or _NAME.match(name) is None or name in seen:
            raise ValueError("difference rows need unique, plain entity names")
        seen.add(name)
        entry: Dict[str, Any] = {"entity": name, "kind": row.get("kind", "object")}
        if row.get("position"):
            entry["position_cm"] = round(float(row["position"]["distance_m"]) * 100.0, 2)
        if row.get("rotation"):
            entry["rotation_deg"] = round(float(row["rotation"]["angle_deg"]), 1)
        if row.get("joints"):
            entry["joints"] = [
                {"name": str(joint["name"]), "offset": round(float(joint["offset"]), 3),
                 "unit": str(joint["unit"])} for joint in row["joints"]]
        entries.append(entry)
    user = json.dumps(
        {"task_instruction": _clean_text(instruction, _MAX_INSTRUCTION_CHARS), "differences": entries},
        ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return {"system": SYSTEM_PROMPT, "user": user}


def _strict_pairs(pairs: List[Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(value: str) -> None:
    raise ValueError("non-finite number")


def parse_hypothesis_reply(content: object, entity_names: Sequence[str]) -> Dict[str, Any]:
    """Validate a model reply against the entities it should rank.

    Returns ``{"ranking", "hypothesis", "completed"}`` where ``ranking`` covers
    every entity (names the model left out are appended in the given
    ``entity_names`` order and listed in ``completed``). Raises
    ``HypothesisError`` with one of ``invalid_json``, ``invalid_shape``,
    ``unknown_entity``, ``duplicate_entity`` or ``invalid_hypothesis``.
    """

    if type(content) is not str:
        raise HypothesisError("invalid_json")
    try:
        value = json.loads(content, object_pairs_hook=_strict_pairs, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise HypothesisError("invalid_json") from None
    if type(value) is not dict or set(value) != {"ranking", "hypothesis"}:
        raise HypothesisError("invalid_shape")
    ranking, text = value["ranking"], value["hypothesis"]
    if type(ranking) is not list or not ranking or any(type(item) is not str for item in ranking):
        raise HypothesisError("invalid_shape")
    known = set(entity_names)
    if any(item not in known for item in ranking):
        raise HypothesisError("unknown_entity")
    if len(set(ranking)) != len(ranking):
        raise HypothesisError("duplicate_entity")
    if type(text) is not str or not text.strip() or len(text) > MAX_HYPOTHESIS_CHARS:
        raise HypothesisError("invalid_hypothesis")
    if any(unicodedata.category(c) in ("Cc", "Cf") and c not in "\n\t" for c in text):
        raise HypothesisError("invalid_hypothesis")
    completed = [name for name in entity_names if name not in set(ranking)]
    return {"ranking": ranking + completed, "hypothesis": text.strip(), "completed": completed}


def hypothesis_verdict(ranking: Sequence[str], reduced_selection: Mapping[str, Any]) -> str:
    """Compare the model's top-ranked entity with the entities that survived.

    ``confirmed``: the top-ranked entity is the only survivor (whatever parts of
    it survive). ``partly``: it is one of several survivors. ``refuted``: it did
    not survive. Raises ``ValueError`` for an empty ranking or an empty
    reduction (an empty selection is the passing reference, not a cause).
    """

    if isinstance(ranking, (str, bytes)) or not ranking:
        raise ValueError("ranking must not be empty")
    survivors = [name for name, parts in reduced_selection.items() if parts]
    if not survivors:
        raise ValueError("the reduced selection is empty")
    top = ranking[0]
    if top not in survivors:
        return "refuted"
    return "confirmed" if len(survivors) == 1 else "partly"


__all__ = [
    "HypothesisError", "MAX_HYPOTHESIS_CHARS", "SYSTEM_PROMPT", "build_hypothesis_prompt",
    "hypothesis_verdict", "nearest_reference", "parse_hypothesis_reply",
]
