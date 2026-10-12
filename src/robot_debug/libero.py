"""LIBERO adapter that injects replayable diagnostic perturbations."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from vla_eval.benchmarks.libero.benchmark import LIBEROBenchmark

from robot_debug.image_perturbation import ScalarPerturbation, stable_seed
from robot_debug.occlusion import (
    RectOcclusion,
    apply_agentview_occlusion,
    apply_wrist_occlusion,
)

_CAMERAS = ("agentview", "wrist")


class DiagnosticLIBEROBenchmark(LIBEROBenchmark):
    """A pinned LIBERO benchmark with controlled policy-view perturbations.

    Besides the agent-view rectangle, a ``wrist_occlusion`` rectangle and a
    single-strength ``image_perturbation`` family (ADR 0026) can be applied.
    The scalar family hits both cameras first, then any occlusion is drawn.
    Without the new options every observation is exactly what it was before.
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
        **kwargs: Any
    ) -> None:
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
        if self.external_reset is None:
            return super().reset(task)
        return self._reset_from_external_state(task)

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
        if self._scalar_active():
            observation = self._perturb_cameras(observation, step)
        observation = apply_agentview_occlusion(observation, self.agentview_occlusion)
        if self.wrist_occlusion.enabled:
            observation = apply_wrist_occlusion(observation, self.wrist_occlusion)
        return observation

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
