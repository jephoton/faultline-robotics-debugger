"""Scene-level perturbation families: camera viewpoint and lighting (ADR 0032).

Unlike the image families these change the simulated scene, not the pixels the policy gets,
so they are applied to the MuJoCo model after the start state is set and before the
settling steps. Both are described by one normalised severity ``s`` in [0, 1] with ``s = 0``
the exact identity, like :mod:`robot_debug.image_perturbation`:

* ``viewpoint`` moves the agent-view camera sideways along its own right axis by
  ``VIEWPOINT_MAX_SHIFT_M * s`` and turns it about its own up (y) axis by
  ``VIEWPOINT_MAX_YAW_DEG * s``, back toward the scene (against the shift), so the
  table stays in view.
* ``lighting`` scales every light's diffuse and ambient colour (and the headlight's, when
  the model has one) by ``1 - LIGHTING_MAX_REDUCTION * s``.

The bounds are module constants so they can be calibrated on CPU before any paid run. The
rig always writes values computed from the *original* model arrays, never from the current
ones, so applying twice is not cumulative and :meth:`SceneRig.restore` returns the model
exactly, which matters because LIBERO reuses one simulator across episodes.

Pure NumPy and standard library, Python 3.8 compatible.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, Mapping, Optional

import numpy as np

SCENE_KINDS = ("viewpoint", "lighting")
AGENTVIEW_CAMERA = "agentview"

# Calibratable bounds (the values at severity 1).
VIEWPOINT_MAX_SHIFT_M = 0.10
VIEWPOINT_MAX_YAW_DEG = 10.0
LIGHTING_MAX_REDUCTION = 0.9

_PHYSICAL_NAMES = {"viewpoint": "camera_shift_m", "lighting": "light_scale"}


class SceneError(RuntimeError):
    """The scene could not be perturbed as asked; the episode must not run on a half-changed scene."""


def _validate_severity(severity: Any) -> float:
    if isinstance(severity, bool) or not isinstance(severity, (int, float)):
        raise TypeError("severity must be a finite number")
    if not math.isfinite(severity):
        raise ValueError("severity must be finite")
    if not 0 <= severity <= 1:
        raise ValueError("severity must be between 0 and 1")
    return float(severity)


def light_scale(severity: float) -> float:
    return 1.0 - LIGHTING_MAX_REDUCTION * _validate_severity(severity)


def physical_value(kind: str, severity: float) -> Dict[str, Any]:
    """The physical parameter a severity maps to, as ``{"name", "value"}``."""

    if kind not in SCENE_KINDS:
        raise ValueError("unknown scene perturbation kind")
    s = _validate_severity(severity)
    value = VIEWPOINT_MAX_SHIFT_M * s if kind == "viewpoint" else light_scale(s)
    return {"name": _PHYSICAL_NAMES[kind], "value": round(value, 6)}


@dataclass(frozen=True)
class ScenePerturbation:
    """One scene family at one severity."""

    kind: str
    severity: float

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in SCENE_KINDS:
            raise ValueError("kind must be one of {}".format(", ".join(SCENE_KINDS)))
        object.__setattr__(self, "severity", _validate_severity(self.severity))

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]]) -> Optional["ScenePerturbation"]:
        """Construct from YAML-compatible data; ``None`` means no perturbation."""

        if value is None:
            return None
        if not isinstance(value, Mapping) or set(value) != {"kind", "severity"}:
            raise ValueError("scene_perturbation needs exactly kind and severity")
        return cls(kind=value["kind"], severity=value["severity"])

    def to_mapping(self) -> Dict[str, Any]:
        return {"kind": self.kind, "severity": self.severity}

    @property
    def enabled(self) -> bool:
        return self.severity > 0

    def physical(self) -> Dict[str, Any]:
        return physical_value(self.kind, self.severity)


# ---------------------------------------------------------------------------
# Quaternion helpers (MuJoCo order: w, x, y, z)
# ---------------------------------------------------------------------------


def _normalised(quaternion: Any) -> np.ndarray:
    q = np.asarray(quaternion, dtype=np.float64).reshape(4)
    norm = float(np.linalg.norm(q))
    if not norm > 0 or not math.isfinite(norm):
        raise SceneError("the camera orientation is not a valid quaternion")
    return q / norm


def _multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ])


def _right_axis(q: np.ndarray) -> np.ndarray:
    """The camera's own x axis (image right) in the parent frame: the first column of its rotation."""

    w, x, y, z = q
    return np.array([1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)])


def viewpoint_pose(position: Any, quaternion: Any, severity: float) -> Dict[str, Any]:
    """The moved and turned camera pose for a severity, plus the applied shift and yaw.

    The camera moves ``VIEWPOINT_MAX_SHIFT_M * s`` along its own right axis and turns
    ``VIEWPOINT_MAX_YAW_DEG * s`` about its own y (up) axis by post-multiplying a local
    rotation. A positive local yaw swings the viewing direction (the camera's -z) against
    its right axis, that is back toward the scene after the camera moved right.
    """

    s = _validate_severity(severity)
    base_position = np.asarray(position, dtype=np.float64).reshape(3)
    base = _normalised(quaternion)
    shift = VIEWPOINT_MAX_SHIFT_M * s
    yaw_deg = VIEWPOINT_MAX_YAW_DEG * s
    half = math.radians(yaw_deg) / 2.0
    turned = _normalised(_multiply(base, np.array([math.cos(half), 0.0, math.sin(half), 0.0])))
    return {
        "position": base_position + shift * _right_axis(base),
        "quaternion": turned if s > 0 else base,
        "shift_m": shift,
        "yaw_deg": yaw_deg,
    }


# ---------------------------------------------------------------------------
# Applying to a simulator
# ---------------------------------------------------------------------------

