"""Single-strength image perturbation families (ADR 0026) with replayable noise.

Each family is described by one normalised severity ``s`` in [0, 1] that maps to
a physical parameter. ``s = 0`` is the exact identity. Everything is pure NumPy
on HxWx3 uint8 RGB images so it runs unchanged in the simulator environment.

Mappings:

* ``darken``   brightness multiplier ``1 - 0.95 s`` (x1.0 down to x0.05)
* ``noise``    additive Gaussian noise, sigma ``100 s`` of 255, clipped to uint8
* ``blur``     Gaussian blur, sigma ``8 s`` pixels (separable, edge-replicated)
* ``contrast`` ``mean + (1 - 0.9 s) (x - mean)`` with the per-image mean

Noise is a deterministic function of (episode seed, step index, camera, kind,
severity) through a stable SHA-256 hash, never Python's salted ``hash()``, so a
replay reproduces every frame exactly (for a fixed NumPy build).
"""

from __future__ import annotations

from dataclasses import dataclass
import functools
import hashlib
import math
from typing import Any, Dict, Mapping, Optional

import numpy as np

KINDS = ("darken", "noise", "blur", "contrast")

DARKEN_MAX_REDUCTION = 0.95
NOISE_SIGMA_MAX = 100.0
BLUR_SIGMA_MAX_PIXELS = 8.0
CONTRAST_MAX_REDUCTION = 0.9

_PHYSICAL_NAMES = {
    "darken": "brightness_factor",
    "noise": "noise_sigma",
    "blur": "blur_sigma_px",
    "contrast": "contrast_factor",
}


def _canonical(part: Any) -> str:
    if isinstance(part, bool):
        raise TypeError("seed parts must be integers, floats or strings")
    if isinstance(part, float):
        return "f{:.6f}".format(part)
    if isinstance(part, int):
        return "i{}".format(part)
    if isinstance(part, str):
        return "s" + part
    raise TypeError("seed parts must be integers, floats or strings")


def stable_seed(*parts: Any) -> int:
    """A 64-bit seed that depends only on the parts' values, in every process."""

    text = "\x1f".join(_canonical(part) for part in parts)
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


def _validate_severity(severity: Any) -> float:
    if isinstance(severity, bool) or not isinstance(severity, (int, float)):
        raise TypeError("severity must be a finite number")
    if not math.isfinite(severity):
        raise ValueError("severity must be finite")
    if not 0 <= severity <= 1:
        raise ValueError("severity must be between 0 and 1")
    return float(severity)


def physical_value(kind: str, severity: float) -> Dict[str, Any]:
    """The physical parameter a severity maps to, as ``{"name", "value"}``."""

    if kind not in KINDS:
        raise ValueError("unknown perturbation kind")
    s = _validate_severity(severity)
    value = {
        "darken": 1.0 - DARKEN_MAX_REDUCTION * s,
        "noise": NOISE_SIGMA_MAX * s,
        "blur": BLUR_SIGMA_MAX_PIXELS * s,
        "contrast": 1.0 - CONTRAST_MAX_REDUCTION * s,
    }[kind]
    return {"name": _PHYSICAL_NAMES[kind], "value": round(value, 6)}


@functools.lru_cache(maxsize=64)
def _blur_matrix(size: int, sigma: float) -> np.ndarray:
    """A (size x size) banded Gaussian operator with edge-replicated borders."""

    radius = max(1, int(math.ceil(3.0 * sigma)))
    offsets = np.arange(-radius, radius + 1)
    weights = np.exp(-(offsets.astype(np.float64) ** 2) / (2.0 * sigma * sigma))
    weights /= weights.sum()
    matrix = np.zeros((size, size), dtype=np.float64)
    rows = np.arange(size)
    for offset, weight in zip(offsets, weights):
        np.add.at(matrix, (rows, np.clip(rows + offset, 0, size - 1)), weight)
    matrix = matrix.astype(np.float32)
    matrix.setflags(write=False)
    return matrix


def _blur(image: np.ndarray, sigma: float) -> np.ndarray:
    height, width = image.shape[:2]
    data = image.astype(np.float32)
    data = np.matmul(_blur_matrix(height, sigma), data.reshape(height, width * 3)).reshape(height, width, 3)
    swapped = np.ascontiguousarray(data.transpose(1, 0, 2)).reshape(width, height * 3)
    data = np.matmul(_blur_matrix(width, sigma), swapped).reshape(width, height, 3).transpose(1, 0, 2)
    return np.clip(np.rint(data), 0, 255).astype(np.uint8)


def _check_image(image: Any) -> None:
    if not isinstance(image, np.ndarray):
        raise TypeError("image must be a NumPy array")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("image must have shape HxWx3")
    if image.dtype != np.uint8:
        raise TypeError("image dtype must be uint8")


@dataclass(frozen=True)
class ScalarPerturbation:
    """One image family at one severity."""

    kind: str
    severity: float

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in KINDS:
            raise ValueError("kind must be one of {}".format(", ".join(KINDS)))
        object.__setattr__(self, "severity", _validate_severity(self.severity))

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]]) -> Optional["ScalarPerturbation"]:
        """Construct from YAML-compatible data; ``None`` means no perturbation."""

        if value is None:
            return None
        if not isinstance(value, Mapping) or set(value) != {"kind", "severity"}:
            raise ValueError("image_perturbation needs exactly kind and severity")
        return cls(kind=value["kind"], severity=value["severity"])

    def to_mapping(self) -> Dict[str, Any]:
        return {"kind": self.kind, "severity": self.severity}

    @property
    def enabled(self) -> bool:
        return self.severity > 0

    def physical(self) -> Dict[str, Any]:
        return physical_value(self.kind, self.severity)

    def apply(
        self, image: np.ndarray, *, episode_seed: int = 0, step: int = 0, camera: str = "agentview"
    ) -> np.ndarray:
        """Return a transformed copy of an HxWx3 uint8 image.

        ``episode_seed``, ``step`` and ``camera`` only affect the noise family.
        """

        _check_image(image)
        if not self.enabled:
            return np.ascontiguousarray(image.copy())
        s = self.severity
        if self.kind == "darken":
            factor = 1.0 - DARKEN_MAX_REDUCTION * s
            out = np.clip(np.rint(image.astype(np.float64) * factor), 0, 255)
        elif self.kind == "noise":
            seed = stable_seed(episode_seed, step, camera, self.kind, s)
            noise = np.random.default_rng(seed).standard_normal(image.shape) * (NOISE_SIGMA_MAX * s)
            out = np.clip(np.rint(image.astype(np.float64) + noise), 0, 255)
        elif self.kind == "blur":
            return np.ascontiguousarray(_blur(image, BLUR_SIGMA_MAX_PIXELS * s))
        else:
            factor = 1.0 - CONTRAST_MAX_REDUCTION * s
            data = image.astype(np.float64)
            mean = data.mean()
            out = np.clip(np.rint(mean + factor * (data - mean)), 0, 255)
        return np.ascontiguousarray(out.astype(np.uint8))
