"""Runner and summary for the M6 camera-reliance and scalar-family experiment (ADR 0026).

Two Serverless modes share the M3 machinery in :mod:`robot_debug.batch_experiment`
(one prefetch, one faultline server with ``max_batch_size = 12``, an untimed
warm-up, concurrent single-episode evaluators with cancellation, the SQLite
scrub and the closed-evidence export):

``m6-smoke``
    A fixed manifest in one wave: nominal x6; the certified reduced agent-view
    mask plus the whole wrist image blacked out x12; the same rectangle on the
    wrist image only x12; and severity 0.6 x2 for each of the four scalar
    families.

``m6-threshold``
    Nominal controls x5, then one coarse-sweep-then-bisect threshold search per
    family (:mod:`robot_debug.threshold_search`). The families run concurrently
    and **share one pool of 12 evaluator workers**: each family's thread submits
    a level's attempts to the common FIFO queue and waits for them, so the four
    families interleave level by level on the same workers and the same server.

Infrastructure problems are never counted as policy failures. The first item
that is not a valid completed result cancels the whole pool, exactly as in M3.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from robot_debug import batch_experiment as be
from robot_debug.image_perturbation import physical_value
from robot_debug.job_runtime import M6_FAMILIES
from robot_debug.threshold_search import ThresholdStop, run_threshold_search

M6_WORKERS = 12
M6_MAX_BATCH_SIZE = 12
SUMMARY_NAME = "m6_summary.json"
NOMINAL_CONTROLS = 5
SMOKE_NOMINAL_REPEATS = 6
SMOKE_WRIST_REPEATS = 12
SMOKE_FAMILY_REPEATS = 2
SMOKE_SEVERITY = 0.6
# The certified M4 reduced rectangle (the same one M3 and M5B use) and a full-frame wrist mask.
REDUCED_MASK = {"x": 0.625, "y": 0.0, "width": 0.375, "height": 0.375}
WRIST_BLACK = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
KNOWN_OUTCOMES = {"nominal": "success"}
SMOKE_CONDITIONS = ("nominal", "agentview_mask_wrist_black", "wrist_mask_only")

# Timing assumptions behind the recommended Job deadlines (measured in M3, October 12).
ASSUMED_OVERHEAD_SECONDS = {
    "model_prefetch": 345.0,   # one model download on an L40S
    "export_preflight": 30.0,
    "server_start": 120.0,
    "warmup_episode": 60.0,
    "finalize_and_export": 90.0,
}
# One wave: 12 evaluators each finish an episode. M3 measured 16.3 episodes/min unbatched with
# 12 workers (12 x 60 / 16.3 = 44 s); batched it measured 19.2-19.4 (about 37 s).
ASSUMED_EPISODE_WALL_SECONDS = 44.0
# A family level competes with the other families' attempts for the same 12 workers, so it can
# take two waves; the sequential chain of levels is bounded by this.
ASSUMED_LEVEL_SECONDS = 90.0
DEADLINE_ROUNDING_SECONDS = 60
MAX_RECOMMENDED_DEADLINE_SECONDS = 2400


def severity_token(severity: float) -> str:
    return "s{:06d}".format(int(round(float(severity) * 1_000_000)))


# ---------------------------------------------------------------------------
# Per-camera effect probe (written by the benchmark beside each perturbed config)
# ---------------------------------------------------------------------------

PROBE_SUFFIX = ".camera_probe.json"
PROBE_CAMERAS = ("agentview", "wrist")
PROBE_MAX_BYTES = 16 * 1024


def probe_path(configs_dir: Path, case_id: str) -> Path:
    return Path(configs_dir) / (case_id + PROBE_SUFFIX)


def _reject_constant(value: str) -> None:
    raise ValueError("non-standard JSON constant: " + value)


def load_probe(path: Path) -> Optional[Dict[str, Any]]:
    """Read one probe sidecar; anything missing, oversized or malformed is ``None``."""

    try:
        path = Path(path)
        if path.stat().st_size > PROBE_MAX_BYTES:
            return None
        document = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (OSError, ValueError):
        return None
    if (
        not isinstance(document, dict) or document.get("schema_version") != 1
        or not isinstance(document.get("episodes"), list)
    ):
        return None
    return document


def _ratio(numerator: Any, denominator: Any) -> Optional[float]:
    if (
        isinstance(numerator, (int, float)) and isinstance(denominator, (int, float))
        and not isinstance(numerator, bool) and not isinstance(denominator, bool)
        and math.isfinite(numerator) and math.isfinite(denominator) and denominator > 0
    ):
        return numerator / denominator
    return None


def camera_effect(probes: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Median perturbed/unperturbed mean and std ratio per camera over every probe sample.

    A ratio of 1.0 means the camera's policy input was unchanged; the mean ratio
    shows brightness changes and occlusion, the std ratio shows lost or added
    contrast and detail. Zero denominators are skipped. ``None`` when there is no sample.
    """

    effect: Dict[str, Any] = {"items": len(probes)}
    found = False
    for camera in PROBE_CAMERAS:
        means: List[float] = []
        stds: List[float] = []
        samples = 0
        for probe in probes:
            for episode in probe.get("episodes", ()):
                for sample in episode.get("samples", ()) if isinstance(episode, Mapping) else ():
                    stats = sample.get(camera) if isinstance(sample, Mapping) else None
                    if not isinstance(stats, Mapping):
                        continue
                    samples += 1
                    mean = _ratio(stats.get("perturbed_mean"), stats.get("unperturbed_mean"))
                    std = _ratio(stats.get("perturbed_std"), stats.get("unperturbed_std"))
                    if mean is not None:
                        means.append(mean)
                    if std is not None:
                        stds.append(std)
        if samples:
            found = True
            effect[camera] = {
                "mean_ratio": be._round(be.percentile(means, 50), 4),
                "std_ratio": be._round(be.percentile(stds, 50), 4),
                "samples": samples,
            }
    return effect if found else None


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------


