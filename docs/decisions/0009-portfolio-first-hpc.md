# ADR 0009: Portfolio-first HPC for diagnostics

**Status:** Accepted direction on 2026-09-29; scheduler details and live experiment pending.

## Context

The fixed-work M3 comparison proved that four concurrent evaluators increased warm episode throughput on one GPU. A single find → confirm → reduce loop contains sequential decision gates, so that throughput result is not evidence of proportional end-to-end diagnosis speedup. Jethro wants HPC to serve multiple robot-task investigations rather than be forced into one dependent loop.

## Decision

Make independent task-level diagnostic jobs the primary unit of portfolio scheduling. Target three tasks inside the existing LIBERO Object suite and the proven occlusion family. Compare sequential processing of the same jobs against a bounded, budget-aware shared-worker scheduler. Preserve each job's independent evidence and replay report. Reserve a second perturbation family and exploration of other LIBERO suites for M6.

The existing single-job adaptive loop remains available as a per-job component. Its proposed paid sequential/adaptive comparison is paused; no cloud expenditure is authorized by this ADR.

## Alternatives and rationale

- Accelerate only one diagnosis: simpler integration but decision dependencies limit parallel work and make HPC less central to the product.
- Even worker partition across jobs: easy to explain but may leave capacity idle at job gates.
- Shared adaptive allocation: best matches a real diagnostic queue and fixed-budget objective; must be compared with one-at-a-time and report any scheduling overhead, extra attempts, and fairness limitations.

## Revisit when

Within-suite task baselines are invalid, shared scheduling changes outcomes, the scheduler starves jobs, or budget-matched evidence does not improve useful reports or time to report. Multi-GPU scale-out is a separate decision.