_SAVED_ARRAYS = ("cam_pos", "cam_quat", "light_diffuse", "light_ambient")
_HEADLIGHT_FIELDS = ("diffuse", "ambient")


def _headlight(model: Any) -> Any:
    return getattr(getattr(model, "vis", None), "headlight", None)


def _write(target: Any, value: np.ndarray, what: str) -> None:
    """Write into a model array in place and check the write took effect."""

    target[...] = value
    if not np.allclose(np.asarray(target, dtype=np.float64), value, rtol=0.0, atol=1e-12):
        raise SceneError("the simulator did not accept the new {}".format(what))


class SceneRig:
    """Applies a :class:`ScenePerturbation` to a simulator and restores the model afterwards."""

    def __init__(self) -> None:
        self._model = None  # type: Any
        self._saved = {}  # type: Dict[str, np.ndarray]
        self._headlight_saved = {}  # type: Dict[str, np.ndarray]

    # -- bookkeeping ------------------------------------------------------

    def _snapshot(self, model: Any) -> None:
        self._model = model
        self._saved = {}
        for name in _SAVED_ARRAYS:
            array = getattr(model, name, None)
            if array is not None:
                self._saved[name] = np.array(array, dtype=np.float64, copy=True)
        self._headlight_saved = {}
        headlight = _headlight(model)
        if headlight is not None:
            for name in _HEADLIGHT_FIELDS:
                array = getattr(headlight, name, None)
                if array is not None:
                    self._headlight_saved[name] = np.array(array, dtype=np.float64, copy=True)

    def restore(self) -> None:
        """Put every value the rig may have changed back to its original; a no-op before any apply."""

        model = self._model
        if model is None:
            return
        for name, original in self._saved.items():
            target = getattr(model, name, None)
            if target is not None and original.size:
                target[...] = original
        headlight = _headlight(model)
        if headlight is not None:
            for name, original in self._headlight_saved.items():
                target = getattr(headlight, name, None)
                if target is not None:
                    target[...] = original

    # -- application ------------------------------------------------------

    def apply(self, sim: Any, perturbation: ScenePerturbation) -> Dict[str, Any]:
        """Perturb the simulator's model and return a JSON-clean record of what was applied.

        Starts from the original values (capturing them the first time a model is seen), so
        calling it again never compounds. Raises :class:`SceneError` when the scene cannot
        be changed exactly as asked.
        """

        model = sim.model
        if self._model is not model:
            self._snapshot(model)
        else:
            self.restore()
        if perturbation.kind == "viewpoint":
            record = self._apply_viewpoint(model, perturbation)
        else:
            record = self._apply_lighting(model, perturbation)
        forward = getattr(sim, "forward", None)
        if callable(forward):
            forward()  # refresh the derived camera and light poses before anything renders
        return record

    def _camera_id(self, model: Any) -> int:
        try:
            index = int(model.camera_name2id(AGENTVIEW_CAMERA))
        except (AttributeError, KeyError, ValueError, TypeError) as error:
            raise SceneError("the model has no {!r} camera".format(AGENTVIEW_CAMERA)) from error
        if index < 0:
            raise SceneError("the model has no {!r} camera".format(AGENTVIEW_CAMERA))
        return index

    def _apply_viewpoint(self, model: Any, perturbation: ScenePerturbation) -> Dict[str, Any]:
        index = self._camera_id(model)
        if "cam_pos" not in self._saved or "cam_quat" not in self._saved:
            raise SceneError("the model exposes no camera poses")
        pose = viewpoint_pose(self._saved["cam_pos"][index], self._saved["cam_quat"][index], perturbation.severity)
        if perturbation.enabled:
            _write(model.cam_pos[index], pose["position"], "camera position")
            _write(model.cam_quat[index], pose["quaternion"], "camera orientation")
        return {
            "kind": "viewpoint", "severity": perturbation.severity, "camera": AGENTVIEW_CAMERA,
            "shift_m": round(pose["shift_m"], 9), "yaw_deg": round(pose["yaw_deg"], 9),
            "cam_pos": [float(v) for v in pose["position"]],
            "cam_quat": [float(v) for v in pose["quaternion"]],
        }

    def _apply_lighting(self, model: Any, perturbation: ScenePerturbation) -> Dict[str, Any]:
        scale = light_scale(perturbation.severity)
        lights = 0
        if "light_diffuse" in self._saved:
            lights = int(self._saved["light_diffuse"].shape[0])
        headlight_scaled = False
        if perturbation.enabled:
            for name in ("light_diffuse", "light_ambient"):
                original = self._saved.get(name)
                if original is not None and original.size:
                    _write(getattr(model, name), original * scale, name.replace("_", " "))
            headlight = _headlight(model)
            if headlight is not None and self._headlight_saved:
                try:
                    for name, original in self._headlight_saved.items():
                        _write(getattr(headlight, name), original * scale, "headlight " + name)
                    headlight_scaled = True
                except (SceneError, ValueError, TypeError, AttributeError):
                    headlight_scaled = False  # a read-only headlight: recorded as not scaled
                    for name, original in self._headlight_saved.items():
                        try:
                            getattr(headlight, name)[...] = original
                        except (ValueError, TypeError, AttributeError):
                            pass
        return {
            "kind": "lighting", "severity": perturbation.severity, "scale": round(scale, 6),
            "lights": lights, "headlight": headlight_scaled,
        }


__all__ = [
    "AGENTVIEW_CAMERA",
    "LIGHTING_MAX_REDUCTION",
    "SCENE_KINDS",
    "SceneError",
    "ScenePerturbation",
    "SceneRig",
    "VIEWPOINT_MAX_SHIFT_M",
    "VIEWPOINT_MAX_YAW_DEG",
    "light_scale",
    "physical_value",
    "viewpoint_pose",
]