def _item(case_id: str, kind: str, config: Mapping[str, Any], **meta: Any) -> Dict[str, Any]:
    return {"case_id": case_id, "kind": kind, "config": dict(config), "meta": dict(meta, condition=kind)}


def nominal_controls(count: int = NOMINAL_CONTROLS, prefix: str = "nominal-control") -> List[Dict[str, Any]]:
    return [_item("{}-{:02d}".format(prefix, number), "nominal", {}, repeat=number)
            for number in range(1, count + 1)]


def scalar_config(family: str, severity: float) -> Dict[str, Any]:
    return {"image_perturbation": {"kind": family, "severity": round(float(severity), 6)}}


def smoke_manifest() -> List[Dict[str, Any]]:
    """The 38 fixed smoke items in submission order (the first nominal doubles as the warm-up)."""

    items = nominal_controls(SMOKE_NOMINAL_REPEATS, prefix="nominal")
    for number in range(1, SMOKE_WRIST_REPEATS + 1):
        items.append(_item(
            "agentview-mask-wrist-black-{:02d}".format(number), "agentview_mask_wrist_black",
            dict(REDUCED_MASK, wrist_occlusion=dict(WRIST_BLACK)), repeat=number))
    for number in range(1, SMOKE_WRIST_REPEATS + 1):
        items.append(_item(
            "wrist-mask-only-{:02d}".format(number), "wrist_mask_only",
            {"wrist_occlusion": dict(REDUCED_MASK)}, repeat=number))
    for family in M6_FAMILIES:
        kind = "{}_{:g}".format(family, SMOKE_SEVERITY)
        for number in range(1, SMOKE_FAMILY_REPEATS + 1):
            items.append(_item(
                "{}-{}-{:02d}".format(family, severity_token(SMOKE_SEVERITY), number), kind,
                scalar_config(family, SMOKE_SEVERITY), repeat=number,
                family=family, severity=SMOKE_SEVERITY))
    return items


def level_items(family: str, severity: float, attempts: int, phase: str = "sweep") -> List[Dict[str, Any]]:
    return [
        _item("{}-{}-a{:02d}".format(family, severity_token(severity), number), family,
              scalar_config(family, severity), family=family, severity=round(float(severity), 6),
              attempt=number, phase=phase)
        for number in range(1, attempts + 1)
    ]


# ---------------------------------------------------------------------------
# Deadline estimate
# ---------------------------------------------------------------------------


