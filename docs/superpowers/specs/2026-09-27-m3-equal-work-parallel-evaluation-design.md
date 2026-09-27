# M3 Equal-Work Parallel Evaluation Design

**Status:** Proposed for Jethro's design review; no worker topology or cloud spending authorized

**Date:** 2026-09-27

**Parent roadmap:** `PROJECT_PLAN.md`, M3

**Evidence input:** `docs/experiments/m4-reducer.md`

## Outcome and claim boundary

Measure whether concurrent simulation/evaluation workers reduce the time and
cloud cost required to **confirm and replay** the actual M4 robot-policy
failure. M3 compares 1, 2, and 4 workers on identical finite work, preserves
the existing success/failure contract, and exposes the bottleneck. Its first
result will be a throughput and cost result for independent episodes, not a
claim that the sequential, adaptive mask reducer or arbitrary failure search
has been accelerated end to end.

M4's candidate choice depends on prior outcomes. Parallelizing that decision
loop requires a new search/scheduling algorithm and a separate design decision.
This distinction should be prominent in the README, viewer, and demo claims.

## Decision for review: where workers run

| Approach | What it teaches | Main drawback |
| --- | --- | --- |
| **A. One Nebius GPU VM, one shared GR00T server, 1/2/4 evaluator processes — recommended** | Whether simulation and server-request concurrency help on the same paid resource; queueing, CPU/GPU saturation, and cost per episode | Shared inference may bottleneck; four simulators may exhaust RAM/CPU/GPU memory |
| B. One VM, separate model server per evaluator | Model-server isolation and GPU contention | Repeats model weights, likely memory pressure, confounds simple worker scaling |
| C. Multiple VMs, one evaluator/server per VM | Distributed scheduling and true scale-out | Different cost topology, provisioning overhead, and a larger spend; premature for the first controlled result |

Recommend A for the first M3 comparison. It keeps the hourly resource price
roughly fixed while changing evaluator concurrency, so a speedup can reduce
cost per completed valid episode. Confirm a live single-GPU shape, quota, price,
and available credit before any paid run; the existing US$75 project ceiling is
not a run authorization. One cloud execution owner provisions and tears down
the VM. A later multi-VM extension is optional, not part of the M3 acceptance
gate.

## Workload and fairness contract

Use a versioned, fixed manifest derived from M4: matched nominal and
upper-right reduced-mask episodes at the same task, initial state, seed,
checkpoint, image geometry, horizon, and inference settings. The first benchmark
should repeat the *known* episode enough times for all worker counts to have
work. It must not silently substitute new episode indices or claim
generalization to new initial states. Choose an exact count after an offline
manifest dry-run and a price-based cap calculation, not by trial-and-error on a
live VM.

Each 1/2/4-worker mode consumes the **same multiset** of case identities and
repeat IDs. Stable assignment should make every run auditable; each item has
one owner, one durable result, and a unique artifact directory. A failed or
timed-out item remains visible and is never counted as a valid episode. Record
both total attempts and completed valid episodes. Keep recordings necessary for
the viewer, but avoid unnecessary duplicate large media if the approved
measurement contract permits a small representative video set; never claim an
unrecorded item is visually replayable.

The pinned AllenAI harness revision builds a task/episode work list and has
fixed-seed shard assignment, per-shard output stems, and progress files. Its
native sharding only creates parallel work if the configured work list contains
multiple items. The current M4 case is one task and one episode index, so the
implementation plan must verify whether native sharding can represent distinct
**repeats of that exact case** without changing initial states. If not, use a
small project-owned manifest scheduler around the existing one-episode runner;
do not mislabel distinct episode indices as repeats. Do not assume the current
upstream CLI matches the pinned revision.

Before comparing performance, run a no-cloud local test with a stub evaluator:
prove equal manifests, collision-free outputs, bounded concurrency, resumption
without duplicate completions, and correct handling of invalid/infrastructure
outcomes. A one-worker live pilot should verify GR00T request isolation and
baseline timing before the bounded 2/4-worker comparison.

## Measurements and validity

For each mode report:

- completed valid episodes per wall-clock hour;
- wall time for identical work, speedup versus 1 worker, and parallel efficiency;
- estimated Nebius compute cost per valid episode, with the pricing assumptions;
- startup/model-download time separately from warm evaluation time;
- per-episode simulation, rendering, inference/request, queue, and recording
  durations where observable;
- peak GPU memory, GPU utilization, CPU/RAM pressure, and failed/invalid counts;
- outcome counts for nominal and reduced-mask cases, plus any drift across modes.

Keep synchronous/fixed-step semantics. Each evaluator must isolate environment,
policy conversation, and buffered action state. If outcome drift appears,
investigate it before interpreting speedup as equivalent work. Report raw
attempts and an honest uncertainty statement; identical seed repeats are a
systems benchmark, not independent evidence across diverse scenes.

Use two clocks: end-to-end session time, including startup and teardown, and
warm benchmark time. A single shared VM means estimated compute cost is elapsed
billable VM time times the live full-resource rate, not worker count times an
imagined per-worker price. Include storage/network charges if material. A
throughput increase is useful only if valid evidence and outcome semantics are
preserved.

## Safety, product, and stopping

- No new cloud run, spend cap, GPU shape, or additional perturbation family is
  approved by this design document. Present a calculated dollar cap and get
  Jethro's approval before provisioning.
- Stop launching new episodes on the approved wall-clock or dollar cutoff,
  repeated infrastructure errors, invalid evidence, model-server instability,
  or resource exhaustion. Keep partial data labeled partial; tear down the VM.
- Save the fixed manifest, config hashes, assignment map, per-worker logs,
  valid/invalid outcomes, timing/telemetry, and replay/video references so the
  viewer can show the benchmark and judges can inspect its provenance.
- The judge-facing claim is conditional: if the same work gets faster and
  cheaper without outcome drift, M3 supports efficient confirmation/replay. If
  it does not, the measured bottleneck is still a valid result and guides the
  next improvement. Neither outcome proves efficient *discovery* yet.

## Acceptance and next decision

M3 is complete when a fixed manifest has been executed with 1/2/4 workers
under an explicitly approved cap; all attempts and resource costs are
reconciled; comparable outcome semantics are checked; the viewer or a linked
report exposes the evidence; and the README states the measured speedup,
cost/episode, bottleneck, and limitations without overstating generality.

**Review question:** Approve approach A and this fixed-repeat M4 replay workload
for M3? If accepted, write a bite-sized implementation plan, verify the pinned
harness's actual CLI/repeat support, calculate a live-session cap, and return
for the separate spending decision. If the priority is end-to-end adaptive
reducer acceleration instead, revise the design first because that changes the
algorithm and result being measured.
