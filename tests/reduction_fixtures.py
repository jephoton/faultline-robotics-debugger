"""A small synthetic reduction shaped like a real budget-exhausted, entity-minimal run.

Five entities differ. The model ranks ``soup`` first and ``sauce`` second. The soup is
necessary (the final selection without it passes) but not sufficient (it alone passes);
the sauce is not needed (the scene without it still fails). The reduction stopped on its
budget while shrinking, so it is entity-minimal but not ``reduced``.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

FAIL = ["policy_failure"] * 4
PASS = ["success"] * 4


def candidate(index: int, phase: str, selection: Optional[Dict[str, Dict[str, float]]], decision: str,
              outcomes: Optional[List[str]] = None, role: Optional[str] = None,
              reference: Any = 28) -> Dict[str, Any]:
    if outcomes is None:
        outcomes = list(FAIL if decision == "reproduces" else PASS)
    return {
        "index": index, "phase": phase, "role": role or "hybrid", "selection": selection,
        "decision": decision, "outcomes": outcomes, "late_outcomes": [], "gate_met": decision == "reproduces",
        "skipped": 0, "kind": "failure", "reference": reference, "complete": True, "stop_withdrawn": 0,
    }


def partial_reduction() -> Dict[str, Any]:
    full = {"position": 1.0}
    final = {"soup": {"position": 0.875}, "cream": dict(full), "milk": dict(full), "robot": {"joints": 0.875}}
    candidates = [
        candidate(0, "gate", None, "reproduces", role="failing", reference=None),
        candidate(1, "gate", None, "passes", list(PASS) + ["success"], role="reference"),
        candidate(2, "probe", {"soup": dict(full)}, "does_not_reproduce"),
        candidate(3, "probe", {"sauce": dict(full)}, "does_not_reproduce"),
        candidate(4, "probe", {"robot": {"joints": 1.0}}, "does_not_reproduce"),
        candidate(5, "probe", {"cream": dict(full)}, "does_not_reproduce"),
        candidate(6, "probe", {"milk": dict(full)}, "does_not_reproduce"),
        # the final entities with the robot at full size and no soup: a pass, so the soup is needed
        candidate(7, "ddmin", {"cream": dict(full), "milk": dict(full), "robot": {"joints": 1.0}},
                  "does_not_reproduce"),
        # everything except the sauce: still fails, so the sauce is not needed
        candidate(8, "ddmin", {"soup": dict(full), "cream": dict(full), "milk": dict(full),
                               "robot": {"joints": 1.0}}, "reproduces"),
        candidate(9, "shrink", {"soup": {"position": 0.5}, "cream": dict(full), "milk": dict(full),
                                "robot": {"joints": 1.0}}, "does_not_reproduce"),
        candidate(10, "shrink", copy.deepcopy(final), "reproduces",
                  ["success", "policy_failure", "policy_failure", "policy_failure", "policy_failure"]),
    ]
    return {
        "stop_reason": "budget_exhausted", "reduced": False, "entity_minimal": True,
        "reference": 28, "final_candidate": 10, "final_selection": final,
        "surviving_entities": ["soup", "cream", "milk", "robot"], "candidates": candidates,
    }


def partial_plan(ranking: Optional[List[str]] = None, order_source: str = "model") -> Dict[str, Any]:
    ranking = ranking or ["soup", "sauce", "robot", "cream", "milk"]
    return {
        "suite": "libero_object", "task_id": 3, "instruction": "pick up the soup and place it in the basket",
        "failing_start": 7, "references": [28], "order": list(ranking), "order_source": order_source,
        "hypothesis": {
            "text": "Reverting only the soup restores success; reverting only the sauce does not.",
            "ranking": list(ranking), "completed": [], "source": order_source, "model": "test/model",
            "tier": "ultra", "fallback_reason": None, "raw_content": None, "provenance": {},
        },
    }
