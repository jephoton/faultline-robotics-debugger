"""LIBERO adapter that injects replayable diagnostic perturbations.

Replay guarantee: the policy input is exact. Noise is a pure function of the
configured seed, the episode, the observation step, the camera, the family and the
severity, so replaying a configuration reproduces every policy-input frame.

Recorded video caveat: the recorded agent-view frame is perturbed with its own step
counter (one count per ``_extract_frame`` call), not the policy's. If the harness
calls ``_extract_frame`` and ``make_obs`` at different cadences, the video shows a
different noise realisation than the policy saw (same distribution, different
pixels). Blur, darkening, contrast and occlusion are deterministic functions of the
image, so for them the video always matches. The per-camera probe records statistics
of the real policy input, not of the video.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

from vla_eval.benchmarks.libero.benchmark import LIBEROBenchmark

from robot_debug.image_perturbation import ScalarPerturbation, stable_seed
from robot_debug.occlusion import (
    RectOcclusion,
    apply_agentview_occlusion,
    apply_wrist_occlusion,
)

_CAMERAS = ("agentview", "wrist")
# The camera-effect probe: the first observation after reset and every 40th step up to 280.
PROBE_STEP_INTERVAL = 40
PROBE_LAST_STEP = 280
PROBE_MAX_BYTES = 16 * 1024


class DiagnosticLIBEROBenchmark(LIBEROBenchmark):
    """A pinned LIBERO benchmark with controlled policy-view perturbations.

    Besides the agent-view rectangle, a ``wrist_occlusion`` rectangle and a
    single-strength ``image_perturbation`` family (ADR 0026) can be applied.
    The scalar family hits both cameras first, then any occlusion is drawn.
    Without the new options every observation is exactly what it was before.

    With ``init_state_index`` every episode starts from that benchmark init state
    (the upstream reset otherwise uses the episode index), so a stage can repeat one
    chosen start.

    With ``camera_probe`` (a JSON path) and a wrist occlusion or scalar family
    configured, a small sidecar records, per camera, the mean and standard
    deviation of the policy-input image before and after the perturbation at the
    first observation after reset and every 40th step up to 280. It proves each
    camera was perturbed without storing frames, is rewritten atomically, stays
    under 16 KB and never changes the observation.
    """

    def __init__(
        self,
        agentview_occlusion: Optional[Mapping[str, Any]] = None,
        task_id: Optional[int] = None,
        send_wrist_image: bool = False,
        send_state: bool = False,
        external_reset: Optional[Mapping[str, Any]] = None,
        wrist_occlusion: Optional[Mapping[str, Any]] = None,
        image_perturbation: Optional[Mapping[str, Any]] = None,
        camera_probe: Optional[str] = None,
        init_state_index: Optional[int] = None,
        **kwargs: Any
    ) -> None:
        if camera_probe is not None and (not isinstance(camera_probe, str) or not camera_probe):
            raise ValueError("camera_probe must be a non-empty path")
        if init_state_index is not None and (
            isinstance(init_state_index, bool) or not isinstance(init_state_index, int)
            or init_state_index < 0
        ):
            raise ValueError("init_state_index must be a nonnegative integer")
        if init_state_index is not None and external_reset is not None:
            raise ValueError("init_state_index cannot be combined with external_reset")
        self.init_state_index = init_state_index
        self.camera_probe = camera_probe
        self._probe_episodes: List[Dict[str, Any]] = []
        self._probe_truncated = False
        if external_reset is not None:
            if (not isinstance(external_reset, Mapping)
                    or set(external_reset) != {"candidate", "metadata_out"}
                    or not all(isinstance(external_reset[key], str) and external_reset[key]
                               for key in ("candidate", "metadata_out"))):
                raise ValueError("external_reset needs candidate and metadata_out paths")
            external_reset = {key: external_reset[key] for key in ("candidate", "metadata_out")}
        self.external_reset = external_reset
        # Noise is keyed by (seed, episode, step, camera, kind, severity); the
        # observation and recorded-frame paths count their own steps from reset.
        seed = kwargs.get("seed", 0)
        self._perturbation_seed = seed if type(seed) is int else 0
        self._episode_index = -1
        self._obs_step = 0
        self._frame_step = 0
        self._external_candidate = None
        self._external_resolved = None
        if task_id is not None and (
            isinstance(task_id, bool) or not isinstance(task_id, int) or task_id < 0
        ):
            raise ValueError("task_id must be a nonnegative integer")
        super().__init__(
            send_wrist_image=send_wrist_image,
            send_state=send_state,
            **kwargs
        )
        self.task_id = task_id
        self.agentview_occlusion = RectOcclusion.from_mapping(agentview_occlusion)
        self.wrist_occlusion = RectOcclusion.from_mapping(wrist_occlusion)
        self.image_perturbation = ScalarPerturbation.from_mapping(image_perturbation)

    def get_tasks(self) -> Any:
        tasks = super().get_tasks()
        if self.task_id is None:
            return tasks
        selected = [task for task in tasks if task["task_id"] == self.task_id]
        if len(selected) != 1:
            raise ValueError("task_id {} did not identify exactly one task".format(self.task_id))
        return selected

    def _begin_episode(self) -> None:
        self._episode_index += 1
        self._obs_step = 0
        self._frame_step = 0

    def _scalar_active(self) -> bool:
        return self.image_perturbation is not None and self.image_perturbation.enabled

    def _episode_seed(self) -> int:
        return stable_seed(self._perturbation_seed, max(self._episode_index, 0))

    def perturbation_record(self) -> Optional[dict]:
        """The replay spec of the new options, or ``None`` when none is enabled."""

        if not self._scalar_active() and not self.wrist_occlusion.enabled:
            return None
        record = {"seed": self._perturbation_seed}
        if self._scalar_active():
            record["image_perturbation"] = dict(
                self.image_perturbation.to_mapping(), physical=self.image_perturbation.physical())
        if self.wrist_occlusion.enabled:
            record["wrist_occlusion"] = {
                "x": self.wrist_occlusion.x, "y": self.wrist_occlusion.y,
                "width": self.wrist_occlusion.width, "height": self.wrist_occlusion.height,
                "color": list(self.wrist_occlusion.color), "opacity": self.wrist_occlusion.opacity,
            }
        return record

    def reset(self, task: Any) -> Any:
        self._begin_episode()
        if self.external_reset is not None:
            return self._reset_from_external_state(task)
        if self.init_state_index is not None:
            # The pinned upstream reset starts from ``init_states[task["episode_idx"]]``.
            task = dict(task, episode_idx=self.init_state_index)
        return super().reset(task)

    def _make_env(self, task: Any) -> Any:
        """Create (or reuse) the task environment exactly as the pinned upstream does."""
        from pathlib import Path

        from libero.libero import get_libero_path
        from libero.libero.envs import OffScreenRenderEnv
        from vla_eval.benchmarks.libero import benchmark as upstream

        task_id = task["task_id"]
        if self._env is None or self._current_task_id != task_id:
            if self._env is not None:
                self._env.close()
            task_obj = task["task_obj"]
            bddl_file = Path(get_libero_path("bddl_files")) / task_obj.problem_folder / task_obj.bddl_file
            resolution = getattr(upstream, "LIBERO_ENV_RESOLUTION", 256)
            env = OffScreenRenderEnv(bddl_file_name=str(bddl_file),
                                     camera_heights=resolution, camera_widths=resolution)
            env.seed(self.env_seed)
            self._env = env
            self._current_task_id = task_id
        return self._env

    def _asset_roots(self) -> dict:
        from pathlib import Path

        import robosuite
        from libero.libero import get_libero_path

        return {"libero": Path(get_libero_path("assets")).resolve(),
                "robosuite": (Path(robosuite.__file__).parent / "models" / "assets").resolve()}

    def _reset_from_external_state(self, task: Any) -> Any:
        """Start the episode from the accepted external demo state (ADR 0016).

        The upstream benchmark init state and its wait steps are replaced by the
        reviewed restore kernel, which restores scene XML and state, checks the
        state hash and settles ten steps. Restore hashes are appended to the
        configured sidecar for every episode.
        """
        import json

        from robot_debug.external_reset import (
            ExternalResetError, resolve_external_assets, restore_external_reset,
            validate_external_reset)

        if self._external_candidate is None:
            with open(self.external_reset["candidate"], "r", encoding="utf-8") as handle:
                self._external_candidate = validate_external_reset(json.load(handle))
        candidate = self._external_candidate
        if candidate["task_id"] != task["task_id"]:
            raise ExternalResetError("external reset task does not match the evaluated task")
        env = self._make_env(task)
        if self._external_resolved is None:
            self._external_resolved = resolve_external_assets(candidate["model_xml"], self._asset_roots())
        result = restore_external_reset(env, candidate, self._external_resolved)
        if getattr(self, "absolute_action", False):
            for robot in env.robots:
                robot.controller.use_delta = False
        sidecar = self.external_reset["metadata_out"]
        try:
            with open(sidecar, "r", encoding="utf-8") as handle:
                records = json.load(handle)
        except FileNotFoundError:
            records = []
        metadata = result["reset_metadata"]
        perturbation = self.perturbation_record()
        if perturbation is not None:
            metadata = dict(metadata, perturbation=perturbation)
        records.append(metadata)
        with open(sidecar, "w", encoding="utf-8") as handle:
            json.dump(records, handle, indent=2, sort_keys=True)
        observation = result["observation"]
        self._recorder.record_video(self._extract_frame(observation))
        return observation

    def make_obs(self, raw_obs: Any, task: Any) -> Any:
        observation = super().make_obs(raw_obs, task)
        step = self._obs_step
        self._obs_step += 1
        unperturbed = observation["images"] if self._probe_due(step) else None
        if self._scalar_active():
            observation = self._perturb_cameras(observation, step)
        observation = apply_agentview_occlusion(observation, self.agentview_occlusion)
        if self.wrist_occlusion.enabled:
            observation = apply_wrist_occlusion(observation, self.wrist_occlusion)
        if unperturbed is not None:
            self._record_probe(step, unperturbed, observation["images"])
        return observation

    def _probe_due(self, step: int) -> bool:
        return (
            self.camera_probe is not None
            and (self._scalar_active() or self.wrist_occlusion.enabled)
            and step <= PROBE_LAST_STEP
            and step % PROBE_STEP_INTERVAL == 0
        )

    @staticmethod
    def _image_stats(image: Any) -> Dict[str, float]:
        data = np.asarray(image, dtype=np.float64)
        return {"mean": round(float(data.mean()), 4), "std": round(float(data.std()), 4)}

    def _record_probe(self, step: int, before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
        """Append one sample and rewrite the sidecar; a probe problem never breaks the episode."""

        try:
            sample: Dict[str, Any] = {"step": step}
            for camera in _CAMERAS:
                if camera in before and camera in after:
                    unperturbed = self._image_stats(before[camera])
                    perturbed = self._image_stats(after[camera])
                    sample[camera] = {
                        "unperturbed_mean": unperturbed["mean"], "unperturbed_std": unperturbed["std"],
                        "perturbed_mean": perturbed["mean"], "perturbed_std": perturbed["std"],
                    }
            index = max(self._episode_index, 0)
            if not self._probe_episodes or self._probe_episodes[-1]["episode_index"] != index:
                self._probe_episodes.append({"episode_index": index, "samples": []})
            self._probe_episodes[-1]["samples"].append(sample)
            text = self._probe_text()
            if len(text.encode("utf-8")) > PROBE_MAX_BYTES:
                # Keep the file within its bound: drop what was just added and say so.
                self._probe_episodes[-1]["samples"].pop()
                if not self._probe_episodes[-1]["samples"]:
                    self._probe_episodes.pop()
                self._probe_truncated = True
                text = self._probe_text()
            self._write_probe(text)
        except (OSError, ValueError, TypeError):
            pass

    def _probe_text(self) -> str:
        document: Dict[str, Any] = {
            "schema_version": 1,
            "perturbation": self.perturbation_record(),
            "episodes": self._probe_episodes,
        }
        if self._probe_truncated:
            document["truncated"] = True
        return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def _write_probe(self, text: str) -> None:
        target = self.camera_probe
        directory = os.path.dirname(target)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary = target + ".partial.json"  # an allowed evidence suffix, in case a kill leaves it
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, target)

    def _perturb_cameras(self, observation: Any, step: int) -> dict:
        images = dict(observation["images"])
        for camera in _CAMERAS:
            if camera not in images:
                raise ValueError("observation has no {!r} image to perturb".format(camera))
            images[camera] = self.image_perturbation.apply(
                images[camera], episode_seed=self._episode_seed(), step=step, camera=camera)
        transformed = dict(observation)
        transformed["images"] = images
        return transformed

    def _extract_frame(self, raw_obs: Any) -> Any:
        frame = super()._extract_frame(raw_obs)
        if frame is None:
            return None
        if self._scalar_active():
            frame = self.image_perturbation.apply(
                frame, episode_seed=self._episode_seed(), step=self._frame_step, camera="agentview")
        self._frame_step += 1
        return self.agentview_occlusion.apply(frame)
