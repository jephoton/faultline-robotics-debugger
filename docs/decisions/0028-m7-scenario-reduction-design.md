# ADR 0028: Scenario reduction (mode 1) design

**Status:** Accepted by Jethro on October 13, 2026 (M7 design checkpoint).
Screening scope, spend cap and the remaining M7a items are decided
separately.

## Problem

Mode 1 ("debug a failure you bring", ADR 0027) must turn an imported failing
LIBERO start state into its minimal cause. A LIBERO start state is one flat
MuJoCo state vector (robot joints plus each object's position and rotation,
with velocities), so the question is which parts of it matter for the
failure, measured by rerunning the policy rather than by inspection.

## Decision

**Loop.** Confirm the imported start fails at least 4 of 5 attempts and the
reference start passes; list the differences between them; delta-debug the
set of differences applied on top of the reference (each candidate rerun
under the same 4-of-5 gate) until removing any single remaining difference
makes the task pass; then bisect the size of each remaining difference
towards the reference. Output a replayable case ("the soup rotated N degrees
is enough") with original, minimal and nominal videos.

1. **Demo failure source: screen for a natural failure.** Run GR00T
   unperturbed over benchmark start states (starting with LIBERO-10, where
   the policy is expected to be weakest, which brings suite support forward
   from the breadth pack) and pick a start that fails at least 4 of 5
   attempts. The demo then exports that run in LIBERO format and imports it
   as a user would. If no reproducible natural failure appears, stop and
   return to Jethro; an engineered start is not an automatic fallback.
2. **Granularity: hierarchical.** First whole entities (each object's pose,
   the robot's joint pose), then split surviving entities into position and
   rotation, then shrink sizes. Fewer reruns and readable answers.
3. **Reference: nearest passing benchmark start** of the same task by object
   pose distance, confirmed to pass under the gate. A user-supplied passing
   run can be added later as an optional override.
4. **Nemotron: order, hypotheses and explanation.** Before reduction,
   Nemotron (Token Factory) reads the task and the list of differences,
   ranks the order in which to try them and states a hypothesis; afterwards
   it explains the verified result and the case records whether its
   hypothesis held. Only reruns decide what is in the reduced case; a wrong
   or unavailable Nemotron answer falls back to a fixed order.

**Defaults (amber, accepted with the above):**

- "Reduced" means 1-minimal over differences plus bisection to a stated
  tolerance per remaining difference: a local minimum, not proof of the
  globally smallest cause (the same boundary as M4).
- Mixed start states can be physically invalid (objects interpenetrating).
  Each candidate is settled and checked for penetrating contacts; invalid
  candidates are recorded as `invalid_scene`, never counted as policy
  failures.
- Import generalises the fail-closed external reset kernel (ADR 0016/0021)
  from two pinned demos to validated LIBERO files for any supported suite and
  task, keeping its size, XML and asset checks.

## Rationale

A natural failure is the honest version of the product story ("the policy
really fails here; why?"). Hierarchical differences against the nearest
passing start keep the candidate count small (roughly 10 to 20 candidates of
5 attempts for about 8 entities, one Job of about 10 minutes at the measured
batched throughput). Nemotron's hypothesis makes "model proposes, simulator
verifies" visible and gives it a real role in the loop.

## What would change direction

- The screen finds only flaky failures (below 4 of 5): return to Jethro
  (wider screen, another suite, or an engineered start labelled as such).
- Most candidates are invalid scenes: revisit granularity or interpolation.
- Nemotron's ordering never beats the fixed order: keep it as hypothesis and
  explanation only, and say so.
