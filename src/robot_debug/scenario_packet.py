"""Evidence packet for a scenario reduction case (packet kind ``scenario_reduction``).

The occlusion packets in :mod:`robot_debug.evidence_packet` describe masked episodes;
this one describes a Mode 1 start-state reduction. It is a small, allowlisted projection
of the case record written by :func:`robot_debug.scenario_experiment.build_case`:

* the task instruction and the difference table (how far each entity moved from the
  passing reference);
* the final minimal selection with each part's shrink fraction;
* the model's hypothesis text and ranking;
* the measured result: which of the top-ranked entities were necessary or sufficient,
  and the few reruns that show it, each with a citable id (``c<candidate index>``).

Everything is derived from reruns that already happened. The model that reads the packet
may point at evidence ids and suggest the next bounded experiment; it decides nothing.
The response contract is the existing one (``observations``, ``hypotheses``,
``limitations``, each citing evidence ids), so :mod:`robot_debug.explanation` limits apply.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .evidence_packet import EvidencePacketError, _canonical
from .explanation import ExplanationValidationError, _validate_response

SCENARIO_PACKET_KIND = "scenario_reduction"
SCENARIO_PACKET_VERSION = 1
MAX_DIFFERENCES = 24
MAX_EVIDENCE = 24
MAX_PARTS = 48

_ERROR = "invalid evidence packet"
_NAME = re.compile(r"[A-Za-z0-9_.\-]{1,64}\Z")
_EVIDENCE_ID = re.compile(r"c[0-9]{1,6}\Z")
_LETTERS = {"success": "S", "policy_failure": "F", "invalid_scene": "I"}
_COMPONENTS = ("position", "rotation", "joints")
_VERDICTS = ("confirmed", "necessary_not_sufficient", "sufficient_not_necessary", "not_in_final",
             "inconclusive")
_SCOPES = ("reduced", "entity_minimal_sizes_partial")
_DECISIONS = ("reproduces", "does_not_reproduce", "invalid_scene", "passes")


def _require(condition: bool) -> None:
    if not condition:
        raise EvidencePacketError(_ERROR)


def _keys(value: object, expected: Sequence[str], optional: Sequence[str] = ()) -> Dict[str, Any]:
    _require(type(value) is dict)
    keys = set(value)
    _require(set(expected) <= keys <= set(expected) | set(optional))
    return value


def _text(value: object, limit: int, nullable: bool = False) -> Optional[str]:
    if value is None and nullable:
        return None
    _require(type(value) is str)
    cleaned = " ".join("".join(
        " " if unicodedata.category(c) in ("Cc", "Cf") else c for c in value).split())
    _require(0 < len(cleaned) <= limit)
    return cleaned


def _name(value: object) -> str:
    _require(type(value) is str and _NAME.match(value) is not None)
    return value


def _int(value: object, low: int = 0, high: int = 1_000_000) -> int:
    _require(type(value) is int and low <= value <= high)
    return value


def _number(value: object) -> float:
    _require(type(value) in (int, float) and math.isfinite(value))
    return 0.0 if value == 0 else float(value)


def _bool_or_none(value: object) -> Optional[bool]:
    _require(value is None or type(value) is bool)
    return value


def letters(outcomes: Any) -> str:
    """Outcome letters for a list of outcomes: ``S`` success, ``F`` policy failure, ``I`` invalid scene."""

    if not isinstance(outcomes, (list, tuple)) or not outcomes:
        return "-"
    return " ".join(_LETTERS.get(item, "?") for item in outcomes)


def _selection(value: object) -> Optional[List[Dict[str, Any]]]:
    """A selection ``{entity: {component: t}}`` as a sorted, bounded list of parts."""

    if value is None:
        return None
    _require(type(value) is dict and len(value) <= MAX_PARTS)
    parts = []
    for entity in sorted(value):
        _name(entity)
        components = value[entity]
        _require(type(components) is dict)
        for component in sorted(components):
            _require(component in _COMPONENTS)
            fraction = _number(components[component])
            _require(0.0 <= fraction <= 1.0)
            parts.append({"entity": entity, "component": component, "fraction": round(fraction, 4)})
    _require(len(parts) <= MAX_PARTS)
    return parts


def _difference(row: object) -> Dict[str, Any]:
    entry = _keys(row, ("entity", "kind"), ("position_cm", "rotation_deg", "joints"))
    result: Dict[str, Any] = {"entity": _name(entry["entity"]), "kind": _text(entry["kind"], 16)}
    for field in ("position_cm", "rotation_deg"):
        if field in entry:
            result[field] = round(_number(entry[field]), 3)
    if "joints" in entry:
        joints = entry["joints"]
        _require(type(joints) is list and len(joints) <= 12)
        result["joints"] = []
        for joint in joints:
            item = _keys(joint, ("name", "offset", "unit"))
            result["joints"].append({"name": _text(item["name"], 64), "offset": round(_number(item["offset"]), 3),
                                     "unit": _text(item["unit"], 16)})
    return result


def _measured(value: object) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    measured = _keys(value, ("verdict", "result_scope", "survivors", "entities"))
    _require(measured["verdict"] in _VERDICTS and measured["result_scope"] in _SCOPES)
    survivors = measured["survivors"]
    _require(type(survivors) is list and 1 <= len(survivors) <= MAX_DIFFERENCES)
    entities = measured["entities"]
    _require(type(entities) is list and 1 <= len(entities) <= 5)
    checked = []
    for item in entities:
        entry = _keys(item, ("entity", "rank", "in_final", "necessary", "sufficient", "label", "necessary_basis"))
        _require(entry["label"] in _VERDICTS)
        _require(entry["necessary_basis"] in (None, "exact", "entity_set", "reference", "not_in_final"))
        _require(type(entry["in_final"]) is bool)
        checked.append({"entity": _name(entry["entity"]), "rank": _int(entry["rank"], 1, 1000),
                        "in_final": entry["in_final"], "necessary": _bool_or_none(entry["necessary"]),
                        "sufficient": _bool_or_none(entry["sufficient"]), "label": entry["label"],
                        "necessary_basis": entry["necessary_basis"]})
    return {"verdict": measured["verdict"], "result_scope": measured["result_scope"],
            "survivors": [_name(item) for item in survivors], "entities": checked}


def validate_scenario_packet(packet: object) -> Dict[str, Any]:
    """Validate the exact packet fields and return a detached canonical-order copy."""

    try:
        return _validate(packet)
    except EvidencePacketError:
        raise
    except Exception:
        raise EvidencePacketError(_ERROR) from None


def _validate(packet: object) -> Dict[str, Any]:
    value = _keys(packet, ("schema_version", "kind", "task", "differences", "minimal", "hypothesis",
                           "measured", "evidence"))
    _require(value["schema_version"] == SCENARIO_PACKET_VERSION and type(value["schema_version"]) is int)
    _require(value["kind"] == SCENARIO_PACKET_KIND)
    task = _keys(value["task"], ("suite", "task_id", "instruction", "failing_start", "reference_start"))
    reference = task["reference_start"]
    checked_task = {"suite": _name(task["suite"]), "task_id": _int(task["task_id"], 0, 1000),
                    "instruction": _text(task["instruction"], 400),
                    "failing_start": _int(task["failing_start"], 0, 100_000),
                    "reference_start": None if reference is None else _int(reference, 0, 100_000)}
    differences = value["differences"]
    _require(type(differences) is list and 1 <= len(differences) <= MAX_DIFFERENCES)
    checked_differences = [_difference(row) for row in differences]
    _require(len({row["entity"] for row in checked_differences}) == len(checked_differences))

    minimal = _keys(value["minimal"], ("selection", "sentence", "entity_minimal", "reduced", "stop_reason"))
    _require(type(minimal["entity_minimal"]) is bool and type(minimal["reduced"]) is bool)
    checked_minimal = {"selection": _selection_from_parts(minimal["selection"]),
                       "sentence": _text(minimal["sentence"], 900),
                       "entity_minimal": minimal["entity_minimal"], "reduced": minimal["reduced"],
                       "stop_reason": _text(minimal["stop_reason"], 64)}

    hypothesis = _keys(value["hypothesis"], ("text", "ranking", "source"))
    ranking = hypothesis["ranking"]
    _require(type(ranking) is list and 1 <= len(ranking) <= MAX_DIFFERENCES and len(set(ranking)) == len(ranking))
    checked_hypothesis = {"text": _text(hypothesis["text"], 1200, nullable=True),
                          "ranking": [_name(item) for item in ranking],
                          "source": _text(hypothesis["source"], 32)}

    evidence = value["evidence"]
    _require(type(evidence) is list and len(evidence) <= MAX_EVIDENCE)
    checked_evidence = []
    seen = set()
    for item in evidence:
        entry = _keys(item, ("evidence_id", "phase", "role", "selection", "outcomes", "decision", "meaning"))
        evidence_id = entry["evidence_id"]
        _require(type(evidence_id) is str and _EVIDENCE_ID.match(evidence_id) is not None
                 and evidence_id not in seen)
        seen.add(evidence_id)
        _require(entry["decision"] in _DECISIONS)
        outcomes = _text(entry["outcomes"], 40)
        _require(re.fullmatch(r"(?:[SFI?-])(?: [SFI?])*", outcomes) is not None)
        checked_evidence.append({
            "evidence_id": evidence_id, "phase": _text(entry["phase"], 16), "role": _text(entry["role"], 16),
            "selection": _selection_from_parts(entry["selection"], nullable=True), "outcomes": outcomes,
            "decision": entry["decision"], "meaning": _text(entry["meaning"], 600)})
    checked_evidence.sort(key=lambda row: int(row["evidence_id"][1:]))
    result = {"schema_version": SCENARIO_PACKET_VERSION, "kind": SCENARIO_PACKET_KIND, "task": checked_task,
              "differences": checked_differences, "minimal": checked_minimal, "hypothesis": checked_hypothesis,
              "measured": _measured(value["measured"]), "evidence": checked_evidence}
    _canonical(result)
    return result


def _selection_from_parts(value: object, nullable: bool = False) -> Optional[List[Dict[str, Any]]]:
    if value is None:
        _require(nullable)
        return None
    _require(type(value) is list and len(value) <= MAX_PARTS)
    parts = []
    for item in value:
        part = _keys(item, ("entity", "component", "fraction"))
        _require(part["component"] in _COMPONENTS)
        fraction = _number(part["fraction"])
        _require(0.0 <= fraction <= 1.0)
        parts.append({"entity": _name(part["entity"]), "component": part["component"],
                      "fraction": round(fraction, 4)})
    return parts


def evidence_meaning(phase: str, role: str, parts: Optional[List[Dict[str, Any]]], outcomes: str,
                     decision: str) -> str:
    """One plain sentence a reader (or a small model) cannot misread: which scene ran and what happened.

    Added after Nemotron Nano read "changed only the soup, S S" as "reverting the soup did not
    restore success" (October 13): the bare codes were too easy to invert.
    """

    counts = "{} of {} attempts failed".format(outcomes.split().count("F"), len(outcomes.split()))
    if role == "failing":
        scene = "The failing start itself"
    elif role == "reference":
        scene = "The passing reference start itself"
    elif parts:
        moved = ", ".join("{} {} {:g}%".format(part["entity"], part["component"], round(part["fraction"] * 100, 1))
                          for part in parts)
        scene = "The passing reference start with only these differences applied ({}); every other entity at the reference".format(moved)
    else:
        scene = "The passing reference start with no differences applied"
    verdict = {
        "reproduces": "so this scene DOES reproduce the failure",
        "does_not_reproduce": "so this scene does NOT reproduce the failure (the task mostly succeeded)",
        "passes": "so this scene passes as a reference should",
        "fails": "so this reference does not pass reliably",
        "invalid_scene": "so this scene was physically invalid and says nothing about the policy",
    }.get(decision, "decision: " + decision)
    return "{}: {} ({}), {}.".format(scene, outcomes, counts, verdict)


def make_scenario_packet(case: Mapping[str, Any]) -> Dict[str, Any]:
    """The bounded packet for a ``scenario_reduction`` case record. Raises ``EvidencePacketError``."""

    try:
        _require(isinstance(case, Mapping) and case.get("kind") == SCENARIO_PACKET_KIND)
        minimal = case["minimal"]
        hypothesis = case["hypothesis"]
        measurement = hypothesis.get("measurement")
        measured = None
        if measurement is not None:
            measured = {
                "verdict": measurement["verdict"], "result_scope": measurement["result_scope"],
                "survivors": list(measurement["survivors"]),
                "entities": [{key: item[key] for key in (
                    "entity", "rank", "in_final", "necessary", "sufficient", "label", "necessary_basis")}
                    for item in measurement["entities"]]}
        evidence = []
        for item in case.get("evidence") or []:
            parts = _selection(item.get("selection"))
            outcomes = letters(item.get("outcomes"))
            evidence.append({
                "evidence_id": "c{}".format(item["index"]), "phase": item["phase"], "role": item["role"],
                "selection": parts, "outcomes": outcomes, "decision": item["decision"],
                "meaning": evidence_meaning(item["phase"], item["role"], parts, outcomes, item["decision"])})
        packet = {
            "schema_version": SCENARIO_PACKET_VERSION, "kind": SCENARIO_PACKET_KIND,
            "task": {"suite": case["suite"], "task_id": case["task_id"], "instruction": case["instruction"],
                     "failing_start": case["failing_start"], "reference_start": case.get("reference_start")},
            "differences": list(case.get("differences") or []),
            "minimal": {"selection": _selection(minimal.get("selection")) or [],
                        "sentence": minimal["sentence"], "entity_minimal": bool(minimal.get("entity_minimal")),
                        "reduced": bool(case.get("reduced")), "stop_reason": case.get("stop_reason") or "unknown"},
            "hypothesis": {"text": hypothesis.get("text"), "ranking": list(hypothesis.get("ranking") or []),
                           "source": hypothesis.get("source") or "unknown"},
            "measured": measured,
            "evidence": evidence,
        }
        return validate_scenario_packet(packet)
    except Exception:
        raise EvidencePacketError(_ERROR) from None


def scenario_packet_identity(packet: Mapping[str, Any]) -> str:
    """SHA-256 of the validated compact sorted UTF-8 JSON."""

    return hashlib.sha256(_canonical(validate_scenario_packet(dict(packet)))).hexdigest()


def evidence_ids(packet: Mapping[str, Any]) -> List[str]:
    return [item["evidence_id"] for item in validate_scenario_packet(dict(packet))["evidence"]]


def validate_scenario_explanation(response_json: object, packet: Mapping[str, Any]) -> Dict[str, Any]:
    """Check JSON structure and citation membership against the packet's evidence ids.

    The contract is the one for occlusion explanations (at most 4 observations, 3 hypotheses and
    6 limitations, each text at most 600 characters, every citation an id in the packet); this checks
    structure, not whether the prose is true.
    """

    validated = validate_scenario_packet(dict(packet))
    shim = {"episodes": [{"evidence_id": item["evidence_id"]} for item in validated["evidence"]]}
    try:
        return _validate_response(response_json, shim)
    except Exception:
        raise ExplanationValidationError("invalid explanation") from None


SCENARIO_SYSTEM_PROMPT = (
    "You help a robotics engineer review one finished delta-debugging run on a simulated "
    "robot-policy failure. The policy fails one LIBERO task from one start state and succeeds from "
    "a nearby reference start. The user message is JSON. task has the instruction. differences "
    "lists, per entity (the robot or one object), how far its start pose differs between the two "
    "starts (position_cm, rotation_deg, joints). minimal.selection lists the parts that were "
    "moved from the reference toward the failing start; fraction 1 is the full difference and "
    "smaller fractions are the shrunk sizes that still failed. minimal.reduced says whether sizes "
    "were fully shrunk; entity_minimal means no whole entity could be removed. hypothesis is what a "
    "model predicted before the runs, with its ranking. measured is arithmetic from reruns: for "
    "each top-ranked entity, necessary is true when the final selection without it did not "
    "reproduce the failure, sufficient is true when changing only that entity reproduced it; "
    "null means not tested. evidence lists those reruns by evidence_id; outcomes use S for "
    "success, F for policy failure, I for an invalid scene, one letter per attempt; each evidence "
    "item's meaning states in plain words which scene ran and whether it reproduced the failure, "
    "and is authoritative: a scene with only one entity applied tests whether that entity is "
    "sufficient, not what happens when it is reverted. "
    "Return exactly one JSON object with keys schema_version (the integer 1), observations, "
    "hypotheses and limitations. observations: 2 to 4 objects with keys text and evidence_ids, "
    "plain factual statements a reviewer can check against measured and evidence, saying what "
    "the prediction got right and what it missed. hypotheses: 1 to 3 objects with keys text and "
    "evidence_ids, each a testable idea about why the failure needs the surviving entities "
    "together, naming one next bounded experiment (a specific entity and size to rerun); these "
    "are not conclusions. limitations: 1 to 3 strings saying the result is a local minimum from a "
    "limited number of reruns, one task and one start pair, that necessary and sufficient are "
    "relative to this final selection, that there is no causal proof and that human review is "
    "required. Copy evidence_ids exactly from evidence. Use only entity names and numbers that "
    "appear in the input. Keep each text under 400 characters."
)

__all__ = [
    "MAX_DIFFERENCES", "MAX_EVIDENCE", "SCENARIO_PACKET_KIND", "SCENARIO_PACKET_VERSION",
    "SCENARIO_SYSTEM_PROMPT", "evidence_ids", "letters", "make_scenario_packet", "scenario_packet_identity",
    "validate_scenario_explanation", "validate_scenario_packet",
]
