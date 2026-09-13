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
        **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.agentview_occlusion = RectOcclusion.from_mapping(agentview_occlusion)

    def make_obs(self, raw_obs: Any, task: Any) -> Any:
        observation = super().make_obs(raw_obs, task)
        return apply_agentview_occlusion(observation, self.agentview_occlusion)

    def _extract_frame(self, raw_obs: Any) -> Any:
        frame = super()._extract_frame(raw_obs)
        if frame is None:
            return None
        return self.agentview_occlusion.apply(frame)
