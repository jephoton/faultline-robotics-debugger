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
  verdict is arithmetic, not an LLM judgement;
* ``measure_hypothesis``: for the model's top-ranked entities, whether each is
  *necessary* (the final selection without it did not reproduce) and *sufficient*
  (it alone reproduced), read only from candidates the reduction already ran.
  It keeps the half of a prediction that was right when the reduction stopped
  early, or when an entity is necessary without being enough on its own.
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
    failing_index: Optional[int],
    screen_results: Mapping[Any, Any],
    states: Mapping[Any, Any],
    layout: Mapping[str, Any],
    count: int = 3,
    failing_state: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Passing starts of ``task_id`` ranked by distance to the failing start.

    ``failing_state`` is the failing start's flat state when it is not one of the screened starts (an
    imported start): ``failing_index`` may then be ``None`` and nothing is skipped by index.

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
    if failing_state is None:
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


def _compact_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"entity": row.get("entity"), "kind": row.get("kind", "object")}
    if row.get("position"):
        entry["position_cm"] = round(float(row["position"]["distance_m"]) * 100.0, 2)
    if row.get("rotation"):
        entry["rotation_deg"] = round(float(row["rotation"]["angle_deg"]), 1)
    if row.get("joints"):
        entry["joints"] = [
            {"name": str(joint["name"]), "offset": round(float(joint["offset"]), 3),
             "unit": str(joint["unit"])} for joint in row["joints"]]
    return entry


