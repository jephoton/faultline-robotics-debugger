"""LIBERO adapter that injects replayable diagnostic perturbations."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from vla_eval.benchmarks.libero.benchmark import LIBEROBenchmark

from robot_debug.occlusion import RectOcclusion, apply_agentview_occlusion


class DiagnosticLIBEROBenchmark(LIBEROBenchmark):
    """A pinned LIBERO benchmark with controlled policy-view occlusion."""

    def __init__(
        self,
        agentview_occlusion: Optional[Mapping[str, Any]] = None,
        task_id: Optional[int] = None,
        send_wrist_image: bool = False,
        send_state: bool = False,
        **kwargs: Any
    ) -> None:
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

    def get_tasks(self) -> Any:
        tasks = super().get_tasks()
        if self.task_id is None:
            return tasks
        selected = [task for task in tasks if task["task_id"] == self.task_id]
        if len(selected) != 1:
            raise ValueError("task_id {} did not identify exactly one task".format(self.task_id))
        return selected

    def make_obs(self, raw_obs: Any, task: Any) -> Any:
        observation = super().make_obs(raw_obs, task)
        return apply_agentview_occlusion(observation, self.agentview_occlusion)

    def _extract_frame(self, raw_obs: Any) -> Any:
        frame = super()._extract_frame(raw_obs)
        if frame is None:
            return None
        return self.agentview_occlusion.apply(frame)
