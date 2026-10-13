"""Scenario state model: name the differences between two LIBERO start states.

A LIBERO start state is one flat MuJoCo state vector ``[time] + qpos + qvel``
(``qpos[i]`` at flat index ``1 + i``, ``qvel[j]`` at ``1 + nq + j``). A *layout*
sidecar (one per suite and task, exported by the simulator side) says which
joints own which slice and which entity (the robot, or one object) each joint
belongs to. With that, a start state is a set of named *entities*:

* ``robot`` groups every robot joint (arm and gripper) and is described by its
  joint offsets only;
* every other entity is an object. A free joint gives it a position and a
  rotation; hinge, slide and ball joints (a microwave door, a drawer) give it
  ``joints``.

This module is pure (numpy only, no simulator, no filesystem beyond reading one
layout file). It provides:

* ``differences``: a stable, ordered table of what changed between a failing
  and a reference state, with a noise floor below which a component counts as
  unchanged (position 2 mm, rotation 1 degree, hinge/ball joint 0.5 degree,
  slide joint 2 mm);
* ``hybrid``: the reference state with chosen components moved a fraction ``t``
  of the way towards the failing state (linear for positions and joints, slerp
  for rotations), velocities zeroed and time taken from the reference;
* ``state_hash``: a deterministic hash for caching and replay, identical to the
  external-reset kernel's state hash;
* ``scenario_distance``: how far apart two starts are in object arrangement,
  used to pick the nearest passing reference.

Everything fails closed with ``ScenarioStateError``.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

SCHEMA_VERSION = 1
POSITION_FLOOR_M = 0.002
ROTATION_FLOOR_DEG = 1.0
JOINT_FLOOR_DEG = 0.5
SLIDE_FLOOR_M = 0.002
COMPONENTS = ("position", "rotation", "joints")
ROBOT = "robot"

_QPOS_WIDTH = {"free": 7, "hinge": 1, "slide": 1, "ball": 4}
_QVEL_WIDTH = {"free": 6, "hinge": 1, "slide": 1, "ball": 3}
_LAYOUT_KEYS = {"schema_version", "suite", "task_id", "state_length", "nq", "nv", "joints"}
_JOINT_KEYS = {"name", "type", "qpos_adr", "qvel_adr", "entity"}
_PARALLEL_DOT = 0.9995


class ScenarioStateError(ValueError):
    """A layout, state or selection is malformed. Never carries private data."""


def _is_int(value: object) -> bool:
    return type(value) is int


def _is_number(value: object) -> bool:
    return (isinstance(value, (int, float, np.integer, np.floating))
            and not isinstance(value, (bool, np.bool_)) and math.isfinite(float(value)))


# --- layout --------------------------------------------------------------------


def validate_layout(layout: object) -> Dict[str, Any]:
    """Return ``layout`` unchanged after checking every field and slice.

    The joints must tile ``qpos`` and ``qvel`` exactly (no gap, no overlap),
    names must be unique, and an entity may own at most one free joint.
    """

    if type(layout) is not dict or set(layout) != _LAYOUT_KEYS:
        raise ScenarioStateError("layout must be an object with the exact layout keys")
    if layout["schema_version"] != SCHEMA_VERSION or not _is_int(layout["schema_version"]):
        raise ScenarioStateError("unsupported layout schema_version")
    if type(layout["suite"]) is not str or not layout["suite"]:
        raise ScenarioStateError("layout suite must be a non-empty string")
    if not _is_int(layout["task_id"]) or layout["task_id"] < 0:
        raise ScenarioStateError("layout task_id must be a non-negative integer")
    for key in ("state_length", "nq", "nv"):
        if not _is_int(layout[key]) or layout[key] < 0:
            raise ScenarioStateError("layout {} must be a non-negative integer".format(key))
    nq, nv = layout["nq"], layout["nv"]
    if layout["state_length"] != 1 + nq + nv:
        raise ScenarioStateError("layout state_length must equal 1 + nq + nv")
    joints = layout["joints"]
    if type(joints) is not list or not joints:
        raise ScenarioStateError("layout joints must be a non-empty list")

    names = set()
    qpos_used = [False] * nq
    qvel_used = [False] * nv
    free_owners = set()
    for joint in joints:
        if type(joint) is not dict or set(joint) != _JOINT_KEYS:
            raise ScenarioStateError("each joint must be an object with the exact joint keys")
        name, kind, entity = joint["name"], joint["type"], joint["entity"]
        if type(name) is not str or not name or name in names:
            raise ScenarioStateError("joint names must be unique non-empty strings")
        names.add(name)
        if kind not in _QPOS_WIDTH:
            raise ScenarioStateError("unsupported joint type")
        if type(entity) is not str or not entity:
            raise ScenarioStateError("joint entity must be a non-empty string")
        if kind == "free":
            if entity in free_owners:
                raise ScenarioStateError("an entity may own at most one free joint")
            free_owners.add(entity)
        for key, width, used, limit in (
            ("qpos_adr", _QPOS_WIDTH[kind], qpos_used, nq),
            ("qvel_adr", _QVEL_WIDTH[kind], qvel_used, nv),
        ):
            address = joint[key]
            if not _is_int(address) or address < 0 or address + width > limit:
                raise ScenarioStateError("joint {} is outside the state".format(key))
            if any(used[address:address + width]):
                raise ScenarioStateError("joints overlap in the state vector")
            used[address:address + width] = [True] * width
    if not all(qpos_used) or not all(qvel_used):
        raise ScenarioStateError("joints must cover every qpos and qvel entry")
    return layout


def load_layout(path: Path) -> Dict[str, Any]:
    """Read and validate a layout sidecar file."""

    try:
        layout = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ScenarioStateError("layout file is unreadable") from None
    return validate_layout(layout)


@dataclass(frozen=True)
class Entity:
    """One named part of a start state: the robot, or a single object."""

    name: str
    kind: str                      # "robot" or "object"
    joints: Tuple[Mapping[str, Any], ...]

    @property
    def free(self) -> Optional[Mapping[str, Any]]:
        for joint in self.joints:
            if joint["type"] == "free":
                return joint
        return None

    @property
    def plain_joints(self) -> Tuple[Mapping[str, Any], ...]:
        return tuple(joint for joint in self.joints if joint["type"] != "free")

    @property
    def components(self) -> Tuple[str, ...]:
        parts: List[str] = []
        if self.free is not None:
            parts += ["position", "rotation"]
        if self.plain_joints:
            parts.append("joints")
        return tuple(parts)


def entities(layout: Mapping[str, Any]) -> List[Entity]:
    """Entities in a stable order: the robot first, then objects as laid out."""

    validate_layout(dict(layout))
    order: List[str] = []
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for joint in layout["joints"]:
        if joint["entity"] not in grouped:
            grouped[joint["entity"]] = []
            order.append(joint["entity"])
        grouped[joint["entity"]].append(joint)
    if ROBOT in grouped:
        order.remove(ROBOT)
        order.insert(0, ROBOT)
    return [Entity(name, ROBOT if name == ROBOT else "object", tuple(grouped[name]))
            for name in order]


def validate_state(state: Sequence[float], layout: Mapping[str, Any]) -> np.ndarray:
    """Return ``state`` as a float64 vector after checking length and finiteness."""

    try:
        vector = np.array(state, dtype=np.float64)
    except (TypeError, ValueError):
        raise ScenarioStateError("state must be a vector of numbers") from None
    if vector.ndim != 1 or vector.shape[0] != layout["state_length"]:
        raise ScenarioStateError("state length does not match the layout")
    if not np.all(np.isfinite(vector)):
        raise ScenarioStateError("state contains non-finite values")
    return vector


# --- quaternion helpers (MuJoCo order: w, x, y, z) ------------------------------


def _unit(quaternion: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(quaternion))
    if not norm > 0.0 or not math.isfinite(norm):
        raise ScenarioStateError("quaternion has no direction")
    return quaternion / norm


def rotation_angle_deg(first: np.ndarray, second: np.ndarray) -> float:
    """Angle between two orientations in degrees; ``q`` and ``-q`` are the same.

    Uses ``4 * atan2(|q0 - q1|, |q0 + q1|)`` for unit quaternions with the sign
    chosen so the dot product is non-negative, which stays accurate for tiny
    angles where ``acos`` of a dot product loses precision.
    """

    q0, q1 = _unit(np.asarray(first, dtype=np.float64)), _unit(np.asarray(second, dtype=np.float64))
    if float(np.dot(q0, q1)) < 0.0:
        q1 = -q1
    angle = 4.0 * math.atan2(float(np.linalg.norm(q0 - q1)), float(np.linalg.norm(q0 + q1)))
    return math.degrees(angle)


def slerp(first: np.ndarray, second: np.ndarray, t: float) -> np.ndarray:
    """Spherical interpolation along the shortest path; the result has unit norm."""

    q0, q1 = _unit(np.asarray(first, dtype=np.float64)), _unit(np.asarray(second, dtype=np.float64))
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1, dot = -q1, -dot
    if dot > _PARALLEL_DOT:
        return _unit(q0 + t * (q1 - q0))
    theta = math.acos(min(1.0, dot))
    sine = math.sin(theta)
    return _unit((math.sin((1.0 - t) * theta) / sine) * q0 + (math.sin(t * theta) / sine) * q1)


# --- differences ---------------------------------------------------------------


def _joint_offset(joint: Mapping[str, Any], failing: np.ndarray,
                  reference: np.ndarray) -> Tuple[float, str, float]:
    """(signed offset, unit, floor) of one non-free joint in degrees or metres."""

    address = 1 + joint["qpos_adr"]
    if joint["type"] == "hinge":
        return math.degrees(failing[address] - reference[address]), "deg", JOINT_FLOOR_DEG
    if joint["type"] == "slide":
        return float(failing[address] - reference[address]), "m", SLIDE_FLOOR_M
    return (rotation_angle_deg(failing[address:address + 4], reference[address:address + 4]),
            "deg", JOINT_FLOOR_DEG)


def _score(position_m: float, rotation_deg: float, joints: Sequence[Dict[str, Any]]) -> float:
    """Summed difference: centimetres plus degrees / 10 (the nearest-reference metric)."""

    total = position_m * 100.0 + rotation_deg / 10.0
    for joint in joints:
        total += abs(joint["offset"]) * 100.0 if joint["unit"] == "m" else abs(joint["offset"]) / 10.0
    return total


def _entity_difference(entity: Entity, failing: np.ndarray, reference: np.ndarray,
                       floor: bool) -> Dict[str, Any]:
    position = None
    rotation = None
    position_m = 0.0
    rotation_deg = 0.0
    free = entity.free
    if free is not None:
        base = 1 + free["qpos_adr"]
        offset = failing[base:base + 3] - reference[base:base + 3]
        position_m = float(np.linalg.norm(offset))
        rotation_deg = rotation_angle_deg(failing[base + 3:base + 7], reference[base + 3:base + 7])
        if not floor or position_m >= POSITION_FLOOR_M:
            position = {"offset_m": [float(value) for value in offset], "distance_m": position_m}
        else:
            position_m = 0.0
        if not floor or rotation_deg >= ROTATION_FLOOR_DEG:
            rotation = {"angle_deg": rotation_deg}
        else:
            rotation_deg = 0.0
    joints: List[Dict[str, Any]] = []
    for joint in entity.plain_joints:
        offset_value, unit, limit = _joint_offset(joint, failing, reference)
        if not floor or abs(offset_value) >= limit:
            joints.append({"name": joint["name"], "type": joint["type"],
                           "offset": float(offset_value), "unit": unit})
    return {
        "entity": entity.name, "kind": entity.kind, "position": position, "rotation": rotation,
        "joints": joints, "distance": _score(position_m, rotation_deg, joints),
    }


def differences(failing: Sequence[float], reference: Sequence[float],
                layout: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Ordered table of what changed from ``reference`` to ``failing``.

    Rows follow ``entities(layout)`` order and exist only for entities where at
    least one component is at or above its noise floor. Each row has ``entity``,
    ``kind``, ``position`` (``offset_m`` vector and ``distance_m``, or None),
    ``rotation`` (``angle_deg`` or None), ``joints`` (name, type, signed
    ``offset`` and ``unit``, changed joints only) and ``distance`` (centimetres
    plus degrees / 10, summed over the changed components).
    """

    failing_state = validate_state(failing, layout)
    reference_state = validate_state(reference, layout)
    rows = []
    for entity in entities(layout):
        row = _entity_difference(entity, failing_state, reference_state, floor=True)
        if row["position"] is not None or row["rotation"] is not None or row["joints"]:
            rows.append(row)
    return rows


