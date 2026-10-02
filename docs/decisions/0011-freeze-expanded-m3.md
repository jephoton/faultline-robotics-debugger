# ADR 0011: Freeze expanded M3 as an optional stretch goal

**Status:** Accepted by Jethro on 2026-10-02.

## Context

M3's fixed-work comparison completed 48 valid episodes without outcome drift.
Four evaluators delivered 3.715× warm replay throughput versus one on the same
GPU VM. Expanded multi-task diagnosis is locally implemented, but its live
comparison has not run. Much of the remaining effort is workstation/cloud
lifecycle reliability rather than additional robotics or GPU optimization.
Jethro judged its remaining cost/value insufficient for a core prerequisite.

## Decision

- Retain completed M3 code and evidence as a bounded parallel replay capability.
- Freeze expanded portfolio diagnosis, unfinished persistent host launcher and
  associated portfolio viewer overview as optional stretch work.
- Keep robot failure discovery, repeatability, bounded reduction, inspection
  and replay as the core product. Expanded M3 does not block M5 or submission.
- Preserve unfinished work and artifacts without deletion or merging unreviewed
  host code. Do not resume automatically because an old plan remains approved.
- Jethro may explicitly resume the stretch later. Refresh its defects/review
  status, resource readiness and numeric spending approval first.
- A bounded formal-methods component may be discussed separately; this decision
  does not approve a new verification tool, algorithm or implementation.

## Applying the existing result

The parallel scheduler overlaps independent episode evaluations against a
shared model server; it does not require one GPU per worker. The validated
entry point is `scripts/run_parallel_eval.py` with its frozen replay workload,
not a general arbitrary-job accelerator. Existing evidence supports repeated
nominal/failure replay throughput on the tested setup, not faster adaptive
search/reduction, a GPU-count optimizer, or finalized cloud-billing savings.

The cloud launcher starts, supervises and stops a run. It does not itself make
episodes faster, and its unfinished host extension remains unvalidated.

## Consequences

The product can finish without new HPC claims. Retain the measured result in
technical documentation/demo with its warm-time and fixed-work boundaries.
Only expand or expose general-purpose parallel diagnosis after a separate
approved design and validity check; do not silently enable it in the core loop.
