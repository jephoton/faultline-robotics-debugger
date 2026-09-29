# Adaptive diagnostic loop on one GPU — design

**Status:** Proposed for written-spec review; single-GPU, conservative decision-round direction approved by Jethro on 2026-09-29. No paid run authorized.

**Parent roadmap:** `PROJECT_PLAN.md` M2/M4/M3. **Evidence:** `docs/experiments/m3-parallel.md`, especially the fixed 1/2/4-worker comparison. **Existing safety boundary:** `docs/decisions/0006-single-vm-parallel-replay.md`.

## Goal and claim boundary

Connect the existing first-failure search, repeatability gate, and rectangle reducer to the M3 bounded evaluator so that one diagnostic session can choose 1, 2, or 4 evaluator processes on **one already-approved GPU VM**. Measure the complete time and estimated compute cost from search start to a confirmed, reduced, replayable failure against a one-worker run. Preserve all evidence and report extra speculative attempts, not merely the fastest clock.

M3's 3.715× result applies only to its fixed replay manifest. The adaptive loop may speed up less because decisions create dependencies. This design does not authorize multiple GPUs, VM provisioning, a new perturbation family, a changed failure definition, or a claim of universal optimality.

## Alternatives and selected approach

1. **Conservative decision rounds (selected):** parallelize only tests whose inputs are already fixed. Wait for the round's relevant results before choosing the next reducer rectangle. This keeps the existing edge order and repeatability semantics auditable, at the price of idle workers between rounds.
2. Speculate across future reducer branches: may shorten the critical path, but can spend on obsolete candidates and changes the search algorithm. Defer until the conservative baseline is measured.
3. Add another GPU/VM: could increase capacity, but adds startup, coordination, and cost uncertainty with no measured scale-out curve. Defer behind a separate user decision and cap.

## Components and data flow

The **diagnostic controller** owns the state machine: nominal validity gate; ordered search candidates; exact-condition confirmation; ordered rectangle reduction; fresh nominal controls; terminal report. Reuse the existing scenario/config builders, `classify_aggregate`, `classify_attempts`, and `candidates` rather than redefining success or geometry. Keep the historical M2 and M4 commands runnable and their artifact formats unchanged.

The **round scheduler** accepts an immutable list of episode requests with unique case IDs and returns durable per-case outcomes and artifact paths. It adapts M3's attempt ledger, exact launch identity, process-group/container containment, and fail-closed resume rules. At most the chosen worker count may be active. Results may finish out of order, but controller decisions use the prescribed candidate/attempt order and never treat missing, timed-out, or infrastructure results as a policy success or failure. Uncertain ownership stops the session rather than retrying a possibly live attempt.

The **worker selector** has no authority to provision hardware. Before each round it considers the count of ready independent episodes, the measured one-GPU 1/2/4-worker timing table, remaining episode/wall-clock/dollar limits, and recent valid episode times. It chooses among `1`, `2`, and `4`, capped by ready work and the approved VM's resource envelope. When evidence is too thin or inconsistent, it defaults to one worker. Selection reason and input estimates are persisted. Estimated dollars equal elapsed VM allocation times the verified full-VM rate; worker count is not multiplied by that rate. Estimates must remain separate from posted billing.

The **comparison reporter** reads complete session records. It reports end-to-end wall time (including model startup where observed), warm diagnostic time, physical/valid episode counts, time to first apparent failure, time to first reproducible failure, time and estimated cost to accepted reduced failure, final mask area, outcome drift, and invalid/uncertain attempts. It refuses an apples-to-apples speedup claim if the sequential and adaptive sessions use different task/model/seed/search configuration or failure rules. Different *physical attempt counts* are shown explicitly because scheduling may spend extra attempts.

## Round and budget semantics

- Search may submit already-defined candidates together. A later result cannot supersede an earlier eligible candidate solely because it completed first. Once a candidate is selected, stop scheduling other candidates; safely drain or contain work already launched and record its cost.
- Search confirmation preserves M2's contract of **exactly five valid replay outcomes**, with at least four policy failures required. At most four can launch initially; schedule the fifth after capacity opens. Do not claim reproducibility from only four completed replays. Process results in stable attempt order.
- Reduction preserves current delta and `left, bottom, right, top` candidate order. Its separate M4 gate may pass after four failures or reject after two valid non-failures, with no more than five valid attempts per candidate. Only one candidate rectangle's gate is active at a time. After pass/reject, generate the next round from the committed reducer state. No cross-candidate speculation in this version.
- Nominal sentinel and fresh controls remain mandatory. A parallel session cannot be certified if these gates fail or are invalid.
- Before every launch, enforce approved episode, wall-clock, and estimated-dollar cutoffs; include a reserve for shutdown and evidence copy. A deadline or invalid/uncertain result stops new launches, records partial evidence, and invokes the existing exact-VM lifecycle boundary during a live run. No local controller is itself a substitute for the independent VM stop guard.

## Verification and rollout

1. Pure local tests: stable ordering despite out-of-order completions; worker selection at 0/1/2/4+ ready items, thin data, high queue time, and near-budget limits; gate decisions; no invalid-as-policy classification.
2. Fake-evaluator integration: one-worker and adaptive modes reach the same certified rectangle and nominal-control result, with durable evidence, unique paths, bounded concurrency, interruption/restart uncertainty, and honest extra-work counts. Run adversarial timeout/late-completion cases before any cloud proposal.
3. Offline replay of M3 timings tests selector arithmetic only; it is not an end-to-end performance claim.
4. A later live one-GPU experiment requires fresh balance, capacity, quota, price, disk, VM state, and separately approved cap/deadline. Run the sequential and adaptive modes against the same frozen scenario contract, retain all evidence, stop the VM, and reconcile billing before final cost claims.

## Boundaries and reversibility

The controller and selector are new modules around, not replacements for, the proven M2/M4 drivers or M3 fixed benchmark. A `workers=1` policy provides the sequential baseline and fallback. The selector can be replaced without altering saved episode identities or the reducer's accepted decision rule. Multi-GPU scale-out, new search algorithms, and viewer design are separate future decisions. The viewer may later consume the comparison report but this design does not add UI scope.
