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

Scene families (``scene_perturbation``, ADR 0032) change the simulated scene itself, so
the recorded video shows exactly what the policy saw. They are applied to the MuJoCo
model after the start state is set and before the settling steps, and undone before the
next reset (see :mod:`robot_debug.scene_perturbation`).
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
# The scene-family bounds are re-exported so they can be calibrated from one place.
from robot_debug.scene_perturbation import (  # noqa: F401
    LIGHTING_MAX_REDUCTION,
    SCENE_KINDS,
    VIEWPOINT_MAX_SHIFT_M,
    VIEWPOINT_MAX_YAW_DEG,
    ScenePerturbation,
    SceneRig,
)

_CAMERAS = ("agentview", "wrist")
# The camera-effect probe: the first observation after reset and every 40th step up to 280.
PROBE_STEP_INTERVAL = 40
PROBE_LAST_STEP = 280
PROBE_MAX_BYTES = 16 * 1024
INSTRUCTION_MAX_CHARS = 200


class DiagnosticLIBEROBenchmark(LIBEROBenchmark):
    """A pinned LIBERO benchmark with controlled policy-view perturbations.

    Besides the agent-view rectangle, a ``wrist_occlusion`` rectangle and a
    single-strength ``image_perturbation`` family (ADR 0026) can be applied.
    The scalar family hits both cameras first, then any occlusion is drawn.
    Without the new options every observation is exactly what it was before.

    With ``init_state_index`` every episode starts from that benchmark init state
    (the upstream reset otherwise uses the episode index), so a stage can repeat one
    chosen start.

    With ``scenario_start`` (``{"candidate": path, "metadata_out": path}``) every
    episode starts from one validated scenario state (``scenario_import``): the
    task's environment is reset, the state restored and checked, and then
    settled as upstream does. A start whose bodies of different entities
    interpenetrate by more than 5 mm is ``invalid_scene``: it is not settled,
    the next ``step`` ends the episode at once with ``success`` false and
    ``invalid_scene`` true in the episode metrics, and the sidecar record says
    so, so it is never mistaken for a policy failure. The sidecar also records
    state hashes before and after settling, the deepest penetration and each
    object's settle displacement.

    With ``camera_probe`` (a JSON path) and a wrist occlusion or scalar family
    configured, a small sidecar records, per camera, the mean and standard
    deviation of the policy-input image before and after the perturbation at the
    first observation after reset and every 40th step up to 280. It proves each
    camera was perturbed without storing frames, is rewritten atomically, stays
    under 16 KB and never changes the observation. A scene family adds the values it
    applied to each episode (``scene_applied``) to the same file.

    ``scene_perturbation`` (``{"kind": "viewpoint" | "lighting", "severity": s}``) perturbs
    the scene after the start state and before settling. The benchmark start is then
    replayed step for step as upstream does it (the same replay ``state_out`` uses).

    ``instruction`` replaces the language the policy receives (the observation's
    ``task_description``, which upstream fills from the task name in ``make_obs``);
    ``instruction_out`` (a JSON path) records, per episode, the text the policy receives,
    overridden or not. Without them every observation is exactly what upstream builds.
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
        scenario_start: Optional[Mapping[str, Any]] = None,
        layout_out: Optional[str] = None,
        state_out: Optional[str] = None,
        scene_perturbation: Optional[Mapping[str, Any]] = None,
        instruction: Optional[str] = None,
        instruction_out: Optional[str] = None,
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
        external_reset = self._candidate_paths("external_reset", external_reset)
        scenario_start = self._candidate_paths("scenario_start", scenario_start)
        if scenario_start is not None and (external_reset is not None or init_state_index is not None):
            raise ValueError("scenario_start cannot be combined with external_reset or init_state_index")
        for name, path in (("layout_out", layout_out), ("state_out", state_out)):
            if path is not None and (not isinstance(path, str) or not path):
                raise ValueError("{} must be a non-empty path".format(name))
        if external_reset is not None and (layout_out is not None or state_out is not None):
            raise ValueError("layout_out and state_out are not available with external_reset")
        if scenario_start is not None and state_out is not None:
            raise ValueError("state_out exports benchmark starts; a scenario_start is already a start state")
        self.layout_out = layout_out
        self.state_out = state_out
        self.scene_perturbation = ScenePerturbation.from_mapping(scene_perturbation)
        if self.scene_perturbation is not None:
            if external_reset is not None:
                raise ValueError("scene_perturbation cannot be combined with external_reset")
            wait = kwargs.get("num_steps_wait", 10)
            if self.scene_perturbation.enabled and (isinstance(wait, bool) or not isinstance(wait, int) or wait < 1):
                raise ValueError("scene_perturbation needs at least one settling step to render the new scene")
        self._scene_rig = SceneRig()
        self._scene_applied = []  # type: List[Dict[str, Any]]
        if instruction is not None and (
            not isinstance(instruction, str) or not 1 <= len(instruction) <= INSTRUCTION_MAX_CHARS
            or not instruction.isprintable()
        ):
            raise ValueError("instruction must be 1 to {} printable characters".format(INSTRUCTION_MAX_CHARS))
        if instruction_out is not None and (not isinstance(instruction_out, str) or not instruction_out):
            raise ValueError("instruction_out must be a non-empty path")
        self.instruction = instruction
        self.instruction_out = instruction_out
        self._instruction_records = []  # type: List[Dict[str, Any]]
        self._exported = set()  # type: set
        self.external_reset = external_reset
        self.scenario_start = scenario_start
        self._scenario_candidate = None  # type: Optional[Dict[str, Any]]
        self._scene_cache = {}  # type: Dict[Any, Dict[str, Any]]
        self._invalid_scene = False
        self._invalid_obs = None  # type: Any
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

    @staticmethod
    def _candidate_paths(name: str, value: Optional[Mapping[str, Any]]) -> Optional[Dict[str, str]]:
        """Validate a ``{"candidate", "metadata_out"}`` path pair; ``None`` stays ``None``."""

        if value is None:
            return None
        if (not isinstance(value, Mapping)
                or set(value) != {"candidate", "metadata_out"}
                or not all(isinstance(value[key], str) and value[key] for key in ("candidate", "metadata_out"))):
            raise ValueError("{} needs candidate and metadata_out paths".format(name))
        return {key: value[key] for key in ("candidate", "metadata_out")}

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

    def _scene_active(self) -> bool:
        return self.scene_perturbation is not None and self.scene_perturbation.enabled

    def _episode_seed(self) -> int:
        return stable_seed(self._perturbation_seed, max(self._episode_index, 0))

    def perturbation_record(self) -> Optional[dict]:
        """The replay spec of the new options, or ``None`` when none is enabled."""

        if not self._scalar_active() and not self.wrist_occlusion.enabled and not self._scene_active():
            return None
        record = {"seed": self._perturbation_seed}
        if self._scalar_active():
            record["image_perturbation"] = dict(
                self.image_perturbation.to_mapping(), physical=self.image_perturbation.physical())
        if self._scene_active():
            record["scene_perturbation"] = dict(
                self.scene_perturbation.to_mapping(), physical=self.scene_perturbation.physical())
        if self.wrist_occlusion.enabled:
            record["wrist_occlusion"] = {
                "x": self.wrist_occlusion.x, "y": self.wrist_occlusion.y,
                "width": self.wrist_occlusion.width, "height": self.wrist_occlusion.height,
                "color": list(self.wrist_occlusion.color), "opacity": self.wrist_occlusion.opacity,
            }
        return record

    def reset(self, task: Any) -> Any:
        self._begin_episode()
        self._invalid_scene = False
        self._invalid_obs = None
        if self._scene_active():
            self._scene_rig.restore()  # the simulator is reused across episodes
        self._record_instruction(task)
        if self.scenario_start is not None:
            return self._reset_from_scenario(task)
        if self.external_reset is not None:
            return self._reset_from_external_state(task)
        if self.init_state_index is not None:
            # The pinned upstream reset starts from ``init_states[task["episode_idx"]]``.
            task = dict(task, episode_idx=self.init_state_index)
        if self.state_out is not None or self._scene_active():
            return self._reset_benchmark_start(task)
        observation = super().reset(task)
        if self.layout_out is not None:
            self._export_benchmark_layout(task)
        return observation

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

    def _suite_name(self) -> Optional[str]:
        return getattr(self, "suite", None)

    def _scene_context(self, task: Any, sim: Any, state_length: int) -> Dict[str, Any]:
        """The task's joint layout and body-entity table (built once per task)."""

        from robot_debug import scene_inspect

        key = (self._suite_name(), task["task_id"])
        context = self._scene_cache.get(key)
        if context is None:
            context = {
                "layout": scene_inspect.build_layout(
                    self._suite_name(), task["task_id"], sim.model, state_length),
                "body_entity": scene_inspect.body_entity_table(sim.model),
            }
            self._scene_cache[key] = context
        return context

    @staticmethod
    def _write_json_atomically(target: str, document: Any) -> None:
        directory = os.path.dirname(target)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary = target + ".partial.json"  # an allowed evidence suffix, in case a kill leaves it
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, sort_keys=True, allow_nan=False)
        os.replace(temporary, target)

    def _export_layout(self, task: Any, context: Mapping[str, Any]) -> None:
        """Write ``layout_out`` on the first reset of each task (a later task replaces the file)."""

        key = ("layout", self._suite_name(), task["task_id"])
        if self.layout_out is not None and key not in self._exported:
            self._write_json_atomically(self.layout_out, context["layout"])
            self._exported.add(key)

    def _export_benchmark_layout(self, task: Any) -> None:
        """After an upstream reset: export the task's joint layout."""

        from robot_debug import scene_inspect

        env = self._env
        sim = scene_inspect.sim_of(env)
        length = int(np.asarray(env.get_sim_state()).size)
        self._export_layout(task, self._scene_context(task, sim, length))

    def _reset_benchmark_start(self, task: Any) -> Any:
        """Upstream's reset, replayed step for step so the start can be scanned before it settles.

        The pinned upstream does ``env.reset()``, ``set_init_state(init_states[episode_idx])``,
        ``num_steps_wait`` dummy steps, then (optionally) absolute action mode and the first
        video frame. A benchmark start is never cut short: the contact scan only records
        ``validity`` (and the deepest penetration) beside ``state_out``, so a screen can
        refuse an interpenetrating start without changing any episode.

        Without ``state_out`` the same replay serves a ``scene_perturbation``, which is applied
        after the start state is set and before the dummy steps (so the first observation
        policy sees is already rendered from the perturbed scene).
        """

        from robot_debug import scene_inspect
        from vla_eval.benchmarks.libero import benchmark as upstream

        env = self._make_env(task)
        self._env = env
        self._current_task_id = task["task_id"]
        env.reset()
        sim = scene_inspect.sim_of(env)
        exporting = self.state_out is not None
        context = None
        length = 0
        if exporting or self.layout_out is not None:
            length = int(np.asarray(env.get_sim_state()).size)
            context = self._scene_context(task, sim, length)
            self._export_layout(task, context)
        index = task.get("episode_idx", 0)
        initial = self._task_suite.get_task_init_states(task["task_id"])[index]
        if exporting:
            from robot_debug.scenario_import import (
                ScenarioImportError, candidate_from_benchmark, write_scenario_candidate)

            state = np.asarray(initial, dtype=np.float64).reshape(-1)
            if state.size != length:
                raise ScenarioImportError("benchmark start state length does not match the environment's")
            observation = env.set_init_state(state)
        else:
            observation = env.set_init_state(initial)
        forward = getattr(sim, "forward", None)
        if callable(forward):
            forward()
        key = ("state", self._suite_name(), task["task_id"])
        if exporting and key not in self._exported:
            scan = scene_inspect.scan_contacts(
                sim.model, sim.data, scene_inspect.PENETRATION_LIMIT_M, body_entity=context["body_entity"])
            write_scenario_candidate(
                self.state_out, candidate_from_benchmark(self._suite_name(), task["task_id"], index, state))
            self._write_json_atomically(scene_inspect.validity_companion(self.state_out), {
                "schema_version": 1, "suite": self._suite_name(), "task_id": task["task_id"],
                "init_state_index": index,
                "validity": "valid" if scan["valid"] else "invalid_scene",
                "penetration_limit_m": scene_inspect.PENETRATION_LIMIT_M,
                "deepest_penetration_m": scan["deepest_penetration_m"],
                "deepest_pair": scan["deepest_pair"], "invalid_contacts": scan["invalid_contacts"],
                "deepest_static_penetration_m": scan.get("deepest_static_penetration_m"),
                "deepest_static_pair": scan.get("deepest_static_pair"),
            })
            self._exported.add(key)
        if self._scene_active():
            self._apply_scene(sim)
        dummy_action = getattr(upstream, "LIBERO_DUMMY_ACTION", [0.0] * 6 + [-1.0])
        for _ in range(self.num_steps_wait):
            observation, _reward, _done, _info = env.step(dummy_action)
        if getattr(self, "absolute_action", False):
            for robot in env.robots:
                robot.controller.use_delta = False
        self._recorder.record_video(self._extract_frame(observation))
        return observation

    def _apply_scene(self, sim: Any) -> Dict[str, Any]:
        """Apply the scene family to the model, record what was applied, and return the record."""

        applied = dict(self._scene_rig.apply(sim, self.scene_perturbation),
                       episode_index=max(self._episode_index, 0))
        self._scene_applied.append(applied)
        self._record_scene_probe()
        return applied

    def _record_instruction(self, task: Any) -> None:
        """Append this episode's policy-facing instruction to ``instruction_out`` (atomic JSON)."""

        if self.instruction_out is None:
            return
        used = self.instruction if self.instruction is not None else task.get("name")
        self._instruction_records.append({
            "episode_index": self._episode_index,
            "instruction_used": used,
            "overridden": self.instruction is not None,
        })
        self._write_json_atomically(self.instruction_out, self._instruction_records)

    def _record_scene_probe(self) -> None:
        """Rewrite the camera-probe sidecar with the applied scene values; a probe problem never breaks the episode."""

        if self.camera_probe is None:
            return
        try:
            text = self._probe_text()
            if len(text.encode("utf-8")) > PROBE_MAX_BYTES:
                self._scene_applied.pop()
                self._probe_truncated = True
                text = self._probe_text()
            self._write_probe(text)
        except (OSError, ValueError, TypeError):
            pass

    def _reset_from_scenario(self, task: Any) -> Any:
        """Start the episode from the validated scenario state (ADR 0028).

        Order: reset the task environment as upstream does, restore the state and
        check it restored exactly, check the start for interpenetrating entities,
        and only then settle it. An invalid start is not settled; ``step`` ends the
        episode at once and the sidecar record carries ``validity: invalid_scene``.
        """

        from robot_debug import scene_inspect
        from robot_debug.external_reset import state_sha256
        from robot_debug.scenario_import import (
            ScenarioImportError, ScenarioStartError, check_scenario_target, load_scenario_candidate)

        if self._scenario_candidate is None:
            self._scenario_candidate = load_scenario_candidate(self.scenario_start["candidate"])
        candidate = self._scenario_candidate
        if candidate["suite"] != self._suite_name() or candidate["task_id"] != task["task_id"]:
            raise ScenarioImportError(
                "scenario candidate does not match the evaluated suite, task or state length")
        env = self._make_env(task)
        self._env = env
        self._current_task_id = task["task_id"]
        env.reset()
        sim = scene_inspect.sim_of(env)
        length = int(np.asarray(env.get_sim_state()).size)
        check_scenario_target(
            candidate, suite=self._suite_name(), task_id=task["task_id"], state_length=length)
        context = self._scene_context(task, sim, length)
        self._export_layout(task, context)
        observation = env.set_init_state(np.asarray(candidate["state"], dtype=np.float64))
        forward = getattr(sim, "forward", None)
        if callable(forward):
            forward()  # contacts must belong to the restored state, whatever set_init_state does
        before = scene_inspect.state_vector(env, length)
        before_hash = state_sha256(before.tolist())
        if before_hash != candidate["state_sha256"]:
            raise ScenarioStartError("the simulator did not restore the scenario state exactly")
        scan = scene_inspect.scan_contacts(
            sim.model, sim.data, scene_inspect.PENETRATION_LIMIT_M, body_entity=context["body_entity"])
        record = {
            "schema_version": 1,
            "episode_index": self._episode_index,
            "suite": candidate["suite"],
            "task_id": candidate["task_id"],
            "source": candidate["source"],
            "candidate_state_sha256": candidate["state_sha256"],
            "pre_settle_state_sha256": before_hash,
            "penetration_limit_m": scene_inspect.PENETRATION_LIMIT_M,
            "deepest_penetration_m": scan["deepest_penetration_m"],
            "deepest_pair": scan["deepest_pair"],
            "invalid_contacts": scan["invalid_contacts"],
            "deepest_static_penetration_m": scan.get("deepest_static_penetration_m"),
            "deepest_static_pair": scan.get("deepest_static_pair"),
        }
        if self._scene_active():
            record["scene_applied"] = self._apply_scene(sim)
        if not scan["valid"]:
            self._invalid_scene = True
            self._invalid_obs = observation
            record.update(validity="invalid_scene", post_settle_state_sha256=None, settling_steps=0,
                          settle_displacement_m={})
        else:
            from vla_eval.benchmarks.libero import benchmark as upstream

            dummy_action = getattr(upstream, "LIBERO_DUMMY_ACTION", [0.0] * 6 + [-1.0])
            for _ in range(self.num_steps_wait):
                observation, _reward, _done, _info = env.step(dummy_action)
            if getattr(self, "absolute_action", False):
                for robot in env.robots:
                    robot.controller.use_delta = False
            after = scene_inspect.state_vector(env, length)
            record.update(
                validity="valid",
                post_settle_state_sha256=state_sha256(after.tolist()),
                settling_steps=int(self.num_steps_wait),
                settle_displacement_m=scene_inspect.settle_displacement(context["layout"], before, after))
        perturbation = self.perturbation_record()
        if perturbation is not None:
            record["perturbation"] = perturbation
        self._append_scenario_record(record)
        self._recorder.record_video(self._extract_frame(observation))
        return observation

    def _append_scenario_record(self, record: Dict[str, Any]) -> None:
        target = self.scenario_start["metadata_out"]
        try:
            with open(target, "r", encoding="utf-8") as handle:
                records = json.load(handle)
        except FileNotFoundError:
            records = []
        records.append(record)
        self._write_json_atomically(target, records)

    def step(self, action: Any) -> Any:
        """Upstream step, except that an invalid scenario start ends the episode unscored."""

        if not self._invalid_scene:
            return super().step(action)
        from vla_eval.benchmarks.base import StepResult

        self._recorder.record_step(reward=0.0, done=True, success=False)
        return StepResult(obs=self._invalid_obs, reward=0.0, done=True, info={"invalid_scene": True})

    def get_step_result(self, step_result: Any) -> Any:
        if self._invalid_scene:
            return {"success": False, "invalid_scene": True}
        return super().get_step_result(step_result)

    def make_obs(self, raw_obs: Any, task: Any) -> Any:
        observation = super().make_obs(raw_obs, task)
        if self.instruction is not None:
            observation = dict(observation, task_description=self.instruction)
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
        if self._scene_active():
            document["scene_applied"] = self._scene_applied
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
