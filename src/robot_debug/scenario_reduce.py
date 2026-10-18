"""Ranked delta-debugging reduction of a failing LIBERO start state (ADR 0028).

Given a start that fails reproducibly and the nearest start that passes, find
which differences between them cause the failure. The search is pure and
simulator-agnostic, like ``threshold_search``: it never builds a state or runs
an episode itself. The caller supplies

* ``executor``: runs attempts (see ``decided_gate`` for the protocol);
* ``prepare(spec) -> (key, item)``: turns a candidate description into a cache
  key (the hash of the hybrid start state) and an executor item. ``spec`` is
  ``{"role": "failing"}``, ``{"role": "reference", "reference": id}`` or
  ``{"role": "hybrid", "reference": id, "selection": {entity: {component: t}}}``;
* ``references``: the nearest passing starts, nearest first, each
  ``{"id": ..., "differences": table}`` with the table from
  ``scenario_state.differences(failing, reference, layout)``.

A candidate **reproduces** when at least ``required_failures`` of its
``attempts`` are policy failures (the 4-of-5 gate), decided as early as the
outcome is fixed (``decided_gate``). ``invalid_scene`` never counts as a policy
failure and is reported.

Steps (a local search, not a proof of the globally smallest cause; the
assumption throughout is that failure is roughly monotone in how much of a
difference is applied):

1. **Gates.** The failing start must reproduce, the full hybrid (every
   difference applied to the reference) must reproduce, and the reference must
   pass 5 of 5. A reference that does not pass is replaced by the next nearest,
   at most ``max_references`` in all.
2. **Ranked probe.** Single entities alone, in ``order``. A singleton that
   reproduces is already 1-minimal over entities (removing it gives the passing
   reference), so ddmin is skipped.
3. **Delta debugging** (ddmin over entities, subsets then complements) until no
   single entity can be removed. Candidates of a round are evaluated
   ``concurrency`` at a time; the first reproducing one in order wins, so the
   result is deterministic.
4. **Split.** Each surviving object is tested with position only and rotation
   only; the smaller sufficient part is kept, both when neither suffices alone.
   (Robot joints and an object's hinge/slide joints stay one part.)
5. **Shrink.** Each surviving part is bisected from ``t = 1`` towards 0
   (``bisection_steps`` steps; tolerance ``1 / 2**bisection_steps`` of the
   original difference), the other parts held at their current values.

Stop reasons: ``reduced``, ``failing_not_reproducible``, ``reference_not_passing``,
``budget_exhausted``, ``deadline_exhausted``, ``infrastructure_error``.
Candidates are cached by key, so an identical hybrid state is never rerun.

The result lists every candidate with its ``phase``, ``selection``, ``key``,
``outcomes`` (in completion order), ``decision`` and ``gate_met`` (the failure
gate reproduced, or the reference passed 5 of 5), ``skipped`` attempts (decided
early, never run) and ``late_outcomes`` (attempts already running when the gate
was decided; recorded, never used). ``ranked_probe`` reports the probe's cost and
a *modelled* count of the candidates plain ddmin would have needed; that count
assumes exactly the sets containing the found entity reproduce, so it is an
estimate to be reported as such, not a measured saving.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .decided_gate import GateRun, collect_late, run_gates
from .scenario_state import fixed_order

STOP_REASONS = (
    "reduced",
    "failing_not_reproducible",
    "reference_not_passing",
    "budget_exhausted",
    "deadline_exhausted",
    "infrastructure_error",
)
_DECIMALS = 6
_COMPONENT_ORDER = ("position", "rotation", "joints")


class _Stop(Exception):
    def __init__(self, reason: str, detail: Optional[str] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


# --- helpers ----------------------------------------------------------------------


def _chunks(items: Sequence[Any], size: int) -> List[List[Any]]:
    return [list(items[start:start + size]) for start in range(0, len(items), size)]


def _split_even(items: Sequence[Any], parts: int) -> List[List[Any]]:
    """``parts`` contiguous slices whose sizes differ by at most one (earlier ones larger)."""

    base, extra = divmod(len(items), parts)
    result, start = [], 0
    for index in range(parts):
        stop = start + base + (1 if index < extra else 0)
        result.append(list(items[start:stop]))
        start = stop
    return result


def ddmin(items: Sequence[Any], find_first: Callable[[List[List[Any]]], Optional[int]]) -> List[Any]:
    """Zeller's ddmin. ``find_first(sets)`` returns the index of the first set (in
    the given order) that still reproduces, or None. Candidate sets are subsets,
    then complements; the empty set is never offered (it is the passing reference).
    Returns a 1-minimal reproducing subset of ``items``."""

    current = list(items)
    granularity = 2
    while len(current) >= 2:
        granularity = min(granularity, len(current))
        subsets = _split_even(current, granularity)
        hit = find_first(subsets)
        if hit is not None:
            current, granularity = subsets[hit], 2
            continue
        if granularity > 2:      # for 2 the complements are the subsets again
            complements = [[x for x in current if x not in subset] for subset in subsets]
            hit = find_first(complements)
            if hit is not None:
                current, granularity = complements[hit], max(granularity - 1, 2)
                continue
        if granularity >= len(current):
            break
        granularity = min(len(current), 2 * granularity)
    return current


def _validate_parameters(attempts: int, required_failures: int, bisection_steps: int,
                         max_candidates: int, concurrency: int, max_references: int) -> None:
    for name, value in (("attempts", attempts), ("required_failures", required_failures),
                        ("bisection_steps", bisection_steps), ("max_candidates", max_candidates),
                        ("concurrency", concurrency), ("max_references", max_references)):
        if type(value) is not int:
            raise ValueError("{} must be an integer".format(name))
    if attempts < 1 or not 1 <= required_failures <= attempts:
        raise ValueError("required_failures must be between 1 and attempts")
    if bisection_steps < 0:
        raise ValueError("bisection_steps must not be negative")
    if max_candidates < 1 or concurrency < 1 or max_references < 1:
        raise ValueError("max_candidates, concurrency and max_references must be at least 1")


def _components(row: Mapping[str, Any]) -> List[str]:
    parts = []
    if row.get("position") is not None:
        parts.append("position")
    if row.get("rotation") is not None:
        parts.append("rotation")
    if row.get("joints"):
        parts.append("joints")
    return parts


def _validate_references(references: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    if isinstance(references, (str, bytes)) or not references:
        raise ValueError("references must be a non-empty sequence")
    result = []
    for entry in references:
        if not isinstance(entry, Mapping) or set(entry) != {"id", "differences"}:
            raise ValueError("each reference needs exactly id and differences")
        table = entry["differences"]
        if isinstance(table, (str, bytes)) or not isinstance(table, Sequence):
            raise ValueError("differences must be a list of rows")
        names = []
        for row in table:
            if not isinstance(row, Mapping) or type(row.get("entity")) is not str or not _components(row):
                raise ValueError("each difference row needs an entity and at least one component")
            names.append(row["entity"])
        if len(set(names)) != len(names):
            raise ValueError("difference rows must have unique entities")
        result.append({"id": entry["id"], "differences": [dict(row) for row in table]})
    if not result[0]["differences"]:
        raise ValueError("the first reference must differ from the failing start")
    return result


class _Reducer:
    """Mutable state of one reduction; ``run`` is the only entry point."""

    def __init__(self, executor: Any, prepare: Callable[[Dict[str, Any]], Tuple[str, Dict[str, Any]]],
                 *, attempts: int, required_failures: int, max_candidates: int, concurrency: int,
                 max_in_flight: Optional[int], remaining: Optional[Callable[[], Optional[float]]],
                 wait_timeout: float) -> None:
        self.executor, self.prepare = executor, prepare
        self.attempts, self.required_failures = attempts, required_failures
        self.max_candidates, self.concurrency = max_candidates, concurrency
        self.max_in_flight, self.remaining, self.wait_timeout = max_in_flight, remaining, wait_timeout
        self.candidates: List[Dict[str, Any]] = []
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.hybrids_used = 0
        self.late: List[Tuple[str, Any]] = []
        self.phase = "gate"

    # -- running candidates -----------------------------------------------------

    def evaluate(self, specs: Sequence[Dict[str, Any]], *, batch: Optional[int] = None
                 ) -> List[Optional[Dict[str, Any]]]:
        """Candidate records for ``specs`` in order; ``None`` marks a spec the
        candidate budget did not allow. Runs uncached ones as one gate batch of
        at most ``batch`` (default ``concurrency``) candidates at a time."""

        size = self.concurrency if batch is None else batch
        results: List[Optional[Dict[str, Any]]] = []
        for group in _chunks(list(specs), size):
            results.extend(self._evaluate_group(group))
        return results

    def _evaluate_group(self, specs: Sequence[Dict[str, Any]]) -> List[Optional[Dict[str, Any]]]:
        slots: List[Optional[Dict[str, Any]]] = [None] * len(specs)
        fresh: List[Tuple[int, Dict[str, Any], Dict[str, Any]]] = []
        pending_keys: Dict[str, int] = {}
        for index, spec in enumerate(specs):
            key, item = self.prepare(copy.deepcopy(spec))
            kind = "pass" if spec["role"] == "reference" else "failure"
            cache_key = kind + ":" + key
            if cache_key in self.cache:
                slots[index] = self.cache[cache_key]
                continue
            if cache_key in pending_keys:        # duplicate within the group
                continue
            if spec["role"] == "hybrid":
                if self.hybrids_used >= self.max_candidates:
                    continue
                self.hybrids_used += 1
            pending_keys[cache_key] = index
            record = {
                "index": len(self.candidates), "phase": self.phase, "role": spec["role"],
                "reference": spec.get("reference"), "selection": copy.deepcopy(spec.get("selection")),
                "key": key, "kind": kind, "decision": None, "gate_met": None, "outcomes": [],
                "late_outcomes": [], "skipped": 0, "stop_withdrawn": 0, "complete": False,
            }
            self.candidates.append(record)
            self.cache[cache_key] = record
            fresh.append((index, record, item))
        if fresh:
            gate_candidates = [{"key": str(record["index"]), "item": item, "kind": record["kind"]}
                               for _, record, item in fresh]
            run = run_gates(
                self.executor, gate_candidates, attempts=self.attempts,
                required_failures=self.required_failures, max_in_flight=self.max_in_flight,
                remaining=self.remaining, wait_timeout=self.wait_timeout, drain=False)
            self._absorb(run, [record for _, record, _ in fresh])
            if run.stop is not None:
                raise _Stop(run.stop, run.detail)
        for index, spec in enumerate(specs):
            if slots[index] is None:
                key, _ = self.prepare(copy.deepcopy(spec))
                kind = "pass" if spec["role"] == "reference" else "failure"
                slots[index] = self.cache.get(kind + ":" + key)
        return slots

    def _absorb(self, run: GateRun, records: Sequence[Dict[str, Any]]) -> None:
        for record in records:
            name = str(record["index"])
            record["decision"] = run.decisions[name]
            record["outcomes"] = list(run.outcomes[name])
            record["skipped"] = run.skipped[name]
            record["stop_withdrawn"] = run.stop_withdrawn[name]
            record["complete"] = record["decision"] is not None
            good = "passes" if record["kind"] == "pass" else "reproduces"
            record["gate_met"] = None if record["decision"] is None else record["decision"] == good
        by_name = {str(record["index"]): record for record in records}
        self.late.extend((by_name[name], ticket) for name, ticket in run.late)

    def finish_late(self) -> None:
        """Record attempts that were already running when their gate was decided."""

        if not self.late:
            return
        by_name = {str(record["index"]): record for record, _ in self.late}
        collected = collect_late(self.executor, [(str(record["index"]), ticket)
                                                 for record, ticket in self.late],
                                 wait_timeout=self.wait_timeout, remaining=self.remaining)
        for name, raw in collected:
            if isinstance(raw, dict) and raw.get("status") == "valid":
                by_name[name]["late_outcomes"].append(raw.get("outcome"))
        self.late = []

    def first_reproducing(self, specs: Sequence[Dict[str, Any]]) -> Optional[int]:
        """Index of the first spec that reproduces, evaluating ``concurrency`` at a time."""

        offset = 0
        for group in _chunks(list(specs), self.concurrency):
            results = self._evaluate_group(group)
            for position, record in enumerate(results):
                if record is None:
                    raise _Stop("budget_exhausted")
                if record["gate_met"]:
                    return offset + position
            offset += len(group)
        return None


def _selection_for(parts: Mapping[str, Mapping[str, float]]) -> Dict[str, Dict[str, float]]:
    return {entity: dict(components) for entity, components in parts.items() if components}


def run_scenario_reduction(
    executor: Any,
    prepare: Callable[[Dict[str, Any]], Tuple[str, Dict[str, Any]]],
    references: Sequence[Mapping[str, Any]],
    *,
    order: Optional[Sequence[str]] = None,
    attempts: int = 5,
    required_failures: int = 4,
    bisection_steps: int = 4,
    max_candidates: int = 30,
    concurrency: int = 3,
    max_references: int = 3,
    max_in_flight: Optional[int] = None,
    speculative_bisection: bool = False,
    remaining: Optional[Callable[[], Optional[float]]] = None,
    wait_timeout: float = 5.0,
) -> Dict[str, Any]:
    """Reduce the differences between a failing start and its reference; returns a
    JSON-clean record (see the module docstring for the steps).

    ``order`` is the entity order to probe (Nemotron's ranking, or ``None`` for
    largest difference first); unknown names are ignored and missing ones are
    appended. ``max_candidates`` bounds the hybrid candidates run (cached ones
    are free). ``concurrency`` is how many independent candidates share a round.
    ``max_in_flight`` (set it to the pool's worker count) lets freed workers take
    attempts of other candidates and makes early decisions save attempts.
    ``speculative_bisection`` tests the midpoint and the lower quarter point
    together, spending extra candidates to halve the rounds. ``remaining()`` is
    the seconds left.
    """

    _validate_parameters(attempts, required_failures, bisection_steps, max_candidates,
                         concurrency, max_references)
    usable = _validate_references(references)
    reducer = _Reducer(executor, prepare, attempts=attempts, required_failures=required_failures,
                       max_candidates=max_candidates, concurrency=concurrency,
                       max_in_flight=max_in_flight, remaining=remaining, wait_timeout=wait_timeout)
    result: Dict[str, Any] = {
        "stop_reason": None, "reduced": False, "error": None, "note": None,
        "attempts": attempts, "required_failures": required_failures,
        "bisection_steps": bisection_steps, "max_candidates": max_candidates,
        "concurrency": concurrency, "speculative_bisection": bool(speculative_bisection),
        "reference": None, "references_tried": [], "order": [], "entities": [],
        "entity_minimal": False, "surviving_entities": [], "final_selection": None,
        "final_candidate": None, "parts": [], "ranked_probe": None,
    }
    state: Dict[str, Any] = {"reference": None, "table": None, "entities": [], "components": {},
                             "current": None, "parts": None}
    try:
        _run(reducer, usable[:max_references], order, bisection_steps, speculative_bisection,
             result, state)
        result["stop_reason"] = "reduced"
        result["reduced"] = True
    except _Stop as stop:
        result["stop_reason"] = stop.reason
        if stop.reason == "infrastructure_error":
            result["error"] = stop.detail
        if stop.reason == "failing_not_reproducible":
            result["note"] = stop.detail
    try:
        reducer.finish_late()
    except Exception:  # noqa: BLE001 - late records are best effort
        pass
    _finalise(reducer, result, state)
    return result


def _run(reducer: _Reducer, references: List[Dict[str, Any]], order: Optional[Sequence[str]],
         bisection_steps: int, speculative: bool, result: Dict[str, Any],
         state: Dict[str, Any]) -> None:
    # 1. gates -----------------------------------------------------------------------
    failing_spec = {"role": "failing"}
    chosen: Optional[Dict[str, Any]] = None
    failing_checked = False
    for reference in references:
        rows = reference["differences"]
        if not rows:
            result["references_tried"].append({"id": reference["id"], "decision": "no_differences"})
            continue
        full = {row["entity"]: {c: 1.0 for c in _components(row)} for row in rows}
        # The failing start and the reference gate together; the full-hybrid check is only spent
        # on a reference that passes 5 of 5 (a failing reference is replaced by the next nearest).
        specs = [] if failing_checked else [failing_spec]
        specs += [{"role": "reference", "reference": reference["id"]}]
        records = reducer.evaluate(specs, batch=len(specs))
        if any(record is None for record in records):
            raise _Stop("budget_exhausted")
        if not failing_checked:
            failing_record = records.pop(0)
            failing_checked = True
            if not failing_record["gate_met"]:
                raise _Stop("failing_not_reproducible", "failing_start_" + str(failing_record["decision"]))
        (reference_record,) = records
        result["references_tried"].append({
            "id": reference["id"], "decision": reference_record["decision"],
            "outcomes": list(reference_record["outcomes"])})
        if reference_record["gate_met"]:       # the pass gate: passes 5 of 5
            (full_record,) = reducer.evaluate(
                [{"role": "hybrid", "reference": reference["id"], "selection": full}], batch=1)
            if full_record is None:
                raise _Stop("budget_exhausted")
            chosen = reference
            if not full_record["gate_met"]:
                state.update(reference=reference["id"], table=rows)
                raise _Stop("failing_not_reproducible",
                            "full_hybrid_" + str(full_record["decision"]))
            break
    if not failing_checked:
        raise _Stop("reference_not_passing")
    if chosen is None:
        raise _Stop("reference_not_passing")
    rid, rows = chosen["id"], chosen["differences"]
    by_entity = {row["entity"]: row for row in rows}
    names = list(by_entity)
    ranking: List[str] = []
    for name in (order or []):
        if name in by_entity and name not in ranking:
            ranking.append(name)
    ranking += [name for name in fixed_order(rows) if name not in ranking]
    components = {name: _components(by_entity[name]) for name in names}
    state.update(reference=rid, table=rows, entities=ranking, components=components)
    result["reference"], result["order"], result["entities"] = rid, list(ranking), list(ranking)
    state["current"] = list(ranking)
    state["parts"] = {name: {c: 1.0 for c in components[name]} for name in ranking}

    def spec_for(entities: Sequence[str]) -> Dict[str, Any]:
        selection = {name: {c: 1.0 for c in components[name]} for name in ranking if name in entities}
        return {"role": "hybrid", "reference": rid, "selection": selection}

    def find_first(sets: List[List[str]]) -> Optional[int]:
        return reducer.first_reproducing([spec_for(entities) for entities in sets])

    # 2. ranked probe ---------------------------------------------------------------
    reducer.phase = "probe"
    probe_before = reducer.hybrids_used
    singles = [[name] for name in ranking]
    hit = find_first(singles)
    probe: Dict[str, Any] = {"hit": None, "rank": None, "singletons_tested": None,
                             "candidates_run": None, "modelled_ddmin_candidates": None,
                             "modelled_candidates_avoided": None,
                             "model": "ddmin under the assumption that a set reproduces iff it "
                                      "contains the culprit entity"}
    result["ranked_probe"] = probe
    probe["candidates_run"] = reducer.hybrids_used - probe_before
    if hit is not None:
        culprit = ranking[hit]
        state["current"] = [culprit]
        probe.update(hit=culprit, rank=hit + 1, singletons_tested=hit + 1)
        modelled = _modelled_ddmin(ranking, culprit, reducer.concurrency)
        probe["modelled_ddmin_candidates"] = modelled
        probe["modelled_candidates_avoided"] = max(0, modelled - probe["candidates_run"])
        result["entity_minimal"] = True
    else:
        probe["singletons_tested"] = len(ranking)
        # 3. ddmin -------------------------------------------------------------------
        reducer.phase = "ddmin"
        if len(ranking) >= 2:
            def track(sets: List[List[str]]) -> Optional[int]:
                index = find_first(sets)
                if index is not None:
                    state["current"] = list(sets[index])
                    state["parts"] = {n: {c: 1.0 for c in components[n]} for n in sets[index]}
                return index
            ddmin(ranking, track)
        result["entity_minimal"] = True
    current = [name for name in ranking if name in state["current"]]
    state["current"] = current
    state["parts"] = {name: {c: 1.0 for c in components[name]} for name in current}
    parts = state["parts"]

    def part_spec(candidate_parts: Mapping[str, Mapping[str, float]]) -> Dict[str, Any]:
        return {"role": "hybrid", "reference": rid, "selection": _selection_for(candidate_parts)}

    # 4. split ----------------------------------------------------------------------
    reducer.phase = "split"
    for name in current:
        if not {"position", "rotation"} <= set(parts[name]):
            continue
        position_only = {**parts, name: {"position": 1.0}}
        rotation_only = {**parts, name: {"rotation": 1.0}}
        records = reducer.evaluate([part_spec(position_only), part_spec(rotation_only)])
        if any(record is None for record in records):
            raise _Stop("budget_exhausted")
        position_ok, rotation_ok = bool(records[0]["gate_met"]), bool(records[1]["gate_met"])
        if position_ok and rotation_ok:
            row = by_entity[name]
            position_size = row["position"]["distance_m"] * 100.0
            rotation_size = row["rotation"]["angle_deg"] / 10.0
            keep = "position" if position_size <= rotation_size else "rotation"
            result.setdefault("also_sufficient", []).append(
                {"entity": name, "kept": keep, "also": "rotation" if keep == "position" else "position"})
            parts[name] = {keep: 1.0}
        elif position_ok:
            parts[name] = {"position": 1.0}
        elif rotation_ok:
            parts[name] = {"rotation": 1.0}

    # 5. shrink ---------------------------------------------------------------------
    reducer.phase = "shrink"
    state["shrink"] = []
    for name in current:
        for component in list(parts[name]):
            summary = _bisect(reducer, parts, name, component, bisection_steps, speculative,
                              part_spec)
            state["shrink"].append(summary)


def _bisect(reducer: _Reducer, parts: Dict[str, Dict[str, float]], entity: str, component: str,
            steps: int, speculative: bool,
            part_spec: Callable[[Mapping[str, Mapping[str, float]]], Dict[str, Any]]) -> Dict[str, Any]:
    low, high = 0.0, parts[entity][component]
    done = 0

    def with_t(value: float) -> Dict[str, Any]:
        return part_spec({**parts, entity: {**parts[entity], component: value}})

    low_tested = False
    invalid_points = []   # midpoints that were interpenetrating scenes: no information about the policy

    def judge(record: Mapping[str, Any], value: float) -> str:
        """``yes`` (reproduces), ``no`` (a tested non-reproducing point) or ``invalid``."""

        if record["gate_met"]:
            return "yes"
        if record["decision"] == "invalid_scene":
            invalid_points.append(value)
            return "invalid"
        return "no"

    while done < steps:
        middle = round((low + high) / 2.0, _DECIMALS)
        if not low < middle < high:
            break
        if speculative and reducer.concurrency >= 2 and steps - done >= 2:
            quarter = round((low + middle) / 2.0, _DECIMALS)
            if low < quarter < middle:
                middle_record, quarter_record = reducer.evaluate([with_t(middle), with_t(quarter)])
                if middle_record is None:
                    raise _Stop("budget_exhausted")
                middle_verdict = judge(middle_record, middle)
                if quarter_record is None:
                    # The budget ended between the pair: keep what the middle point proved (found October 18:
                    # a verified 75% was reported as 100% because the unrun quarter discarded it).
                    if middle_verdict == "yes":
                        parts[entity][component] = middle
                    raise _Stop("budget_exhausted")
                quarter_verdict = judge(quarter_record, quarter)
                if middle_verdict == "yes":
                    if quarter_verdict == "yes":
                        high = quarter
                    else:
                        low, high, low_tested = quarter, middle, quarter_verdict == "no"
                    done += 2
                else:
                    low, low_tested = middle, middle_verdict == "no"
                    done += 1
                parts[entity][component] = high
                continue
        (record,) = reducer.evaluate([with_t(middle)])
        if record is None:
            raise _Stop("budget_exhausted")
        verdict = judge(record, middle)
        if verdict == "yes":
            high = middle
        else:
            # An invalid midpoint says nothing about the policy: keep the search conservative (the
            # size stays at the smallest verified reproducing value) and do not call it tested.
            low, low_tested = middle, verdict == "no"
        done += 1
        parts[entity][component] = high
    parts[entity][component] = high
    return {"entity": entity, "component": component, "t": high, "lower": low,
            "lower_tested": low_tested, "invalid_points": invalid_points,
            "resolution": round(high - low, _DECIMALS), "steps_done": done}


def _modelled_ddmin(ranking: Sequence[str], culprit: str, concurrency: int) -> int:
    """Candidates ddmin would test from the full set if exactly the sets containing
    ``culprit`` reproduce (the situation in which the ranked probe found a singleton).
    Counted in the same ``concurrency``-sized rounds the real search uses."""

    tested = set()

    def find_first(sets: List[List[str]]) -> Optional[int]:
        offset = 0
        for group in _chunks(sets, concurrency):
            for position, entities in enumerate(group):
                tested.add(frozenset(entities))
                if culprit in entities:
                    return offset + position
            offset += len(group)
        return None

    ddmin(list(ranking), find_first)
    return len(tested)


def _finalise(reducer: _Reducer, result: Dict[str, Any], state: Dict[str, Any]) -> None:
    parts = state.get("parts")
    current = state.get("current")
    if parts is not None and current is not None:
        final = _selection_for({name: parts[name] for name in current if name in parts})
        result["final_selection"] = final
        result["surviving_entities"] = list(final)
        result["parts"] = state.get("shrink", [])
        if state.get("reference") is not None:
            key, _ = reducer.prepare({"role": "hybrid", "reference": state["reference"],
                                      "selection": copy.deepcopy(final)})
            record = reducer.cache.get("failure:" + key)
            if record is not None and record["gate_met"]:
                result["final_candidate"] = record["index"]
    if state.get("reference") is not None:
        result["reference"] = state["reference"]
    result["candidates"] = reducer.candidates
    hybrids = [c for c in reducer.candidates if c["role"] == "hybrid"]
    gates = [c for c in reducer.candidates if c["role"] != "hybrid"]
    run_count = lambda group: sum(len(c["outcomes"]) + len(c["late_outcomes"]) for c in group)  # noqa: E731
    result["candidates_tested"] = len(hybrids)
    result["attempts_run_gates"] = run_count(gates)
    result["attempts_run_hybrid"] = run_count(hybrids)
    result["attempts_run"] = result["attempts_run_gates"] + result["attempts_run_hybrid"]
    result["attempts_skipped"] = sum(c["skipped"] for c in reducer.candidates)
    result["attempts_stop_withdrawn"] = sum(c["stop_withdrawn"] for c in reducer.candidates)
    result["invalid_scenes"] = [c["index"] for c in reducer.candidates if c["decision"] == "invalid_scene"]


__all__ = ["STOP_REASONS", "ddmin", "run_scenario_reduction"]
