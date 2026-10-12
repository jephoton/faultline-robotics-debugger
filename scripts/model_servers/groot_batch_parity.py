"""Seeded batch-versus-single parity check for the Faultline GR00T server.

Runs under the model environment (``/opt/model-env/bin/python``) on the GPU,
with the same ``--args.*`` flags as the model-server Job. It constructs
``FaultlineGrootServer`` once, builds two synthetic observations A and B (fixed
random images, distinct states, the task-0 instruction) and checks that every
item of ``predict_batch`` matches the single-observation ``predict`` of the same
observation within bf16 tolerance.

GR00T samples its actions from flow-matching noise, so equality needs identical
noise per item. Two noise modes are available:

* ``per-item`` (default): while a call runs, ``torch.randn`` draws item ``i`` from
  its own CPU generator seeded ``seed + offset[i]``. A batched call and the
  matching single call therefore see identical noise by construction, which does
  not depend on how the CUDA generator lays out a larger draw. This also lets
  the check cover item 1 of each batch, not only item 0.
* ``manual-seed``: only ``torch.manual_seed(seed)`` before each call, relying on
  the first slice of a batched ``randn`` equalling the single-call draw. Only
  item 0 can be compared in this mode.

``parity.json`` records pass/fail and maxima only; the exit code is 0 on pass
and 1 on any failure (including an exception).
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

import numpy as np

DEFAULT_TOLERANCE = 0.05
DEFAULT_SEED = 1234
DEFAULT_IMAGE_SIZE = 256
DEFAULT_STATE_DIM = 8
TASK_ZERO_INSTRUCTION = "pick up the alphabet soup and place it in the basket"
NOISE_MODES = ("per-item", "manual-seed")


def max_abs_diff(left: Any, right: Any) -> float:
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.shape != b.shape:
        return float("inf")
    return float(np.max(np.abs(a - b))) if a.size else 0.0


def build_observations(
    *, image_size: int = DEFAULT_IMAGE_SIZE, state_dim: int = DEFAULT_STATE_DIM,
    task: str = TASK_ZERO_INSTRUCTION, seed: int = DEFAULT_SEED,
) -> List[Dict[str, Any]]:
    """Two fixed synthetic observations in the harness format; A and B differ everywhere."""

    observations = []
    for index in range(2):
        rng = np.random.RandomState(seed + 101 * (index + 1))
        observations.append({
            "images": {
                "agentview": rng.randint(0, 256, size=(image_size, image_size, 3)).astype(np.uint8),
                "wrist": rng.randint(0, 256, size=(image_size, image_size, 3)).astype(np.uint8),
            },
            "states": rng.uniform(-1.0, 1.0, size=state_dim).astype(np.float32),
            "task_description": task,
        })
    return observations


@contextmanager
def per_item_noise(torch: Any, seed: int, offsets: Sequence[int], counter: Dict[str, int]) -> Iterator[None]:
    """Make ``torch.randn`` draw batch item ``i`` from a generator seeded ``seed + offsets[i]``."""

    original = torch.randn

    def randn(*size: Any, **kwargs: Any) -> Any:
        if size and len(size) == 1 and isinstance(size[0], (tuple, list)):
            shape = tuple(size[0])
        elif size:
            shape = tuple(size)
        else:
            shape = tuple(kwargs.get("size", ()))
        if not shape or shape[0] != len(offsets):
            return original(*size, **kwargs)
        rest = {key: value for key, value in kwargs.items() if key not in ("size", "device", "dtype", "generator")}
        pieces = []
        for offset in offsets:
            generator = torch.Generator()
            generator.manual_seed(int(seed) + int(offset))
            pieces.append(original((1,) + shape[1:], generator=generator, **rest))
        counter["calls"] = counter.get("calls", 0) + 1
        draw = torch.cat(pieces, dim=0)
        target = {key: kwargs[key] for key in ("device", "dtype") if kwargs.get(key) is not None}
        return draw.to(**target) if target else draw

    torch.randn = randn
    try:
        yield
    finally:
        torch.randn = original


def run_parity(
    server: Any,
    observations: Sequence[Dict[str, Any]],
    *,
    noise: Callable[[Sequence[int]], Any],
    per_item: bool,
    tolerance: float = DEFAULT_TOLERANCE,
) -> Dict[str, Any]:
    """Run the parity checks. ``noise(offsets)`` returns a context manager for one call."""

    a, b = observations
    ctxs = [SimpleNamespace(session_id="parity-a"), SimpleNamespace(session_id="parity-b")]

    def single(obs: Dict[str, Any], ctx: Any, offset: int) -> np.ndarray:
        with noise([offset]):
            return np.asarray(server.predict(obs, ctx)["actions"])

    def batch(order: Sequence[int]) -> List[np.ndarray]:
        pair = [observations[i] for i in order]
        with noise(list(range(len(pair)))):
            results = server.predict_batch(pair, [ctxs[i] for i in order])
        return [np.asarray(result["actions"]) for result in results]

    solo_a, solo_b = single(a, ctxs[0], 0), single(b, ctxs[1], 0)
    batch_ab, batch_ba = batch([0, 1]), batch([1, 0])

    checks: Dict[str, Dict[str, Any]] = {}

    def equivalence(name: str, left: np.ndarray, right: np.ndarray) -> None:
        diff = max_abs_diff(left, right)
        checks[name] = {"max_abs_diff": diff, "passed": bool(diff <= tolerance)}

    equivalence("batch_ab_item0_vs_single_a", batch_ab[0], solo_a)
    equivalence("batch_ba_item0_vs_single_b", batch_ba[0], solo_b)
    if per_item:
        equivalence("batch_ab_item1_vs_single_b", batch_ab[1], single(b, ctxs[1], 1))
        equivalence("batch_ba_item1_vs_single_a", batch_ba[1], single(a, ctxs[0], 1))

    distinct = max_abs_diff(solo_a, solo_b)
    checks["single_a_vs_single_b_differ"] = {"max_abs_diff": distinct, "passed": bool(distinct > tolerance)}

    arrays = [solo_a, solo_b] + batch_ab + batch_ba
    shapes_match = len({tuple(array.shape) for array in arrays}) == 1
    dtypes_match = len({str(array.dtype) for array in arrays}) == 1
    checks["shapes_and_dtypes_match"] = {"passed": bool(shapes_match and dtypes_match)}

    equivalence_diffs = [
        value["max_abs_diff"] for name, value in checks.items() if name.startswith("batch_")
    ]
    return {
        "schema_version": 1,
        "passed": all(value["passed"] for value in checks.values()),
        "tolerance": tolerance,
        "max_abs_diff": max(equivalence_diffs),
        "observed_distinct_diff": distinct,
        "shapes_match": shapes_match,
        "dtypes_match": dtypes_match,
        "checks": checks,
        "error": None,
    }


def write_result(path: Path, result: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes((json.dumps(result, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    os.replace(str(temporary), str(path))


def failure_result(error: BaseException, *, tolerance: float, noise_mode: str, seed: int) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "passed": False,
        "tolerance": tolerance,
        "noise_mode": noise_mode,
        "seed": seed,
        "checks": {},
        "error": "{}: {}".format(type(error).__name__, str(error)[:300]),
    }


def _parse(argv: Optional[Sequence[str]], server_cls: Any) -> Any:
    from jsonargparse import ArgumentParser

    parser = ArgumentParser(description="GR00T batch parity check")
    parser.add_argument("--output", required=True, type=Path, help="Path of parity.json")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--noise", choices=NOISE_MODES, default="per-item")
    parser.add_argument("--image-size", type=int, default=DEFAULT_IMAGE_SIZE)
    parser.add_argument("--state-dim", type=int, default=DEFAULT_STATE_DIM)
    parser.add_class_arguments(server_cls, nested_key="args", fail_untyped=False, sub_configs=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    from faultline_groot_server import FaultlineGrootServer

    config = _parse(argv, FaultlineGrootServer)
    per_item = config.noise == "per-item"
    try:
        import torch

        server = FaultlineGrootServer(**config.args.as_dict())
        counter: Dict[str, int] = {}

        def noise(offsets: Sequence[int]) -> Any:
            torch.manual_seed(config.seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(config.seed)
            if per_item:
                return per_item_noise(torch, config.seed, offsets, counter)
            return _null_context()

        observations = build_observations(
            image_size=config.image_size, state_dim=config.state_dim, seed=config.seed
        )
        result = run_parity(
            server, observations, noise=noise, per_item=per_item, tolerance=config.tolerance
        )
        result.update({"noise_mode": config.noise, "seed": config.seed, "noise_draws_intercepted": counter.get("calls", 0)})
        if per_item and counter.get("calls", 0) == 0:
            result["passed"] = False
            result["error"] = "per-item noise never engaged; torch.randn was not called with a batch dimension"
    except Exception as error:  # a parity run must always leave a verdict behind
        result = failure_result(error, tolerance=config.tolerance, noise_mode=config.noise, seed=config.seed)
    write_result(config.output, result)
    return 0 if result["passed"] else 1


@contextmanager
def _null_context() -> Iterator[None]:
    yield


if __name__ == "__main__":
    sys.exit(main())
