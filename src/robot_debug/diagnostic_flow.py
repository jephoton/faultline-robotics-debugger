"""Pure, ordered find → confirm → reduce decisions for one frozen scenario.

The controller submits a complete `pending()` round and feeds its valid
outcomes to `apply_round`. This module does not launch or cancel evaluations;
the durable round adapter owns those side effects and uncertainty handling.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import math
from typing import Mapping, Sequence

from robot_debug.reduce import Candidate, GateDecision, Rect, candidates, classify_attempts
from robot_debug.session import is_reproducible


class DiagnosticFlow:
    """Deterministic phase transitions with separate M2 and M4 gates."""

    def __init__(
        self, *, search: Sequence[tuple[str, Rect]], deltas: Sequence[float],
        nominal_count: int, candidate_attempt_budget: int, control_count: int,
        config_hash: str,
    ) -> None:
        if not search or len({item[0] for item in search}) != len(search):
            raise ValueError("search must have unique, nonempty case IDs")
        if any(not isinstance(rect, Rect) or not case_id for case_id, rect in search):
            raise ValueError("search items must have case IDs and rectangles")
        if not deltas or any(isinstance(value, bool) or not isinstance(value, (int, float))
                             or not math.isfinite(value) or value <= 0 for value in deltas):
            raise ValueError("deltas must be positive")
        for name, value in (("nominal_count", nominal_count),
                            ("candidate_attempt_budget", candidate_attempt_budget),
                            ("control_count", control_count)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not config_hash:
            raise ValueError("config_hash must be nonempty")
        self.search = tuple(search)
        self.deltas = tuple(float(value) for value in deltas)
        self.nominal_count = nominal_count
        self.candidate_attempt_budget = candidate_attempt_budget
        self.control_count = control_count
        self.config_hash = config_hash
        self.phase = "nominal"
        self.selected_search_id: str | None = None
        self.current_rect: Rect | None = None
        self.delta_index = 0
        self.candidate_index = 0
        self.gate_outcomes: list[str] = []
        self.candidate_attempts = 0
        self.decisions: list[dict[str, object]] = []
        self.stop_reason: str | None = None

    @property
    def certified(self) -> bool:
        return self.phase == "certified"

    def _candidate(self) -> Candidate | None:
        if self.current_rect is None or self.delta_index >= len(self.deltas):
            return None
        options = candidates(self.current_rect, delta=self.deltas[self.delta_index])
        return options[self.candidate_index] if self.candidate_index < len(options) else None

    def _gate_prefix(self) -> str:
        if self.phase == "reduction_parent":
            return "parent"
        candidate = self._candidate()
        if candidate is None:
            raise ValueError("no active reduction candidate")
        return f"delta-{self.delta_index + 1:02d}-{candidate.edge}"

    def pending(self) -> tuple[str, ...]:
        if self.phase == "nominal":
            return tuple(f"nominal-{number:02d}" for number in range(1, self.nominal_count + 1))
        if self.phase == "search":
            return tuple(case_id for case_id, _ in self.search)
        if self.phase == "confirm":
            return tuple(f"confirm-{number:02d}" for number in range(1, 6))
        if self.phase == "reduction_sentinel":
            return ("reduction-sentinel",)
        if self.phase in ("reduction_parent", "reduce_candidate"):
            remaining_gate = 5 - len(self.gate_outcomes)
            count = min(4 if not self.gate_outcomes else 1, remaining_gate)
            if self.phase == "reduce_candidate":
                count = min(count, self.candidate_attempt_budget - self.candidate_attempts)
            return tuple(f"{self._gate_prefix()}-{number:02d}"
                         for number in range(len(self.gate_outcomes) + 1,
                                             len(self.gate_outcomes) + count + 1))
        if self.phase == "controls":
            return tuple(f"control-{number:02d}" for number in range(1, self.control_count + 1))
        return ()

    def _stop(self, reason: str) -> None:
        self.phase = "stopped"
        self.stop_reason = reason

    def _next_candidate(self) -> None:
        self.gate_outcomes = []
        while self.delta_index < len(self.deltas):
            if self.current_rect is None:
                raise ValueError("reducer has no parent")
            options = candidates(self.current_rect, delta=self.deltas[self.delta_index])
            if self.candidate_index < len(options):
                self.phase = "reduce_candidate"
                return
            self.delta_index += 1
            self.candidate_index = 0
        self.phase = "controls"

    def apply_round(self, outcomes: Mapping[str, str]) -> None:
        """Commit one complete round; never infer an omitted or invalid result."""
        expected = self.pending()
        if not expected or set(outcomes) != set(expected):
            raise ValueError("round results must match every pending case ID exactly")
        ordered = [outcomes[case_id] for case_id in expected]
        if any(outcome not in {"success", "policy_failure"} for outcome in ordered):
            self._stop("invalid_or_infrastructure_outcome")
            return
        if self.phase == "nominal":
            if any(outcome != "success" for outcome in ordered):
                self._stop("nominal_gate_failed")
            else:
                self.phase = "search"
        elif self.phase == "search":
            selected = next((case_id for case_id in expected if outcomes[case_id] == "policy_failure"), None)
            if selected is None:
                self._stop("no_apparent_failure")
            else:
                self.selected_search_id = selected
                self.current_rect = dict(self.search)[selected]
                self.decisions.append({"phase": "search", "selected": selected})
                self.phase = "confirm"
        elif self.phase == "confirm":
            if not is_reproducible(ordered):
                self._stop("failure_not_reproducible")
            else:
                self.phase = "reduction_sentinel"
        elif self.phase == "reduction_sentinel":
            if ordered != ["success"]:
                self._stop("reduction_sentinel_failed")
            else:
                self.phase = "reduction_parent"
        elif self.phase in ("reduction_parent", "reduce_candidate"):
            gate_phase = self.phase
            self.gate_outcomes.extend(ordered)
            if gate_phase == "reduce_candidate":
                self.candidate_attempts += len(ordered)
            decision = classify_attempts(self.gate_outcomes)
            if decision is GateDecision.PENDING:
                if len(self.gate_outcomes) == 5:
                    self._stop("gate_exhausted_without_decision")
                elif gate_phase == "reduce_candidate" and self.candidate_attempts >= self.candidate_attempt_budget:
                    self.phase = "controls"
                return
            if gate_phase == "reduction_parent":
                if decision is GateDecision.REJECT:
                    self._stop("parent_not_reproducible")
                else:
                    self.candidate_index = 0
                    self._next_candidate()
                return
            candidate = self._candidate()
            if candidate is None:
                raise ValueError("reducer lost candidate")
            self.decisions.append({"phase": "reduce_candidate", "edge": candidate.edge,
                                   "delta": self.deltas[self.delta_index], "decision": decision.value,
                                   "outcomes": list(self.gate_outcomes)})
            if decision is GateDecision.PASS:
                self.current_rect = candidate.rect
                self.candidate_index = 0
            else:
                self.candidate_index += 1
            if self.candidate_attempts >= self.candidate_attempt_budget:
                self.phase = "controls"
            else:
                self._next_candidate()
        elif self.phase == "controls":
            if any(outcome != "success" for outcome in ordered):
                self._stop("nominal_controls_failed")
            else:
                self.phase = "certified"

    def snapshot(self) -> dict[str, object]:
        """Return JSON-compatible state with its complete frozen config contract."""
        return json.loads(json.dumps({
            "config": {
                "search": [(case_id, asdict(rect)) for case_id, rect in self.search],
                "deltas": self.deltas, "nominal_count": self.nominal_count,
                "candidate_attempt_budget": self.candidate_attempt_budget,
                "control_count": self.control_count, "config_hash": self.config_hash,
            },
            "phase": self.phase, "selected_search_id": self.selected_search_id,
            "current_rect": asdict(self.current_rect) if self.current_rect else None,
            "delta_index": self.delta_index, "candidate_index": self.candidate_index,
            "gate_outcomes": self.gate_outcomes, "candidate_attempts": self.candidate_attempts,
            "decisions": self.decisions, "stop_reason": self.stop_reason,
        }, allow_nan=False))

    @classmethod
    def restore(cls, snapshot: Mapping[str, object], **config: object) -> "DiagnosticFlow":
        """Restore only a state saved for the same frozen scenario contract."""
        flow = cls(**config)
        if snapshot.get("config") != flow.snapshot()["config"]:
            raise ValueError("stored diagnostic configuration differs")
        phase = snapshot.get("phase")
        if phase not in {"nominal", "search", "confirm", "reduction_sentinel",
                         "reduction_parent", "reduce_candidate", "controls", "certified", "stopped"}:
            raise ValueError("unknown stored diagnostic phase")
        flow.phase = phase
        flow.selected_search_id = snapshot.get("selected_search_id")
        raw_rect = snapshot.get("current_rect")
        flow.current_rect = Rect(**raw_rect) if isinstance(raw_rect, dict) else None
        for name in ("delta_index", "candidate_index", "candidate_attempts"):
            value = snapshot.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"invalid stored {name}")
            setattr(flow, name, value)
        outcomes = snapshot.get("gate_outcomes")
        if not isinstance(outcomes, list) or len(outcomes) > 5 or any(
            item not in {"success", "policy_failure"} for item in outcomes
        ):
            raise ValueError("invalid stored gate outcomes")
        flow.gate_outcomes = list(outcomes)
        decisions = snapshot.get("decisions")
        if not isinstance(decisions, list):
            raise ValueError("invalid stored decisions")
        flow.decisions = list(decisions)
        flow.stop_reason = snapshot.get("stop_reason")
        if flow.phase not in {"stopped", "certified"} and not flow.pending():
            raise ValueError("restored active state has no pending work")
        return flow
