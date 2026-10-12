"""Instrumented, batch-capable GR00T model server for the M3 batching experiment.

Runs under the model environment's Python (``/opt/model-env/bin/python``), like
the upstream ``vla_eval/model_servers/lerobot.py`` it extends. It must not
import ``robot_debug``: that package is not installed in the model environment.

What it adds to upstream ``LeRobotModelServer`` (upstream files stay unmodified):

* ``predict_batch``: builds each item's raw frame exactly as upstream
  ``predict()`` does, prepares each item with the same LeRobot helper, then
  stacks the prepared tensors (tasks become a list) so the GR00T processor sees
  ONE batch. The processor keeps a per-instance raw-state cache that is used to
  decode relative actions, so a batch must be preprocessed as a batch, never per
  item and then concatenated afterwards. One ``predict_action_chunk`` call and
  one postprocess run, and the result is split along dim 0 per session.
* ``--args.timing_log``: one JSON line per inference call with the batch size,
  inference time and per-item wait (observation arrival to inference start).
  Only numbers are written, never observations, images or task text.

``predict()`` is upstream's, so ``max_batch_size == 1`` keeps the original
single-observation path behind the original lock.

The ``--args.*`` flags are the upstream ones (``run_server`` builds them from the
constructor signature), plus ``--args.max_batch_size`` (already supported by
``PredictModelServer``) and ``--args.timing_log``.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import signal
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from vla_eval.model_servers.lerobot import LeRobotModelServer

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL_SECONDS = 1.0
_SIGTERM_EXIT_STATUS = 143
_SHUTDOWN_FLUSH_TIMEOUT_SECONDS = 1.0


# ---------------------------------------------------------------------------
# Pure helpers (importable and testable without torch)
# ---------------------------------------------------------------------------


def stack_frames(frames: Sequence[Dict[str, Any]], cat: Callable[..., Any]) -> Dict[str, Any]:
    """Combine per-item prepared frames into one batch.

    Every frame comes from ``prepare_observation_for_inference``: tensor values
    already carry a batch dimension of one, ``task`` and ``robot_type`` are
    strings. Tensors are concatenated along dim 0 with ``cat`` (``torch.cat``);
    tasks become a list in item order; other strings must agree across items.
    """

    if not frames:
        raise ValueError("cannot stack an empty batch")
    keys = list(frames[0])
    for frame in frames[1:]:
        if set(frame) != set(keys):
            raise ValueError("batched frames must have the same keys")
    batch: Dict[str, Any] = {}
    for key in keys:
        values = [frame[key] for frame in frames]
        if key == "task":
            batch[key] = [str(value) for value in values]
        elif isinstance(values[0], str):
            if any(value != values[0] for value in values):
                raise ValueError("batched frames disagree on {}".format(key))
            batch[key] = values[0]
        else:
            batch[key] = cat(values, dim=0)
    return batch


def split_actions(chunk: Any, expected: int) -> List[Dict[str, np.ndarray]]:
    """Split a ``(B, n_steps, action_dim)`` chunk into per-session actions."""

    array = np.asarray(chunk)
    if array.ndim != 3:
        raise RuntimeError("expected a (batch, steps, action_dim) chunk, got {}".format(tuple(array.shape)))
    if array.shape[0] != expected:
        raise RuntimeError(
            "policy returned a batch of {} for {} observations".format(array.shape[0], expected)
        )
    return [{"actions": np.array(array[index], dtype=np.float32)} for index in range(expected)]


def timing_record(
    start: float, batch_size: int, inference_ms: float, wait_ms: Sequence[float]
) -> Dict[str, Any]:
    """One log line: numbers only."""

    if len(wait_ms) != batch_size:
        raise ValueError("wait_ms must have one entry per batch item")
    return {
        "t": round(float(start), 3),
        "batch_size": int(batch_size),
        "inference_ms": round(float(inference_ms), 3),
        "wait_ms": [round(float(value), 3) for value in wait_ms],
    }


class TimingLog:
    """Buffered JSONL timing writer plus per-session arrival bookkeeping."""

    def __init__(
        self,
        path: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        flush_interval: float = _FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self._path = path
        self._clock = clock
        self._flush_interval = flush_interval
        self._lock = threading.Lock()
        self._arrivals: Dict[str, float] = {}
        self._buffer: List[str] = []
        self._last_flush = clock()

    def note_arrival(self, session_id: str) -> None:
        with self._lock:
            self._arrivals[session_id] = self._clock()

    def forget(self, session_id: str) -> None:
        with self._lock:
            self._arrivals.pop(session_id, None)

    def take_waits(self, session_ids: Sequence[str], start: float) -> List[float]:
        """Milliseconds from each session's arrival to ``start`` (0 if unknown)."""

        with self._lock:
            waits = []
            for session_id in session_ids:
                arrived = self._arrivals.pop(session_id, None)
                waits.append(0.0 if arrived is None else max(0.0, (start - arrived) * 1000.0))
            return waits

    def record(self, start: float, batch_size: int, inference_ms: float, wait_ms: Sequence[float]) -> None:
        line = json.dumps(
            timing_record(start, batch_size, inference_ms, wait_ms), sort_keys=True, separators=(",", ":")
        )
        with self._lock:
            self._buffer.append(line)
            if self._clock() - self._last_flush >= self._flush_interval:
                self._flush_locked()

    def flush(self, timeout: Optional[float] = None) -> bool:
        """Write buffered lines; with a timeout, give up (and drop them) if the lock stays busy.

        The SIGTERM handler runs on the thread that may already hold the
        non-reentrant lock, so it must never wait for it indefinitely.
        """

        if timeout is None:
            self._lock.acquire()
        elif not self._lock.acquire(timeout=timeout):
            return False
        try:
            self._flush_locked()
        finally:
            self._lock.release()
        return True

    def _flush_locked(self) -> None:
        self._last_flush = self._clock()
        if not self._buffer:
            return
        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self._path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(self._buffer) + "\n")
        self._buffer = []


