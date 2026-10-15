"""Single-strength image perturbation families (ADR 0026) with replayable noise.

Each family is described by one normalised severity ``s`` in [0, 1] that maps to
a physical parameter. ``s = 0`` is the exact identity. Everything is pure NumPy
on HxWx3 uint8 RGB images so it runs unchanged in the simulator environment.

Mappings:

* ``darken``   brightness multiplier ``1 - 0.95 s`` (x1.0 down to x0.05)
* ``noise``    additive Gaussian noise, sigma ``100 s`` of 255, clipped to uint8
* ``blur``     Gaussian blur, sigma ``8 s`` pixels (separable, edge-replicated)
* ``contrast`` ``mean + (1 - 0.9 s) (x - mean)`` with the per-image mean
* ``jpeg``     JPEG compression at quality ``95 - 90 s`` (95 down to 5), encoded and
  decoded with a pure-NumPy 8x8 block-DCT codec (see :func:`_jpeg`)
* ``colour_cast`` per-channel gains R ``1 + 0.6 s``, G ``1``, B ``1 - 0.6 s`` (a warm tint)
* ``motion_blur`` horizontal normalised line kernel of ``1 + 30 s`` pixels
* ``dead_pixels`` a fraction ``0.2 s`` of the pixels pinned to black or white

Noise and dead pixels are deterministic functions of (episode seed, step index, camera,
kind, severity) through a stable SHA-256 hash, never Python's salted ``hash()``, so a
replay reproduces every frame exactly (for a fixed NumPy build).

The key deliberately has **no attempt index** (coordinator decision, October 13):
the perturbation is a fixed, replayable function of the episode, so every attempt
at one level sees the identical noise. Variation between attempts comes only from
the policy and the simulator, which is what the 4-of-5 reproducibility gate measures.
"""

from __future__ import annotations

from dataclasses import dataclass
import functools
import hashlib
import math
from typing import Any, Dict, Mapping, Optional

import numpy as np

from robot_debug import scene_perturbation

KINDS = ("darken", "noise", "blur", "contrast", "jpeg", "colour_cast", "motion_blur", "dead_pixels")

DARKEN_MAX_REDUCTION = 0.95
NOISE_SIGMA_MAX = 100.0
BLUR_SIGMA_MAX_PIXELS = 8.0
CONTRAST_MAX_REDUCTION = 0.9
JPEG_QUALITY_MAX = 95.0
JPEG_QUALITY_SPAN = 90.0  # quality falls from 95 at s = 0 to 5 at s = 1
COLOUR_CAST_GAIN = 0.6  # red x(1 + 0.6 s), blue x(1 - 0.6 s)
MOTION_BLUR_EXTRA_PIXELS = 30.0  # kernel length 1 + 30 s pixels
DEAD_PIXEL_FRACTION_MAX = 0.2