def compact_differences(differences: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The difference table as small rounded rows (the shape the model and the case record use).

    Each row keeps ``entity``, ``kind`` and, when present, ``position_cm``,
    ``rotation_deg`` and ``joints`` (name, offset, unit); distances, offsets in metres and
    joint types are dropped. Rows that are not mappings are skipped.
    """

    return [_compact_row(row) for row in differences or () if isinstance(row, Mapping)]


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
        entries.append(_compact_row(row))
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


_INFORMATIVE = ("reproduces", "does_not_reproduce")
_TOLERANCE = 1e-9
TOP_K = 3


def _applied(selection: Any) -> Dict[str, Dict[str, float]]:
    """``{entity: {component: t}}`` for the parts that are applied (t > 0)."""

    applied: Dict[str, Dict[str, float]] = {}
    if not isinstance(selection, Mapping):
        return applied
    for entity, parts in selection.items():
        if not isinstance(parts, Mapping):
            continue
        kept = {}
        for component, t in parts.items():
            if isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0:
                kept[str(component)] = float(t)
        if kept:
            applied[str(entity)] = kept
    return applied


def _same_sizes(left: Mapping[str, Mapping[str, float]], right: Mapping[str, Mapping[str, float]]) -> bool:
    if set(left) != set(right):
        return False
    for entity, parts in left.items():
        if set(parts) != set(right[entity]):
            return False
        if any(abs(t - right[entity][component]) > _TOLERANCE for component, t in parts.items()):
            return False
    return True


def _same_parts(left: Mapping[str, Mapping[str, float]], right: Mapping[str, Mapping[str, float]]) -> bool:
    return set(left) == set(right) and all(set(left[name]) == set(right[name]) for name in left)


def _reproduced(matches: Sequence[Mapping[str, Any]]) -> Optional[bool]:
    """True when some match reproduced, False when every informative one did not, None if none is informative."""

    decisions = [match["decision"] for match in matches if match.get("decision") in _INFORMATIVE]
    if not decisions:
        return None
    return "reproduces" in decisions


def _indices(matches: Sequence[Mapping[str, Any]]) -> List[int]:
    return sorted(match["index"] for match in matches if isinstance(match.get("index"), int))


def _measure_entity(entity: str, rank: int, final: Mapping[str, Mapping[str, float]],
                    hybrids: Sequence[Mapping[str, Any]], reduction: Mapping[str, Any]) -> Dict[str, Any]:
    survivors = list(final)
    in_final = entity in final

    # Sufficient: a tested candidate that changed only this entity.
    singles = [c for c in hybrids if set(c["_applied"]) == {entity} and c.get("decision") in _INFORMATIVE]
    reproduced = [c for c in singles if c["decision"] == "reproduces"]
    if reproduced:
        sufficient: Optional[bool] = True
        sufficient_basis = _indices(reproduced)
    elif singles:
        sufficient, sufficient_basis = False, _indices(singles)
    else:
        sufficient, sufficient_basis = None, []

    # Necessary, relative to the final selection: take just this entity out of it.
    necessary: Optional[bool]
    how: Optional[str]
    necessary_indices: List[int] = []
    candidates = [c for c in reduction.get("candidates") or [] if isinstance(c, Mapping)]
    if not in_final:
        necessary, how = False, "not_in_final"
        final_candidate = next((c for c in candidates if c.get("index") == reduction.get("final_candidate")), None)
        if final_candidate is not None:
            necessary_indices = _indices([final_candidate])
    else:
        target = {name: parts for name, parts in final.items() if name != entity}
        if not target:
            gates = [c for c in candidates if c.get("role") == "reference" and c.get("decision") == "passes"
                     and (reduction.get("reference") is None or c.get("reference") == reduction.get("reference"))]
            if gates:
                necessary, how, necessary_indices = True, "reference", _indices(gates)
            else:
                necessary, how = None, None
        else:
            exact = [c for c in hybrids if _same_sizes(c["_applied"], target) and c.get("decision") in _INFORMATIVE]
            loose = [c for c in hybrids if c.get("phase") == "ddmin" and _same_parts(c["_applied"], target)
                     and c.get("decision") in _INFORMATIVE]
            chosen, how = (exact, "exact") if exact else (loose, "entity_set")
            repro = _reproduced(chosen)
            if repro is None:
                necessary, how = None, None
            else:
                necessary, necessary_indices = not repro, _indices(chosen)

    if not in_final:
        label = "not_in_final"
    elif necessary is True and sufficient is True:
        label = "confirmed" if survivors == [entity] else "inconclusive"
    elif necessary is True and sufficient is False:
        label = "necessary_not_sufficient"
    elif necessary is False and sufficient is True:
        label = "sufficient_not_necessary"
    else:
        label = "inconclusive"
    return {
        "entity": entity, "rank": rank, "in_final": in_final,
        "sufficient": sufficient, "necessary": necessary, "necessary_basis": how,
        "basis": {"sufficient": sufficient_basis, "necessary": necessary_indices},
        "label": label,
    }


def measure_hypothesis(ranking: Sequence[str], reduction: Mapping[str, Any], top: int = TOP_K) -> Dict[str, Any]:
    """Was the model's top suspect necessary, sufficient, both or neither?

    Reads only candidates the reduction already ran (no new runs). For each of the
    first ``top`` ranked entities it reports ``sufficient`` (a tested candidate that
    changed only that entity reproduced: True; was tested and did not: False; never
    tested: None), ``necessary`` relative to the final selection (the final selection
    without that entity did not reproduce: True; reproduced: False; not tested: None),
    ``in_final``, a ``label`` and the candidate indices behind each answer.
    ``necessary_basis`` says how the complement was matched: ``exact`` (same parts and
    sizes), ``entity_set`` (a ddmin-phase candidate with the same entities and parts but
    other sizes), ``reference`` (the final selection is that entity alone, so removing it
    gives the passing reference) or ``not_in_final`` (necessary is False because the
    entity did not survive).

    The result's ``verdict`` is the top-ranked entity's label: ``confirmed`` (necessary,
    sufficient and the only survivor), ``necessary_not_sufficient``,
    ``sufficient_not_necessary``, ``not_in_final`` (refuted) or ``inconclusive``. Also
    returned: ``survivors``, ``ranked_survivors_overlap`` (how many of the ``top_k``
    ranked entities survived) and ``basis`` (the top entity's candidate indices).
    Raises ``ValueError`` for an empty ranking or a reduction without a final selection.
    """

    if isinstance(ranking, (str, bytes)) or not ranking:
        raise ValueError("ranking must not be empty")
    if type(top) is not int or top < 1:
        raise ValueError("top must be a positive integer")
    final = _applied(reduction.get("final_selection"))
    if not final:
        raise ValueError("the reduction has no final selection")
    hybrids = []
    for candidate in reduction.get("candidates") or []:
        if isinstance(candidate, Mapping) and candidate.get("role") == "hybrid" \
                and isinstance(candidate.get("selection"), Mapping):
            hybrids.append(dict(candidate, _applied=_applied(candidate["selection"])))
    considered = list(ranking[:top])
    entities = [_measure_entity(name, position + 1, final, hybrids, reduction)
                for position, name in enumerate(considered)]
    leader = entities[0]
    return {
        "top": leader["entity"],
        "verdict": leader["label"],
        "sufficient": leader["sufficient"],
        "necessary": leader["necessary"],
        "in_final": leader["in_final"],
        "basis": sorted(set(leader["basis"]["sufficient"]) | set(leader["basis"]["necessary"])),
        "survivors": list(final),
        "top_k": len(considered),
        "ranked_survivors_overlap": sum(1 for name in considered if name in final),
        "entities": entities,
    }


__all__ = [
    "HypothesisError", "MAX_HYPOTHESIS_CHARS", "SYSTEM_PROMPT", "build_hypothesis_prompt", "compact_differences",
    "hypothesis_verdict", "measure_hypothesis", "nearest_reference", "parse_hypothesis_reply",
]
