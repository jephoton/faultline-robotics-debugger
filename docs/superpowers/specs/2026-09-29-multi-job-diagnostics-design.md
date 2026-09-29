# Multi-job robot failure diagnosis — design

**Status:** Design direction approved by Jethro on 2026-09-29; written spec awaiting review. No implementation or paid run authorized by this document.

## Product question and change in emphasis

A robotics engineer has several tasks to test, not just one mask to minimize. The product accepts a bounded queue of task-level diagnostic jobs, searches for policy failures, confirms repeatability, reduces accepted triggers, and returns a separate replayable report for each job. Its HPC contribution is allocating one GPU's evaluator capacity across *independent jobs* so useful reports arrive sooner and more failures are found within a fixed compute budget. Parallelism inside one job remains an optional optimization, not the product's headline.

The completed M3 1/2/4-worker experiment measured equal-work episode throughput (3.715× warm four-worker speedup), not portfolio diagnostic effectiveness. The locally implemented single-job adaptive loop remains reusable as a job engine, but the proposed US$4/90-minute single-loop comparison is paused and must not be run as the next M3 experiment.

## Scope and alternatives

The first portfolio targets **three distinct tasks within the existing LIBERO Object suite** and the already-tested global agent-view occlusion family. The exact task IDs, baseline validity, and portfolio budget are later explicit experiment decisions. Do not silently change the policy checkpoint, simulator, failure oracle, or perturbation family. M6 adds a separately approved second family and explores other LIBERO suites after checking checkpoint/task compatibility.

Three scheduling approaches are useful:

1. **One job at a time** is the baseline. It is simple and makes the cost of sequential diagnosis visible.
2. **Evenly split workers** is a useful reference when jobs have ready work, but can waste slots while a job waits for a decision or confirmation.
3. **Budget-aware adaptive allocation** is the selected product direction. A work-conserving scheduler chooses among ready episodes across jobs, respects per-job evidence and a shared GPU/time/dollar ceiling, and records why work was selected. It must not equate an apparent failure with a confirmed one or starve all other jobs indefinitely. The exact priority formula and fairness bound require an implementation-plan decision supported by local fixtures; this spec does not claim a mathematically optimal scheduler.

## Architecture and boundaries

```text
portfolio manifest (task jobs, frozen model/evaluator/family/budget)
    → per-job diagnostic controllers (find → confirm → reduce → controls)
    → shared ready-work scheduler (bounded 1/2/4 evaluator slots, one GPU)
    → existing durable attempt ledger and contained evaluator launcher
    → per-job replay bundles + portfolio summary + viewer
```

Each job has a unique immutable identity and its own task/seed/config hash, candidate order, attempt ledger, evidence paths, and terminal state. The scheduler sees only requests already authorized by a job controller; it cannot invent masks, mix outcomes between tasks, alter gate rules, or certify a job. A controller advances only on its own ordered valid results. Missing/invalid/uncertain results remain explicit and fail closed. Shared infrastructure failure may pause the portfolio; it cannot be recast as several policy failures.

The portfolio manifest pins the common policy, checkpoint, simulator image, task suite, perturbation family, failure definition, and budget envelope. Job-specific task IDs and seeds are frozen before either comparison mode. The same manifest is replayed with sequential-job and adaptive-portfolio scheduling. Where a task has a weak nominal baseline or incompatible model behavior, mark it ineligible rather than quietly replace it with an easier task; record the decision and retain the attempted evidence.

## Comparison and product evidence

Use identical frozen jobs and bounds for both modes. Measure time to the first *reproducible reduced report*, number of completed valid reports, reproducible failures found, distinct task coverage, total physical/valid attempts, speculative or abandoned work, GPU utilization where available, and full VM allocation cost per useful report. Show failures and no-failure/budget-exhausted jobs, not just successful diagnoses. Check matched candidate outcomes for drift before making a speed or efficiency claim. Warm throughput, full-session elapsed time, estimated cost, and posted billing remain separate numbers.

The viewer should present a portfolio overview (one row/card per task job, status, spend/time, first apparent/confirmed/reduced result), with drill-down to the existing per-case videos, reduction lineage, and replay recipe. This is a proposed M5 UI change; the current viewer does not yet display a portfolio.

## Safety and rollout

First implement and adversarially test the scheduler locally with fake evaluators: out-of-order completion, conflicting task outcomes, job starvation, interrupted or uncertain attempts, budget exhaustion, and report comparability. Preserve the proven exact-VM watchdog and one execution owner. A real portfolio run needs a new user-approved numeric cap and deadline, fresh balance/price/quota/capacity and model readiness, a disk-retention decision, and a bounded stop-and-copy procedure. Do not treat the prior single-loop proposal or prior M3 spend approval as authorization.

The first live comparison may fail to produce the same failures on every task. That is an experimental result, not a reason to change tasks mid-run. If no task beyond the proven one has a valid nominal baseline, stabilize task selection before benchmarking the scheduler. Cross-suite exploration is explicitly M6, after the within-suite portfolio has a trustworthy comparison.
