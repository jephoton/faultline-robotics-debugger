"""Shared synthetic layouts, states and a fake executor for the scenario tests.

Nothing here touches a simulator or the network. The fake executor models the
real pool closely enough for the gate and reducer tests: a fixed number of
workers, a first-in-first-out queue, tickets that can only be withdrawn while
queued, and completion one ticket per ``wait_any`` call.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np


def synthetic_layout() -> Dict[str, Any]:
    """Robot (2 hinges + 1 slide), two free objects and a hinged door."""

    joints = [
        {"name": "robot0_joint1", "type": "hinge", "qpos_adr": 0, "qvel_adr": 0, "entity": "robot"},
        {"name": "robot0_joint2", "type": "hinge", "qpos_adr": 1, "qvel_adr": 1, "entity": "robot"},
        {"name": "gripper0_finger", "type": "slide", "qpos_adr": 2, "qvel_adr": 2, "entity": "robot"},
        {"name": "soup_1_joint0", "type": "free", "qpos_adr": 3, "qvel_adr": 3, "entity": "soup_1"},
        {"name": "microwave_1_door", "type": "hinge", "qpos_adr": 10, "qvel_adr": 9,
         "entity": "microwave_1"},
        {"name": "bowl_1_joint0", "type": "free", "qpos_adr": 11, "qvel_adr": 10, "entity": "bowl_1"},
    ]
    nq, nv = 18, 16
    return {"schema_version": 1, "suite": "libero_10", "task_id": 3,
            "state_length": 1 + nq + nv, "nq": nq, "nv": nv, "joints": joints}


def base_state(layout: Optional[Dict[str, Any]] = None) -> np.ndarray:
    """A deterministic at-rest state: identity quaternions, distinct positions."""

    layout = layout or synthetic_layout()
    state = np.zeros(layout["state_length"], dtype=np.float64)
    state[0] = 0.5
    qpos = state[1:1 + layout["nq"]]
    qpos[0:3] = (0.1, -0.2, 0.01)
    qpos[3:10] = (0.10, 0.20, 0.90, 1.0, 0.0, 0.0, 0.0)
    qpos[10] = 0.0
    qpos[11:18] = (-0.30, 0.40, 0.85, 1.0, 0.0, 0.0, 0.0)
    return state


def flat_qpos(layout: Dict[str, Any], adr: int) -> int:
    return 1 + adr


def quat_about_z(degrees: float) -> List[float]:
    half = math.radians(degrees) / 2.0
    return [math.cos(half), 0.0, 0.0, math.sin(half)]


def with_object_pose(state: np.ndarray, adr: int, *, dxyz: Sequence[float] = (0, 0, 0),
                     z_degrees: float = 0.0) -> np.ndarray:
    """Copy of ``state`` with the free joint at ``adr`` moved and turned about z."""

    out = np.array(state, dtype=np.float64)
    base = 1 + adr
    out[base:base + 3] += np.asarray(dxyz, dtype=np.float64)
    if z_degrees:
        out[base + 3:base + 7] = quat_about_z(z_degrees)
    return out


# --- fake executor -------------------------------------------------------------


class FakeTicket:
    """Mirrors the ticket protocol of ``decided_gate.Ticket``."""

    def __init__(self, item: Dict[str, Any], owner: "FakeExecutor") -> None:
        self.item = item
        self.record: Optional[Dict[str, Any]] = None
        self.started = False
        self._owner = owner

    def done(self) -> bool:
        return self.record is not None

    def withdraw(self, reason: str = "decided_skipped") -> bool:
        if self.started or self.record is not None:
            return False
        self._owner.queue.remove(self)
        self.record = {"status": reason, "item": self.item}
        self._owner.withdrawn.append(self)
        return True


class FakeExecutor:
    """Pool with ``workers`` slots; each ``wait_any`` call finishes one started ticket.

    ``outcome_fn(item)`` returns the outcome string (or a full record dict) of
    an attempt. Calls are logged so tests can assert on the exact sequence.
    """

    def __init__(self, outcome_fn: Callable[[Dict[str, Any]], Any], workers: int = 12) -> None:
        self.outcome_fn = outcome_fn
        self.workers = workers
        self.queue: List[FakeTicket] = []
        self.running: List[FakeTicket] = []
        self.submitted: List[FakeTicket] = []
        self.withdrawn: List[FakeTicket] = []
        self.executed: List[Dict[str, Any]] = []
        self.wait_calls = 0

    def submit(self, item: Dict[str, Any]) -> FakeTicket:
        ticket = FakeTicket(copy.deepcopy(item), self)
        self.submitted.append(ticket)
        self.queue.append(ticket)
        self._start()
        return ticket

    def _start(self) -> None:
        while self.queue and len(self.running) < self.workers:
            ticket = self.queue.pop(0)
            ticket.started = True
            self.running.append(ticket)

    def wait_any(self, tickets: Sequence[FakeTicket], timeout: float) -> None:
        self.wait_calls += 1
        if any(ticket.done() for ticket in tickets):
            return
        if not self.running:
            self._start()
        if not self.running:
            return
        ticket = self.running.pop(0)
        result = self.outcome_fn(ticket.item)
        if isinstance(result, dict):
            ticket.record = result
        else:
            ticket.record = {"status": "valid", "outcome": result}
        self.executed.append(ticket.item)
        self._start()
