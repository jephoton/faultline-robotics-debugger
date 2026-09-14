"""Deterministic image-space perturbations for robot policy observations."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class RectOcclusion:
    """An axis-aligned RGB rectangle expressed in normalized image coordinates."""

    enabled: bool = True
    x: float = 0.0
    y: float = 0.0
    width: float = 0.25
    height: float = 0.25
    color: Tuple[int, int, int] = (0, 0, 0)
    opacity: float = 1.0

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("enabled must be a bool")

        coordinates = {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "opacity": self.opacity,
        }
        for name, value in coordinates.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError("{} must be a finite number".format(name))
            if not math.isfinite(value):
                raise ValueError("{} must be finite".format(name))

        if self.x < 0 or self.y < 0:
            raise ValueError("x and y must be non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("rectangle must fit inside normalized image bounds")
        if not 0 <= self.opacity <= 1:
            raise ValueError("opacity must be between 0 and 1")

        if not isinstance(self.color, tuple) or len(self.color) != 3:
            raise TypeError("color must be an RGB tuple")
        for channel in self.color:
            if type(channel) is not int:
                raise TypeError("color channels must be integers")
            if not 0 <= channel <= 255:
                raise ValueError("color channels must be between 0 and 255")

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]]) -> "RectOcclusion":
        """Construct a spec from YAML-compatible data."""

        if value is None:
            return cls(enabled=False)
        data = dict(value)
        if "color" in data:
            data["color"] = tuple(data["color"])
        return cls(**data)

    def apply(self, image: np.ndarray) -> np.ndarray:
        """Return a transformed copy of an HxWx3 uint8 RGB image."""

        if not isinstance(image, np.ndarray):
            raise TypeError("image must be a NumPy array")
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("image must have shape HxWx3")
        if image.dtype != np.uint8:
            raise TypeError("image dtype must be uint8")

        output = np.ascontiguousarray(image.copy())
        if not self.enabled or self.opacity == 0:
            return output

        image_height, image_width = output.shape[:2]
        left = math.floor(self.x * image_width)
        top = math.floor(self.y * image_height)
        right = math.ceil((self.x + self.width) * image_width)
        bottom = math.ceil((self.y + self.height) * image_height)

        region = output[top:bottom, left:right].astype(np.float32)
        color = np.asarray(self.color, dtype=np.float32)
        blended = (1.0 - self.opacity) * region + self.opacity * color
        output[top:bottom, left:right] = np.rint(blended).astype(np.uint8)
        return output


def apply_agentview_occlusion(
    observation: Mapping[str, Any], spec: RectOcclusion
) -> dict:
    """Copy an observation envelope and transform only its agent-view image."""

    transformed = dict(observation)
    images = dict(transformed["images"])
    images["agentview"] = spec.apply(images["agentview"])
    transformed["images"] = images
    return transformed