_PHYSICAL_NAMES = {
    "darken": "brightness_factor",
    "noise": "noise_sigma",
    "blur": "blur_sigma_px",
    "contrast": "contrast_factor",
    "jpeg": "jpeg_quality",
    "colour_cast": "red_gain",
    "motion_blur": "motion_kernel_px",
    "dead_pixels": "dead_pixel_fraction",
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
    """The physical parameter a severity maps to, as ``{"name", "value"}``.

    Scene families (viewpoint, lighting) are answered by :mod:`robot_debug.scene_perturbation`, so the
    threshold search and the reports can ask one function about any audit family.
    """

    if kind in scene_perturbation.SCENE_KINDS:
        return scene_perturbation.physical_value(kind, severity)
    if kind not in KINDS:
        raise ValueError("unknown perturbation kind")
    s = _validate_severity(severity)
    value = {
        "darken": 1.0 - DARKEN_MAX_REDUCTION * s,
        "noise": NOISE_SIGMA_MAX * s,
        "blur": BLUR_SIGMA_MAX_PIXELS * s,
        "contrast": 1.0 - CONTRAST_MAX_REDUCTION * s,
        "jpeg": JPEG_QUALITY_MAX - JPEG_QUALITY_SPAN * s,
        "colour_cast": 1.0 + COLOUR_CAST_GAIN * s,
        "motion_blur": 1.0 + MOTION_BLUR_EXTRA_PIXELS * s,
        "dead_pixels": DEAD_PIXEL_FRACTION_MAX * s,
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


# The standard JPEG (Annex K) quantisation tables, which libjpeg scales by quality.
_LUMINANCE_TABLE = np.array(
    [
        [16, 11, 10, 16, 24, 40, 51, 61],
        [12, 12, 14, 19, 26, 58, 60, 55],
        [14, 13, 16, 24, 40, 57, 69, 56],
        [14, 17, 22, 29, 51, 87, 80, 62],
        [18, 22, 37, 56, 68, 109, 103, 77],
        [24, 35, 55, 64, 81, 104, 113, 92],
        [49, 64, 78, 87, 103, 121, 120, 101],
        [72, 92, 95, 98, 112, 100, 103, 99],
    ],
    dtype=np.float64,
)
_CHROMINANCE_TABLE = np.full((8, 8), 99.0)
_CHROMINANCE_TABLE[:4, :4] = np.array(
    [[17, 18, 24, 47], [18, 21, 26, 66], [24, 26, 56, 99], [47, 66, 99, 99]], dtype=np.float64
)


def _quantisation_table(base: np.ndarray, quality: float) -> np.ndarray:
    """libjpeg's quality scaling of a base table (quality 50 is the table itself)."""

    quality = min(max(float(quality), 1.0), 100.0)
    scale = 5000.0 / quality if quality < 50.0 else 200.0 - 2.0 * quality
    return np.clip(np.floor((base * scale + 50.0) / 100.0), 1.0, 255.0)


@functools.lru_cache(maxsize=1)
def _dct_matrix() -> np.ndarray:
    """The orthonormal 8-point DCT-II basis (rows are frequencies)."""

    frequency = np.arange(8)[:, None]
    position = np.arange(8)[None, :]
    matrix = np.cos((2 * position + 1) * frequency * math.pi / 16.0) * math.sqrt(2.0 / 8.0)
    matrix[0] = math.sqrt(1.0 / 8.0)
    matrix.setflags(write=False)
    return matrix


@functools.lru_cache(maxsize=1)
def _dct_matrix_2d() -> np.ndarray:
    """The 64x64 operator of the separable 2-D DCT on a row-major flattened 8x8 block."""

    matrix = np.kron(_dct_matrix(), _dct_matrix())
    matrix.setflags(write=False)
    return matrix


def _pillow_jpeg(image: np.ndarray, quality: float) -> Optional[np.ndarray]:
    """A libjpeg round trip (4:4:4) through Pillow, or ``None`` when Pillow is unavailable.

    The LIBERO simulator image ships Pillow 10.4 (about 2.4 ms per 256x256 frame), whereas the
    pure-NumPy fallback below took about 33 ms per frame there (October 15), which would have
    roughly doubled an episode's wall time with three compressed frames per step.
    """

    try:
        import io
        from PIL import Image
    except ImportError:
        return None
    buffer = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(image, dtype=np.uint8)).save(
        buffer, format="JPEG", quality=int(round(quality)), subsampling=0, optimize=False)
    return np.asarray(Image.open(io.BytesIO(buffer.getvalue())).convert("RGB"), dtype=np.uint8)


def _jpeg(image: np.ndarray, quality: float) -> np.ndarray:
    """Round-trip an image through baseline-JPEG-style compression, deterministically.

    The LIBERO simulator image has no encoder that is certain to be present, so this is
    pure NumPy: full-range YCbCr, no chroma subsampling, 8x8 block DCT, the standard
    luminance/chrominance tables scaled by ``quality`` as libjpeg does, rounding, then the
    inverse. It matches a libjpeg round trip (4:4:4) to within about one grey level on
    average; it skips only the entropy coding, which is lossless.
    """

    height, width = image.shape[:2]
    pad_h, pad_w = (-height) % 8, (-width) % 8
    data = image.astype(np.float64)
    if pad_h or pad_w:
        data = np.pad(data, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
    red, green, blue = data[..., 0], data[..., 1], data[..., 2]
    luma = 0.299 * red + 0.587 * green + 0.114 * blue
    cb = -0.168736 * red - 0.331264 * green + 0.5 * blue
    cr = 0.5 * red - 0.418688 * green - 0.081312 * blue
    planes = np.stack([luma - 128.0, cb, cr], axis=0)  # level-shifted, (3, H, W)
    rows, cols = planes.shape[1] // 8, planes.shape[2] // 8
    blocks = planes.reshape(3, rows, 8, cols, 8).transpose(0, 1, 3, 2, 4)  # (3, rows, cols, 8, 8)
    transform = _dct_matrix_2d()
    coefficients = np.matmul(blocks.reshape(3, rows * cols, 64), transform.T)  # (3, blocks, 64)
    chroma = _quantisation_table(_CHROMINANCE_TABLE, quality).reshape(64)
    tables = np.stack([_quantisation_table(_LUMINANCE_TABLE, quality).reshape(64), chroma, chroma])[:, None, :]
    coefficients = np.rint(coefficients / tables) * tables
    restored = np.matmul(coefficients, transform)  # the orthonormal transform's inverse is its transpose
    planes = restored.reshape(3, rows, cols, 8, 8).transpose(0, 1, 3, 2, 4).reshape(3, rows * 8, cols * 8)
    luma, cb, cr = planes[0] + 128.0, planes[1], planes[2]
    out = np.stack([luma + 1.402 * cr, luma - 0.344136 * cb - 0.714136 * cr, luma + 1.772 * cb], axis=-1)
    return np.clip(np.rint(out[:height, :width]), 0, 255).astype(np.uint8)


@functools.lru_cache(maxsize=64)
def _line_matrix(size: int, length: float) -> np.ndarray:
    """A (size x size) operator averaging ``length`` pixels in a line, edge-replicated.

    Tap ``k`` weighs the overlap of the box ``[-length/2, length/2]`` with pixel ``k``, so the
    kernel varies continuously with ``length`` and a length of 1 is the identity.
    """

    radius = max(0, int(math.ceil(length / 2.0)))
    offsets = np.arange(-radius, radius + 1)
    weights = np.clip(length / 2.0 - np.abs(offsets) + 0.5, 0.0, 1.0)
    weights /= weights.sum()
    matrix = np.zeros((size, size), dtype=np.float64)
    rows = np.arange(size)
    for offset, weight in zip(offsets, weights):
        if weight > 0:
            np.add.at(matrix, (rows, np.clip(rows + offset, 0, size - 1)), weight)
    matrix = matrix.astype(np.float32)
    matrix.setflags(write=False)
    return matrix


def _motion_blur(image: np.ndarray, length: float) -> np.ndarray:
    width = image.shape[1]
    data = np.tensordot(_line_matrix(width, round(length, 6)), image.astype(np.float32), axes=([1], [1]))
    return np.clip(np.rint(data.transpose(1, 0, 2)), 0, 255).astype(np.uint8)


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

    def _dead_pixels(self, image: np.ndarray, seed: int) -> np.ndarray:
        """Pin exactly ``round(0.2 s H W)`` pixels (all three channels) to 0 or 255."""

        height, width = image.shape[:2]
        count = int(round(DEAD_PIXEL_FRACTION_MAX * self.severity * height * width))
        out = image.copy().reshape(height * width, 3)
        if count:
            rng = np.random.default_rng(seed)
            chosen = rng.choice(height * width, size=count, replace=False)
            out[chosen] = (rng.integers(0, 2, size=count) * 255).astype(np.uint8)[:, None]
        return np.ascontiguousarray(out.reshape(height, width, 3))

    def apply(
        self, image: np.ndarray, *, episode_seed: int = 0, step: int = 0, camera: str = "agentview"
    ) -> np.ndarray:
        """Return a transformed copy of an HxWx3 uint8 image.

        ``episode_seed``, ``step`` and ``camera`` only affect the noise and dead-pixel families.
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
        elif self.kind == "jpeg":
            quality = JPEG_QUALITY_MAX - JPEG_QUALITY_SPAN * s
            encoded = _pillow_jpeg(image, quality)
            return np.ascontiguousarray(encoded if encoded is not None else _jpeg(image, quality))
        elif self.kind == "colour_cast":
            gains = np.array([1.0 + COLOUR_CAST_GAIN * s, 1.0, 1.0 - COLOUR_CAST_GAIN * s])
            out = np.clip(np.rint(image.astype(np.float64) * gains), 0, 255)
        elif self.kind == "motion_blur":
            return np.ascontiguousarray(_motion_blur(image, 1.0 + MOTION_BLUR_EXTRA_PIXELS * s))
        elif self.kind == "dead_pixels":
            return self._dead_pixels(image, stable_seed(episode_seed, step, camera, self.kind, s))
        else:
            factor = 1.0 - CONTRAST_MAX_REDUCTION * s
            data = image.astype(np.float64)
            mean = data.mean()
            out = np.clip(np.rint(mean + factor * (data - mean)), 0, 255)
        return np.ascontiguousarray(out.astype(np.uint8))