def planned_episodes(mode: str, config: Optional[Mapping[str, Any]] = None) -> int:
    """Worst-case valid episodes: the whole smoke manifest or every threshold level."""

    if mode == "m6-smoke":
        return len(smoke_manifest())
    levels = len(config["sweep"]) + config["bisection_steps"]
    return NOMINAL_CONTROLS + len(config["families"]) * levels * config["attempts"]


def threshold_waves(families: int, levels: int, attempts: int, workers: int = M6_WORKERS) -> int:
    """FIFO waves needed when ``families`` searches of ``levels`` levels share ``workers`` workers.

    Each family's next level is queued when its previous level's attempts have all
    finished; every wave runs up to ``workers`` queued attempts for one episode wall time.
    """

    queue_: List[List[int]] = [[family, attempts] for family in range(families)]
    pending = {family: attempts for family in range(families)}
    left = {family: levels for family in range(families)}
    waves = 0
    while queue_:
        slots = workers
        ran: Dict[int, int] = {}
        while slots and queue_:
            family, count = queue_[0]
            take = min(count, slots)
            ran[family] = ran.get(family, 0) + take
            slots -= take
            if take == count:
                queue_.pop(0)
            else:
                queue_[0] = [family, count - take]
        waves += 1
        for family, count in ran.items():
            pending[family] -= count
            if pending[family] == 0:
                left[family] -= 1
                if left[family] > 0:
                    pending[family] = attempts
                    queue_.append([family, attempts])
    return waves


def recommended_deadline_seconds(mode: str, config: Optional[Mapping[str, Any]] = None) -> int:
    """A Job ``deadline_seconds`` from the documented timing assumptions.

    The one-off overheads, plus the worst-case work in whole waves of 12
    episodes (the longer of the FIFO wave count and the sequential chain of
    two-wave levels for the threshold mode), plus the no-start guard: an item is
    never started with less than ``ITEM_TIMEOUT_SECONDS`` left, so the last item
    needs that much time plus one episode wall time. Rounded up to whole minutes;
    never below the prepare script's 1000 s floor, and refused above the
    2400 s cap this milestone allows.
    """

    wall = ASSUMED_EPISODE_WALL_SECONDS
    if mode == "m6-smoke":
        work = math.ceil(len(smoke_manifest()) / M6_WORKERS) * wall
    else:
        levels = len(config["sweep"]) + config["bisection_steps"]
        waves = 1 + threshold_waves(len(config["families"]), levels, config["attempts"])  # 1: controls
        chain = (1 + levels) * ASSUMED_LEVEL_SECONDS  # controls, then the longest sequential chain
        work = max(waves * wall, chain)
    total = sum(ASSUMED_OVERHEAD_SECONDS.values()) + work + be.ITEM_TIMEOUT_SECONDS + wall
    rounded = int(max(1000, math.ceil(total / DEADLINE_ROUNDING_SECONDS) * DEADLINE_ROUNDING_SECONDS))
    if rounded > MAX_RECOMMENDED_DEADLINE_SECONDS:
        raise ValueError("this workload needs more than the {} s cap; shrink it".format(
            MAX_RECOMMENDED_DEADLINE_SECONDS))
    return rounded


# ---------------------------------------------------------------------------
# Shared evaluator pool
# ---------------------------------------------------------------------------

JOIN_SECONDS = 30.0


def _join_all(threads: Sequence[threading.Thread], seconds: float) -> None:
    """Join every live thread under ONE shared deadline (not ``seconds`` each)."""

    deadline = time.monotonic() + seconds
    for thread in threads:
        if thread.is_alive():
            thread.join(max(0.0, deadline - time.monotonic()))


def snapshot_families(state: Mapping[str, Any], lock: Any) -> Dict[str, Any]:
    """A copy of the finished family results, taken under the lock the family threads write with."""

    with lock:
        return dict(state["families"])


class _Ticket:
    def __init__(self, item: Mapping[str, Any]) -> None:
        self.item = item
        self.event = threading.Event()
        self.record: Optional[Dict[str, Any]] = None