def make_shutdown_handler(log: TimingLog, exit_fn: Callable[[int], Any] = os._exit) -> Callable[..., None]:
    """SIGTERM handler: flush the buffered timing lines, then exit immediately."""

    def handler(_signum: int, _frame: Any) -> None:
        try:
            log.flush(timeout=_SHUTDOWN_FLUSH_TIMEOUT_SECONDS)
        finally:
            exit_fn(_SIGTERM_EXIT_STATUS)

    return handler


def install_shutdown_flush(log: TimingLog) -> None:
    """Flush on normal exit and on SIGTERM (how the Job stops this server)."""

    atexit.register(log.flush)
    try:
        signal.signal(signal.SIGTERM, make_shutdown_handler(log))
    except (ValueError, OSError):  # not the main thread, or no such signal here
        logger.warning("could not install the SIGTERM timing flush")


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class FaultlineGrootServer(LeRobotModelServer):
    """Upstream LeRobot server plus true batching and per-call timing."""

    def __init__(self, *, timing_log: Optional[str] = None, **kwargs: Any) -> None:
        """
        Args:
            timing_log: Path of a JSONL file that receives one line per
                inference call (batch size, inference ms, per-item wait ms).
                ``None`` disables instrumentation.
        """
        super().__init__(**kwargs)
        if self.max_batch_size > 1 and self._use_select_action:
            raise ValueError("max_batch_size > 1 is not supported together with use_select_action")
        self._timing: Optional[TimingLog] = None
        if timing_log:
            self._timing = TimingLog(str(timing_log))
            install_shutdown_flush(self._timing)

    # -- shared frame construction ------------------------------------------------

    def _raw_frame(self, obs: Any) -> Dict[str, np.ndarray]:
        """The raw frame upstream ``predict()`` builds before preparing it."""

        images = obs.get("images", {}) or {}
        frame: Dict[str, np.ndarray] = {}
        for bench_key, policy_key in self._resolve_image_map(images).items():
            frame[policy_key] = self._resize_to_declared(np.asarray(images[bench_key], dtype=np.uint8), policy_key)

        if self.state_key:
            raw_state = obs.get("states", obs.get("state"))
            if raw_state is not None:
                frame[self.state_key] = np.asarray(raw_state, dtype=np.float32)
        return frame

    # -- inference ----------------------------------------------------------------

    def predict(self, obs: Any, ctx: Any) -> Any:
        if self._timing is None:
            return super().predict(obs, ctx)
        start = time.monotonic()
        waits = self._timing.take_waits([ctx.session_id], start)
        result = super().predict(obs, ctx)
        self._timing.record(start, 1, (time.monotonic() - start) * 1000.0, waits)
        return result

    def predict_batch(self, obs_batch: List[Any], ctx_batch: List[Any]) -> List[Dict[str, np.ndarray]]:
        if not obs_batch:
            raise ValueError("predict_batch needs at least one observation")
        if self._timing is None:
            return self._predict_batch(obs_batch)
        start = time.monotonic()
        waits = self._timing.take_waits([ctx.session_id for ctx in ctx_batch], start)
        results = self._predict_batch(obs_batch)
        self._timing.record(start, len(obs_batch), (time.monotonic() - start) * 1000.0, waits)
        return results

    def _predict_batch(self, obs_batch: List[Any]) -> List[Dict[str, np.ndarray]]:
        if self._use_select_action:
            raise RuntimeError("predict_batch does not support use_select_action")
        torch = self._torch
        from lerobot.policies.utils import prepare_observation_for_inference

        prepared = []
        for obs in obs_batch:
            task = obs.get("task_description", "")
            prepared.append(
                prepare_observation_for_inference(
                    self._raw_frame(obs), self._device, task=task, robot_type=self.robot_type
                )
            )
        batch = stack_frames(prepared, torch.cat)
        try:
            batch = self._preprocess(batch)
        except Exception as error:
            raise RuntimeError(
                "GR00T processor rejected a batched input ({}: {}); batching is not usable as-is".format(
                    type(error).__name__, error
                )
            ) from error

        with torch.inference_mode():
            chunk = self._policy.predict_action_chunk(batch)
        chunk = self._postprocess(chunk)

        # (B, n_steps, action_dim) -> one (n_steps, action_dim) float32 chunk per session.
        array = chunk.detach().to("cpu").numpy()
        return split_actions(array, len(obs_batch))

    # -- instrumentation hooks ----------------------------------------------------

    async def on_observation(self, obs: Any, ctx: Any) -> None:
        if self._timing is not None:
            self._timing.note_arrival(ctx.session_id)
        await super().on_observation(obs, ctx)

    async def on_episode_end(self, result: Any, ctx: Any) -> None:
        if self._timing is not None:
            self._timing.forget(ctx.session_id)
        await super().on_episode_end(result, ctx)


if __name__ == "__main__":
    from vla_eval.model_servers.serve import run_server

    run_server(FaultlineGrootServer)
