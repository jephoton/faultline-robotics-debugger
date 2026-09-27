# ADR 0006: Single-VM parallel replay benchmark

**Status:** Accepted

**Date:** 2026-09-27

## Context

M4 produced a reproducible, reduced robot-policy failure. The next HPC question
is whether concurrent evaluation of independent episodes improves throughput
and cost per valid result. M4's candidate-selection loop is adaptive and cannot
be called parallel merely because individual replays can run concurrently.

## Decision

Compare 1, 2, and 4 evaluator workers on one Nebius GPU VM against one shared
GR00T server. Each mode must consume the same fixed manifest of nominal and
reduced-mask repeats of task 0, episode 0, seed 7. Use separate evaluator
processes and collision-free result paths. Measure warm and end-to-end time,
valid throughput, resource pressure, outcome drift, and estimated cost per
valid episode. No paid run or cap is authorized by this ADR.

## Alternatives

- One model server per worker would isolate inference but duplicate weights and
  introduce GPU-memory contention.
- Multiple VMs would test distributed scale-out but add resource and pricing
  changes before the single-resource bottleneck is understood.

## Consequences

The first M3 claim is limited to confirmation/replay throughput and cost on the
known case. End-to-end adaptive reducer or discovery speedup requires a new
algorithmic experiment. The fixed-repeat workload is a systems benchmark, not
evidence of robustness across new initial states. A separate live-price check
and Jethro-approved run cap precede provisioning.