class EvaluatorPool:
    """A fixed number of worker threads draining one FIFO queue of single-episode items.

    Every submitted item gets a ticket whose record always ends up non-``None``:
    a started item has the evaluator's record; an item that never started is
    ``cancelled`` (the pool was cancelled) or ``deadline_skipped`` (fewer than
    ``item_timeout`` seconds remained, so it could have been cut short by the Job
    deadline). A started item that is not ``valid`` cancels the whole pool.
    """

    def __init__(
        self,
        *,
        workers: int,
        evaluate: Callable[..., Dict[str, Any]],
        remaining: Callable[[], float],
        item_timeout: float,
        cancel: threading.Event,
    ) -> None:
        self._evaluate = evaluate
        self._remaining = remaining
        self._item_timeout = item_timeout
        self.cancel = cancel
        self.deadline_stop = threading.Event()
        self._queue: "queue.Queue[Optional[_Ticket]]" = queue.Queue()
        self._lock = threading.Lock()
        self.results: List[Dict[str, Any]] = []
        self._not_started: Dict[str, int] = {}
        self._threads = [
            threading.Thread(target=self._work, name="m6-worker-{}".format(index), daemon=True)
            for index in range(workers)
        ]

    def start(self) -> None:
        for thread in self._threads:
            thread.start()

    def submit(self, item: Mapping[str, Any]) -> _Ticket:
        ticket = _Ticket(item)
        self._queue.put(ticket)
        return ticket

    @staticmethod
    def wait(tickets: Sequence[_Ticket]) -> None:
        for ticket in tickets:
            while not ticket.event.wait(0.5):
                pass  # short slices so a pending KeyboardInterrupt is delivered promptly

    def shutdown(self, join_seconds: float = JOIN_SECONDS) -> None:
        """Let queued items drain (they are cancelled when the pool is) and stop the workers.

        All workers share one ``join_seconds`` deadline, so a stuck pool costs 30 s, not 30 s each.
        """

        for _ in self._threads:
            self._queue.put(None)
        _join_all(self._threads, join_seconds)

    def not_started_counts(self) -> Dict[str, int]:
        """How many submitted items never started, by reason (cancelled, deadline_skipped, ...)."""

        with self._lock:
            return dict(sorted(self._not_started.items()))

    def _skipped(self, ticket: _Ticket, status: str) -> None:
        with self._lock:
            self._not_started[status] = self._not_started.get(status, 0) + 1
        ticket.record = {
            "case_id": str(ticket.item["case_id"]), "kind": ticket.item["kind"], "status": status,
            "outcome": None, "started": False,
        }
        if ticket.item.get("meta"):
            ticket.record.update(ticket.item["meta"])

    def _work(self) -> None:
        while True:
            ticket = self._queue.get()
            if ticket is None:
                return
            try:
                if self.cancel.is_set():
                    self._skipped(ticket, "cancelled")
                elif self._remaining() < self._item_timeout:
                    # Never start an item that the Job deadline could cut short.
                    self.deadline_stop.set()
                    self._skipped(ticket, "deadline_skipped")
                else:
                    record = self._evaluate(ticket.item)
                    with self._lock:
                        self.results.append(record)
                    if record["status"] != "valid":
                        self.cancel.set()
                    ticket.record = record
            except BaseException:
                self.cancel.set()
                self._skipped(ticket, "infrastructure_error")
            finally:
                ticket.event.set()


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def condition_stats(
    records: Sequence[Mapping[str, Any]], planned: Optional[Mapping[str, int]] = None
) -> Dict[str, Dict[str, Any]]:
    """Per-condition outcome counts and wall durations over the *valid* items."""

    kinds: List[str] = list(planned or ())
    for record in records:
        if record["kind"] not in kinds:
            kinds.append(record["kind"])
    table: Dict[str, Dict[str, Any]] = {}
    for kind in kinds:
        mine = [r for r in records if r["kind"] == kind]
        valid = [r for r in mine if r["status"] == "valid"]
        outcomes = be.outcomes_by_kind(mine).get(kind, {})
        durations = sorted(round(r["ended_seconds"] - r["started_seconds"], 3) for r in valid)
        steps = sorted(r["steps"] for r in valid if isinstance(r.get("steps"), int))
        table[kind] = {
            "planned": None if planned is None else planned.get(kind),
            "attempted": len([r for r in mine if r.get("started", True)]),
            "valid": len(valid),
            "outcomes": dict(sorted(outcomes.items())),
            "median_duration_seconds": be._round(be.percentile(durations, 50)),
            "durations_seconds": durations,
            "median_steps": be._round(be.percentile(steps, 50), 1),
        }
    return table


