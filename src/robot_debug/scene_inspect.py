"""Read a LIBERO/robosuite/MuJoCo scene: joint layout, entity grouping and start validity.

Everything here takes the duck-typed MuJoCo ``model`` and ``data`` the simulator
exposes, so it runs against fakes in the unit tests. It also runs inside the
simulator image (Python 3.8), so only the standard library and numpy are used.

Entities. A scene is a set of *entities*: the robot (arm and gripper) and every
other jointed top-level body (a movable object, or an articulated fixture such
as a microwave). The entity of a body is its ancestor directly under the world
body. Top-level bodies without any joint (table, floor, static fixtures) are
*static*: they belong to no entity. A trailing ``_main`` is dropped from object
body names (robosuite names an object's root body ``<name>_main``), unless that
would make two entities share a name.

The flat state is robosuite's ``MjSimState.flatten``: ``[time] + qpos + qvel``,
so a joint's qpos starts at flat index ``1 + qpos_adr`` and its qvel at
``1 + nq + qvel_adr`` (``qvel_adr`` is MuJoCo's ``jnt_dofadr``).
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional

import numpy as np

SCHEMA_VERSION = 1
ROBOT_ENTITY = "robot"
ROBOT_PREFIXES = ("robot0_", "gripper0_", "mount0_")
PENETRATION_LIMIT_M = 0.005
_JOINT_TYPES = {0: "free", 1: "ball", 2: "slide", 3: "hinge"}
_MAIN_SUFFIX = "_main"


class SceneInspectError(ValueError):
    """The scene does not have the shape the reduction relies on."""


def validity_companion(state_out: str) -> str:
    """The validity record that sits beside an exported benchmark start (``x.json`` -> ``x.validity.json``)."""

    return os.path.splitext(state_out)[0] + ".validity.json"


def sim_of(env: Any) -> Any:
    """The MuJoCo sim of a LIBERO env wrapper (``env.sim`` or ``env.env.sim``)."""

    for holder in (env, getattr(env, "env", None)):
        sim = getattr(holder, "sim", None) if holder is not None else None
        if sim is not None:
            return sim
    raise SceneInspectError("the environment exposes no simulator")


def state_vector(env: Any, expected_length: int) -> np.ndarray:
    """``env.get_sim_state()`` as a flat finite float64 array of the expected length."""

    try:
        vector = np.asarray(env.get_sim_state(), dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        raise SceneInspectError("the simulator state is not numeric") from None
    if vector.shape != (expected_length,):
        raise SceneInspectError(
            "simulator state has {} entries, expected {}".format(vector.size, expected_length))
    if not np.all(np.isfinite(vector)):
        raise SceneInspectError("simulator state contains non-finite values")
    return vector


def _name(model: Any, kind: str, index: int) -> str:
    getter = getattr(model, kind + "_id2name", None)
    if callable(getter):
        name = getter(int(index))
    else:
        names = getattr(model, kind + "_names", None)
        if names is None:
            raise SceneInspectError("the model cannot name its {}s".format(kind))
        name = names[int(index)]
    if not isinstance(name, str):
        raise SceneInspectError("unnamed {}".format(kind))
    return name


def _top_bodies(model: Any) -> List[int]:
    """For every body, its ancestor directly under the world body (the world maps to itself)."""

    count = int(model.nbody)
    parent = [int(value) for value in model.body_parentid]
    top = []
    for body in range(count):
        current = body
        steps = 0
        while current != 0 and parent[current] != 0:
            current = parent[current]
            steps += 1
            if steps > count:
                raise SceneInspectError("the body tree has a cycle")
        top.append(current)
    return top


def _is_robot_name(name: str) -> bool:
    return name.startswith(ROBOT_PREFIXES)


def _entity_tables(model: Any):
    """``(body_entity, joint_entity)``: the entity name (or ``None`` for static) per body and joint."""

    top = _top_bodies(model)
    joint_bodies = [int(model.jnt_bodyid[j]) for j in range(int(model.njnt))]
    joint_names = [_name(model, "joint", j) for j in range(int(model.njnt))]
    jointed = set(top[body] for body in joint_bodies)
    jointed.discard(0)  # a joint on the world body would not name an entity
    robot = set(top[body] for body, name in zip(joint_bodies, joint_names) if _is_robot_name(name))
    for body in range(int(model.nbody)):
        if top[body] != 0 and _is_robot_name(_name(model, "body", top[body])):
            robot.add(top[body])
    robot &= jointed
    objects = sorted(jointed - robot)
    raw = {body: _name(model, "body", body) for body in objects}
    short = {body: (name[:-len(_MAIN_SUFFIX)] if name.endswith(_MAIN_SUFFIX) and len(name) > len(_MAIN_SUFFIX)
                    else name) for body, name in raw.items()}
    counts = {}  # type: Dict[str, int]
    for name in list(short.values()) + [ROBOT_ENTITY]:
        counts[name] = counts.get(name, 0) + 1
    names = {body: (short[body] if counts[short[body]] == 1 else raw[body]) for body in objects}
    for body in robot:
        names[body] = ROBOT_ENTITY
    body_entity = [names.get(top[body]) if top[body] != 0 else None for body in range(int(model.nbody))]
    joint_entity = [body_entity[body] for body in joint_bodies]
    return body_entity, joint_entity


def build_layout(suite: str, task_id: int, model: Any, state_length: int) -> Dict[str, Any]:
    """The per-task joint layout the reduction uses to name and slice differences."""

    nq, nv = int(model.nq), int(model.nv)
    if int(state_length) != 1 + nq + nv:
        raise SceneInspectError(
            "state has {} entries but 1 + nq + nv = {}; the flat state is not [time] + qpos + qvel".format(
                int(state_length), 1 + nq + nv))
    _body_entity, joint_entity = _entity_tables(model)
    joints = []
    for index in range(int(model.njnt)):
        kind = _JOINT_TYPES.get(int(model.jnt_type[index]))
        if kind is None:
            raise SceneInspectError("unsupported joint type")
        joints.append({
            "name": _name(model, "joint", index),
            "type": kind,
            "qpos_adr": int(model.jnt_qposadr[index]),
            "qvel_adr": int(model.jnt_dofadr[index]),
            "entity": joint_entity[index],
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": suite,
        "task_id": int(task_id),
        "state_length": int(state_length),
        "nq": nq,
        "nv": nv,
        "joints": joints,
    }


def scan_contacts(model: Any, data: Any, limit: float = PENETRATION_LIMIT_M,
                  body_entity: Optional[List[Optional[str]]] = None) -> Dict[str, Any]:
    """Classify the current contacts for the start-validity check.

    Only contacts between two different entities count (robot against object,
    object against object); contacts with static scene bodies and contacts inside
    one entity are ignored. A start is invalid when any counted contact
    penetrates deeper than ``limit`` (``dist < -limit``; exactly ``limit`` is valid).
    """

    if body_entity is None:
        body_entity = _entity_tables(model)[0]
    geom_body = model.geom_bodyid
    deepest = 0.0
    pair = None
    invalid = 0
    checked = 0
    for index in range(int(data.ncon)):
        contact = data.contact[index]
        first = body_entity[int(geom_body[int(contact.geom1)])]
        second = body_entity[int(geom_body[int(contact.geom2)])]
        if first is None or second is None or first == second:
            continue
        distance = float(contact.dist)
        if not math.isfinite(distance):
            raise SceneInspectError("a contact has a non-finite distance")
        checked += 1
        if distance < -limit:
            invalid += 1
        depth = -distance
        if depth > deepest:
            deepest = depth
            pair = sorted([first, second])
    return {
        "valid": invalid == 0,
        "deepest_penetration_m": float(deepest),
        "deepest_pair": pair,
        "invalid_contacts": invalid,
        "contacts_checked": checked,
    }


def body_entity_table(model: Any) -> List[Optional[str]]:
    """The entity name (``None`` for static bodies) of every body, for repeated scans."""

    return _entity_tables(model)[0]


def settle_displacement(layout: Dict[str, Any], before: Any, after: Any) -> Dict[str, float]:
    """Metres each free-joint object moved between two flat states (robot and jointed fixtures excluded)."""

    first = np.asarray(before, dtype=np.float64).reshape(-1)
    second = np.asarray(after, dtype=np.float64).reshape(-1)
    length = int(layout["state_length"])
    if first.shape != (length,) or second.shape != (length,):
        raise SceneInspectError("state length does not match the layout")
    result = {}  # type: Dict[str, float]
    for joint in layout["joints"]:
        entity = joint["entity"]
        if joint["type"] != "free" or entity == ROBOT_ENTITY or entity in result:
            continue
        start = 1 + int(joint["qpos_adr"])
        result[entity] = float(np.linalg.norm(second[start:start + 3] - first[start:start + 3]))
    return result