def scenario_distance(first: Sequence[float], second: Sequence[float],
                      layout: Mapping[str, Any]) -> float:
    """Summed object distance: position in cm plus rotation in degrees / 10.

    Only object entities count (the robot is not part of the arrangement);
    object joints (a door, a drawer) add their offsets on the same scale.
    No noise floor is applied: this ranks references, it does not name causes.
    """

    one, two = validate_state(first, layout), validate_state(second, layout)
    return float(sum(_entity_difference(entity, one, two, floor=False)["distance"]
                     for entity in entities(layout) if entity.kind == "object"))


def fixed_order(table: Sequence[Mapping[str, Any]]) -> List[str]:
    """The fallback testing order: largest difference first, ties by name."""

    return [row["entity"] for row in sorted(table, key=lambda row: (-row["distance"], row["entity"]))]


# --- hybrid states ---------------------------------------------------------------


def normalise_selection(selection: object, layout: Mapping[str, Any]) -> Dict[str, Dict[str, float]]:
    """Validate a selection and return its canonical form.

    A selection maps entity -> ``{component: t}`` with ``t`` in [0, 1], where
    the components are ``position`` and ``rotation`` (free-joint objects) or
    ``joints`` (the robot, and objects with hinge, slide or ball joints).
    Parts with ``t == 0`` equal the reference and are dropped; entities and
    components come out in layout order, so equal selections compare equal.
    """

    if type(selection) is not dict:
        raise ScenarioStateError("selection must be an object")
    known = {entity.name: entity for entity in entities(layout)}
    result: Dict[str, Dict[str, float]] = {}
    for name in selection:
        if name not in known:
            raise ScenarioStateError("selection names an unknown entity")
    for entity in known.values():
        if entity.name not in selection:
            continue
        parts = selection[entity.name]
        if type(parts) is not dict:
            raise ScenarioStateError("selection parts must be an object")
        for component, value in parts.items():
            if component not in entity.components:
                raise ScenarioStateError("component is not available for this entity")
            if not _is_number(value) or not 0.0 <= float(value) <= 1.0:
                raise ScenarioStateError("selection fractions must be numbers within [0, 1]")
        kept = {component: float(parts[component]) for component in COMPONENTS
                if component in parts and float(parts[component]) > 0.0}
        if kept:
            result[entity.name] = kept
    return result


