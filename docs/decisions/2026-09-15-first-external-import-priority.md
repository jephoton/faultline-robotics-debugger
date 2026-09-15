# First external import priority

Status: accepted direction from Jethro's September 15, 2026 instruction to
prioritize the option that makes the product usable and scalable. Exact schema,
implementation and cloud experiment remain proposed.

Decision: test a LIBERO/robomimic-style HDF5 simulation episode as the first
external artifact to import, conditional on a real sample providing restorable
simulator state and compatible task/runtime assets. Reuse the existing evaluator
and viewer, and present episode inspection, replay readiness and missing
prerequisites before starting diagnosis. Build an episode/capability boundary
that later readers can share; adding another format will not imply equivalent
replay capability.

Alternatives: MCAP has direct evidence of use in deployed robotics, but its logs
usually lack a portable simulator reset. GR00T-compatible LeRobot v2 is closer
to a broad VLA developer dataset workflow, but observations/actions alone do
not guarantee closed-loop replay. Neither should be claimed to deliver the
full confirm/reduce/regression journey without additional prerequisites.

Why this choice: the hackathon demo needs a fresh operator to bring an existing
case and see the complete diagnosis loop. A replay-feasible simulation artifact
is the smallest credible way to demonstrate that experience. Scalability comes
from independent episode indexing and a bounded, format-neutral diagnosis
pipeline, not a claim that every robot log is rerunnable.

Next experiment: inspect a rights-compatible external sample, locate simulator
state/model/task/controller information, restore it with the pinned LIBERO
runtime, and attempt a deterministic one-episode rerun locally or within a
separately approved cloud cap. If restoration fails, record the missing field
and reconsider whether GR00T LeRobot direct inspection should lead instead.

Sources: [robomimic dataset schema](https://robomimic.github.io/docs/datasets/overview.html),
[robomimic playback modes](https://robomimic.github.io/docs/tutorials/dataset_contents.html),
[NVIDIA GR00T LeRobot requirements](https://github.com/NVIDIA/Isaac-GR00T/blob/main/getting_started/data_preparation.md),
[MCAP specification](https://mcap.dev/spec).