def nominal_summary(records: Sequence[Mapping[str, Any]], planned: int) -> Dict[str, Any]:
    nominal = [r for r in records if r["kind"] == "nominal" and r["status"] == "valid"]
    outcomes: Dict[str, int] = {}
    for record in nominal:
        outcomes[record["outcome"]] = outcomes.get(record["outcome"], 0) + 1
    return {
        "planned": planned,
        "valid": len(nominal),
        "outcomes": dict(sorted(outcomes.items())),
        "passed": len(nominal) == planned and outcomes.get("success", 0) == planned,
    }


def write_summary(root: Path, summary: Mapping[str, Any]) -> None:
    target = Path(root) / SUMMARY_NAME
    temporary = Path(root) / ("." + SUMMARY_NAME + ".tmp")
    payload = json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary.write_bytes(payload.encode("utf-8"))
    os.replace(str(temporary), str(target))


def _family_not_run(family: str, config: Mapping[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "family": family, "threshold_severity": None, "lower_bound": None, "resolution": None,
        "stop_reason": reason, "sweep": list(config["sweep"]), "attempts": config["attempts"],
        "required_failures": config["required_failures"],
        "bisection_steps": config["bisection_steps"], "bisection_steps_done": 0,
        "levels_tried": [], "attempts_used": 0, "levels": [], "threshold_physical": None,
    }


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def run_m6(
    *,
    mode: str,
    config: Optional[Mapping[str, Any]],
    batch_root: Path,
    log_root: Path,
    project_root: Path,
    model_factory: Callable[..., Any],
    set_model: Callable[[Any], None],
    run_item: Callable[..., Any],
    failure: Callable[[], Optional[str]],
    remaining: Callable[[], float],
    launch_deadline: float,
    clock: Callable[[], float] = time.monotonic,
    progress: Callable[..., None] = lambda _event, **_fields: None,
    write_config: Optional[Callable[..., None]] = None,
    load_result: Optional[Callable[[Path], Any]] = None,
    item_timeout: float = be.ITEM_TIMEOUT_SECONDS,
    prefetch: Optional[Callable[[], Any]] = None,
    snapshot: Callable[[], Mapping[str, Any]] = be.memory_snapshot,
    server_clock: Callable[[], float] = time.monotonic,
    workers: int = M6_WORKERS,
) -> Dict[str, Any]:
    """Run one M6 mode against a single freshly started 12-worker server; returns the summary.

    ``config`` is the validated threshold configuration (``None`` for the smoke
    mode). The injected ``run_item``, ``failure`` and ``remaining`` are the
    bounded runner and latch from ``run_workload``, as for the M3 phases.
    """

    if mode not in ("m6-smoke", "m6-threshold"):
        raise ValueError("unsupported M6 mode")
    if mode == "m6-threshold" and config is None:
        raise ValueError("the threshold mode needs its configuration")
    if write_config is None or load_result is None:
        from scripts import run_failure_search

        write_config = write_config or run_failure_search._write_config
        load_result = load_result or (
            lambda output: run_failure_search._load_stage_results(output, expected_count=1)[0]
        )
    # Family threads report concurrently; one line per event must not interleave.
    raw_progress = progress
    progress_lock = threading.Lock()

    def progress(event: str, **fields: Any) -> None:
        with progress_lock:
            raw_progress(event, **fields)

    batch_root = Path(batch_root)
    batch_root.mkdir(parents=True, exist_ok=True)
    configs = batch_root / "configs"
    runs = batch_root / "runs"
    configs.mkdir(exist_ok=True)
    runs.mkdir(exist_ok=True)
    timing_path = batch_root / "server-timing.jsonl"

    threshold = mode == "m6-threshold"
    extra: Dict[str, Any] = {"prefetch_seconds": None, "cleanup_unconfirmed": False}
    state: Dict[str, Any] = {
        "stop_reason": None, "warmup": None, "families": {}, "nominal_controls": None,
        "server_argv": None, "memory_start": None, "memory_end": None, "timing": None,
        "startup_seconds": None, "total_seconds": None, "warm_elapsed_seconds": None,
        "records": [], "planned_items": None, "not_started": {},
    }
    started_at = clock()
    scrub = {"companions_removed": 0}
    smoke_items = smoke_manifest() if not threshold else []
    controls = nominal_controls() if threshold else []

    probe_cache: Dict[str, Optional[Dict[str, Any]]] = {}

    def effect_for(subset: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
        """Camera effect over the *valid* items of a condition or level (warm-up never included)."""

        probes = []
        for record in subset:
            if record["status"] != "valid":
                continue
            case_id = record["case_id"]
            if case_id not in probe_cache:
                probe_cache[case_id] = load_probe(probe_path(configs, case_id))
            if probe_cache[case_id] is not None:
                probes.append(probe_cache[case_id])
        return camera_effect(probes)

    families_lock = threading.Lock()

    def enriched_families(finished: Mapping[str, Any]) -> Dict[str, Any]:
        records = state["records"]
        families: Dict[str, Any] = {}
        for name, result in finished.items():
            copy = dict(result)
            levels = []
            for level in result.get("levels", ()):
                item = dict(level)
                item["camera_effect"] = effect_for([
                    r for r in records if r.get("family") == name and r.get("severity") == level["severity"]])
                levels.append(item)
            copy["levels"] = levels
            threshold = result.get("threshold_severity")
            copy["threshold_camera_effect"] = next(
                (item["camera_effect"] for item in levels if item["severity"] == threshold), None)
            families[name] = copy
        return families

    def build() -> Dict[str, Any]:
        records = sorted(state["records"], key=lambda r: r["case_id"])
        started = [r for r in records if r.get("started", True)]
        valid = [r for r in records if r["status"] == "valid"]
        planned_by_kind: Optional[Dict[str, int]] = None
        if not threshold:
            planned_by_kind = {}
            for item in smoke_items:
                planned_by_kind[item["kind"]] = planned_by_kind.get(item["kind"], 0) + 1
        nominal_planned = NOMINAL_CONTROLS if threshold else SMOKE_NOMINAL_REPEATS
        finished_families = snapshot_families(state, families_lock)
        conditions = condition_stats(records, planned_by_kind)
        for kind, row in conditions.items():
            row["camera_effect"] = effect_for([r for r in records if r["kind"] == kind])
        summary: Dict[str, Any] = {
            "schema_version": 1,
            "mode": mode,
            "workers": workers,
            "max_batch_size": M6_MAX_BATCH_SIZE,
            "config": None if config is None else {
                key: config[key] for key in ("families", "sweep", "attempts", "required_failures",
                                              "bisection_steps")},
            "stop_reason": state["stop_reason"],
            "planned_items": len(smoke_items) if not threshold else None,
            "attempted": len(started),
            "valid_count": len(valid),
            "conditions": conditions,
            "nominal_controls": state["nominal_controls"] or nominal_summary(records, nominal_planned),
            "families": enriched_families(finished_families),
            "warmup": state["warmup"],
            "server_argv": state["server_argv"],
            "memory_start": state["memory_start"],
            "memory_end": state["memory_end"],
            "timing": state["timing"],
            "startup_seconds": state["startup_seconds"],
            "warm_elapsed_seconds": state["warm_elapsed_seconds"],
            "total_seconds": state["total_seconds"],
            "not_started": dict(state["not_started"]),
            "sqlite_companions_removed": scrub["companions_removed"],
            "items": records,
        }
        summary.update(extra)
        if not threshold:
            summary["complete"] = len(valid) == len(smoke_items)
            summary["all_nominal_succeeded"] = summary["nominal_controls"]["passed"]
        else:
            summary["complete"] = (
                state["stop_reason"] is None and bool(finished_families)
                and all(item.get("stop_reason") in ("threshold_found", "no_reproducible_failure")
                        for item in finished_families.values())
            )
        return summary

    def save() -> Dict[str, Any]:
        summary = build()
        write_summary(batch_root, summary)
        return summary

    cancel = threading.Event()
    pool: Optional[EvaluatorPool] = None
    launch_t: Optional[float] = None
    warmup_seconds = 0.0
    try:
        if be.run_prefetch(prefetch, clock, progress, extra):
            state["stop_reason"] = "prefetch_failed"
        else:
            state["memory_start"] = dict(snapshot())
            progress("m6_start", mode=mode, workers=workers, **dict(state["memory_start"]))
            phase_started = clock()
            try:
                with be.started_server(
                    model_factory=model_factory, set_model=set_model, log_root=log_root,
                    max_batch_size=M6_MAX_BATCH_SIZE, timing_log=timing_path,
                    launch_deadline=launch_deadline,
                ) as (_model, server_argv):
                    state["server_argv"] = server_argv
                    ready_at = clock()
                    state["startup_seconds"] = be._round(ready_at - phase_started)
                    evaluate = be.make_evaluate(
                        stage_prefix="m6-", project_root=project_root, write_config=write_config,
                        load_result=load_result, run_item=run_item, cancel=cancel,
                        item_timeout=item_timeout, clock=clock, ready_at=ready_at,
                        configs_dir=configs, runs_dir=runs,
                        config_kwargs=lambda item: item["config"],
                    )
                    pool = EvaluatorPool(workers=workers, evaluate=evaluate, remaining=remaining,
                                         item_timeout=item_timeout, cancel=cancel)
                    try:
                        first = (smoke_items or controls)[0]
                        warm, warmup_seconds, skipped = be.run_warmup(
                            evaluate=evaluate, first=first, batch_root=batch_root, remaining=remaining,
                            item_timeout=item_timeout, clock=clock, known_outcomes=KNOWN_OUTCOMES,
                        )
                        state["warmup"] = warm
                        progress("m6_warmup_done", status=warm.get("status"), outcome=warm.get("outcome"),
                                 duration_seconds=warm.get("duration_seconds"))
                        if skipped:
                            state["stop_reason"] = "deadline_exhausted"
                        elif warm["status"] != "valid":
                            state["stop_reason"] = failure() or "warmup_failed"
                            cancel.set()
                        if state["stop_reason"] is None:
                            launch_t = server_clock()
                            pool.start()
                            if threshold:
                                _run_threshold(
                                    pool=pool, config=config, controls=controls, state=state,
                                    failure=failure, remaining=remaining, item_timeout=item_timeout,
                                    progress=progress, save=save, families_lock=families_lock)
                            else:
                                _run_smoke(pool=pool, items=smoke_items, state=state, failure=failure,
                                           progress=progress)
                    except BaseException:
                        # Mirror M3: cancel first, so the evaluators die before the server does.
                        cancel.set()
                        raise
                    finally:
                        # Evaluators are cancelled, joined and gone before the server closes.
                        pool.shutdown()
            except be.PhaseFailure as error:
                state["stop_reason"] = error.reason
            state["memory_end"] = dict(snapshot())
    except BaseException:
        cancel.set()
        raise
    finally:
        if pool is not None:
            state["records"] = list(pool.results)
            state["not_started"] = pool.not_started_counts()
        # Killed evaluators can leave SQLite companions and half-written media behind.
        for entry in state["records"]:
            if entry["status"] in ("cancelled", "timed_out") and entry.get("started", True):
                entry["run_dir_removed"] = be.remove_tree_within(runs / entry["case_id"], batch_root)
        scrub["companions_removed"] += be.purge_sqlite_companions(batch_root)
        state["total_seconds"] = be._round(clock() - started_at)
        finished = [r for r in state["records"] if r.get("ended_seconds") is not None]
        if finished:
            warm_elapsed = max(r["ended_seconds"] for r in finished) - min(r["started_seconds"] for r in finished)
            state["warm_elapsed_seconds"] = be._round(max(warm_elapsed, 1e-6))
            if launch_t is not None:
                state["timing"] = be.timing_stats(timing_path, state["warm_elapsed_seconds"], min_t=launch_t)
        summary = save()
    progress(
        "m6_summary", mode=mode, stop_reason=summary["stop_reason"], complete=summary["complete"],
        nominal=summary["nominal_controls"],
        thresholds={name: item.get("threshold_severity") for name, item in summary["families"].items()},
        family_stops={name: item.get("stop_reason") for name, item in summary["families"].items()},
        valid=summary["valid_count"], sqlite_companions_removed=summary["sqlite_companions_removed"],
    )
    return summary


def _wait_and_classify(pool: EvaluatorPool, items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    tickets = [pool.submit(item) for item in items]
    pool.wait(tickets)
    return [ticket.record for ticket in tickets]  # type: ignore[misc]


def _run_smoke(
    *, pool: EvaluatorPool, items: Sequence[Mapping[str, Any]], state: Dict[str, Any],
    failure: Callable[[], Optional[str]], progress: Callable[..., None],
) -> None:
    records = _wait_and_classify(pool, items)
    state["records"] = list(pool.results)
    bad = [r for r in records if r["status"] != "valid"]
    if bad:
        state["stop_reason"] = failure() or (
            "deadline_exhausted" if pool.deadline_stop.is_set() else "phase_incomplete")
    state["nominal_controls"] = nominal_summary(pool.results, SMOKE_NOMINAL_REPEATS)
    progress("m6_smoke_done", valid=len(records) - len(bad), invalid=len(bad))


def _run_threshold(
    *, pool: EvaluatorPool, config: Mapping[str, Any], controls: Sequence[Mapping[str, Any]],
    state: Dict[str, Any], failure: Callable[[], Optional[str]], remaining: Callable[[], float],
    item_timeout: float, progress: Callable[..., None], save: Callable[[], Any],
    families_lock: Any,
) -> None:
    control_records = _wait_and_classify(pool, controls)
    state["records"] = list(pool.results)
    state["nominal_controls"] = nominal_summary(pool.results, NOMINAL_CONTROLS)
    progress("m6_controls_done", **state["nominal_controls"])
    invalid = [r for r in control_records if r["status"] != "valid"]
    if invalid:
        state["stop_reason"] = failure() or (
            "deadline_exhausted" if pool.deadline_stop.is_set() else "controls_incomplete")
        with families_lock:
            for family in config["families"]:
                state["families"][family] = _family_not_run(family, config, "not_run")
        return
    if not state["nominal_controls"]["passed"]:
        state["stop_reason"] = "nominal_controls_failed"
        with families_lock:
            for family in config["families"]:
                state["families"][family] = _family_not_run(family, config, "nominal_failed")
        save()
        return
    save()

    def run_family(family: str) -> None:
        def evaluate_level(severity: float, attempts: int) -> List[str]:
            records = _wait_and_classify(pool, level_items(family, severity, attempts))
            outcomes = [r["outcome"] if r["status"] == "valid" else "infrastructure_error" for r in records]
            progress("m6_level_done", family=family, severity=severity,
                     failures=outcomes.count("policy_failure"), outcomes=outcomes)
            if any(r["status"] != "valid" for r in records):
                if pool.deadline_stop.is_set() and all(
                    r["status"] in ("valid", "deadline_skipped") for r in records
                ):
                    raise ThresholdStop("deadline_exhausted", [o for o in outcomes if o != "infrastructure_error"])
            return outcomes

        try:
            result = run_threshold_search(
                evaluate_level,
                sweep=config["sweep"], attempts=config["attempts"],
                required_failures=config["required_failures"],
                bisection_steps=config["bisection_steps"],
                can_start=lambda: remaining() >= item_timeout,
                physical=lambda severity: physical_value(family, severity),
            )
        except BaseException as error:  # a bug here must stop the experiment, never pass as a result
            pool.cancel.set()
            result = _family_not_run(family, config, "infrastructure_error")
            result["error"] = type(error).__name__
        result["family"] = family
        with families_lock:
            state["families"][family] = result
        progress("m6_family_done", family=family, stop_reason=result["stop_reason"],
                 threshold_severity=result["threshold_severity"], lower_bound=result["lower_bound"])

    threads = [threading.Thread(target=run_family, args=(family,), name="m6-family-" + family, daemon=True)
               for family in config["families"]]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            while thread.is_alive():
                thread.join(0.5)
    except BaseException:
        pool.cancel.set()
        _join_all(threads, JOIN_SECONDS)
        raise
    finally:
        state["records"] = list(pool.results)
    with families_lock:
        stops = {item["stop_reason"] for item in state["families"].values()}
    clean = {"threshold_found", "no_reproducible_failure"}
    if not stops <= clean:
        if failure() is not None:
            state["stop_reason"] = failure()
        elif "deadline_exhausted" in stops or pool.deadline_stop.is_set():
            state["stop_reason"] = "deadline_exhausted"
        else:
            state["stop_reason"] = "phase_incomplete"


__all__ = [
    "EvaluatorPool",
    "M6_MAX_BATCH_SIZE",
    "M6_WORKERS",
    "SUMMARY_NAME",
    "level_items",
    "nominal_controls",
    "planned_episodes",
    "recommended_deadline_seconds",
    "run_m6",
    "smoke_manifest",
]