def selection_key(selection: Mapping[str, Mapping[str, float]]) -> str:
    """Stable text form of a (normalised) selection, for cache keys and logs."""

    return json.dumps(selection, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _lerp(first: np.ndarray, second: np.ndarray, t: float) -> np.ndarray:
    return second.copy() if t == 1.0 else first + t * (second - first)


def hybrid(reference: Sequence[float], failing: Sequence[float],
           selection: Mapping[str, Mapping[str, float]], layout: Mapping[str, Any]) -> np.ndarray:
    """The reference start with the selected differences applied.

    Selected positions and joints move ``t`` of the way from reference to
    failing (``t == 1`` copies the failing value exactly); rotations slerp.
    Unselected entities keep the reference. All velocities are zero (benchmark
    starts are at rest) and time comes from the reference. Inputs are not
    modified.
    """

    reference_state = validate_state(reference, layout)
    failing_state = validate_state(failing, layout)
    chosen = normalise_selection(dict(selection) if isinstance(selection, Mapping) else selection,
                                 layout)
    out = reference_state.copy()
    out[1 + layout["nq"]:] = 0.0
    by_name = {entity.name: entity for entity in entities(layout)}
    for name, parts in chosen.items():
        entity = by_name[name]
        free = entity.free
        for component, t in parts.items():
            if component == "position":
                base = 1 + free["qpos_adr"]
                out[base:base + 3] = _lerp(reference_state[base:base + 3],
                                           failing_state[base:base + 3], t)
            elif component == "rotation":
                base = 1 + free["qpos_adr"] + 3
                out[base:base + 4] = (failing_state[base:base + 4].copy() if t == 1.0 else
                                      slerp(reference_state[base:base + 4],
                                            failing_state[base:base + 4], t))
            else:
                for joint in entity.plain_joints:
                    base = 1 + joint["qpos_adr"]
                    if joint["type"] == "ball":
                        out[base:base + 4] = (failing_state[base:base + 4].copy() if t == 1.0 else
                                              slerp(reference_state[base:base + 4],
                                                    failing_state[base:base + 4], t))
                    else:
                        out[base] = _lerp(reference_state[base:base + 1],
                                          failing_state[base:base + 1], t)[0]
    return out


def state_hash(state: Sequence[float]) -> str:
    """SHA-256 of the little-endian float64 packing of ``state``.

    Matches the external-reset kernel's state hash, so a hash recorded by the
    simulator side and one computed here for the same vector are comparable.
    """

    try:
        payload = b"".join(struct.pack("<d", float(value)) for value in state)
    except (TypeError, ValueError, OverflowError, struct.error):
        raise ScenarioStateError("state must be a vector of numbers") from None
    if any(not math.isfinite(float(value)) for value in state):
        raise ScenarioStateError("state contains non-finite values")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "COMPONENTS", "Entity", "ROBOT", "ScenarioStateError", "differences", "entities",
    "fixed_order", "hybrid", "load_layout", "normalise_selection", "rotation_angle_deg",
    "scenario_distance", "selection_key", "slerp", "state_hash", "validate_layout",
    "validate_state",
]
