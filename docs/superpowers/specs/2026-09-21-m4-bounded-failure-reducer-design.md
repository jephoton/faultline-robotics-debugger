# M4 Bounded Failure Reducer Design

**Status:** Accepted direction; detailed execution awaits plan review  
**Date:** 2026-09-21  
**Parent roadmap:** `PROJECT_PLAN.md`, M4

## Outcome

M4 turns the proven upper-right 25%-area occlusion failure into a smaller,
replayable counterexample under an explicit episode budget. The reducer will
not claim a globally minimal mask or causal explanation. It will report the
smallest nested rectangle it actually tested and certified under the accepted
repeatability rule.

The fixed experiment contract remains:

- GR00T N1.7 LIBERO Object checkpoint;
- task 0, episode 0, seed and environment seed 7;
- opaque black rectangle on `agentview` only;
- `policy_failure` as the failure category;
- nominal controls must remain successful;
- infrastructure and invalid-evidence outcomes never count as policy results.

## Alternatives considered

1. **Binary-search square size.** Cheapest and simplest, but it assumes a
   monotonic threshold and cannot identify which part of the upper-right mask
   matters. The position results already warn against that assumption.
2. **Exhaustive rectangle grid.** Maps the region more fully, but spends most
   of M4's budget on coverage rather than producing one reduced regression.
3. **Bounded greedy edge stripping — recommended.** Remove one strip from one
   edge at a time, certify each accepted move, and stop at a hard attempt
   budget. This gives an interpretable reduction path and naturally becomes
   useful work for the later M3 parallelism comparison.

## Reducer contract

The starting rectangle is `(x=0.50, y=0.00, width=0.50, height=0.50)` in
normalized image coordinates with a top-left origin. Every candidate must be a
strict subset of the current rectangle and remain within `[0, 1]`.

At each state, generate candidates by removing one strip from an edge:

- left: increase `x` and decrease `width`;
- bottom: decrease `height`;
- right: decrease `width`;
- top: increase `y` and decrease `height`.

Use deterministic edge order `left, bottom, right, top`. This first tests
whether the failure is retained by the image-corner portion of the known mask;
the order is an engineering heuristic, not a claim about visual causality.
Try coarse `0.125` strips before fine `0.0625` strips. When a candidate passes,
it becomes the new current rectangle and candidate generation restarts at the
same granularity. If no edge passes, move to the finer granularity. The result
is a local minimum relative to tested moves and budget, not a global minimum.

## Repeatability and stopping

A candidate is evaluated sequentially against the same initial state:

- pass as soon as four `policy_failure` outcomes are observed;
- reject as soon as two non-failure policy outcomes are observed;
- use no more than five valid attempts;
- abort the session on infrastructure or invalid evidence rather than treating
  either as a rejection.

This is the existing four-of-five engineering screen with safe early stopping.
A nominal sentinel runs first. The known parent rectangle is revalidated under
the same gate to catch runtime drift.

The first paid reducer session has a proposed maximum of 23 valid episodes:

- 1 nominal sentinel;
- up to 5 parent-validation attempts;
- 12 candidate-evaluation attempts shared across all candidates;
- 5 matched nominal controls after at least one reduction is accepted.

If the candidate budget ends during a gate, record the candidate as
`inconclusive_budget_exhausted`; do not accept it. A wall-clock launch cutoff is
also mandatory. The plan does not authorize this spend: live price, remaining
credit, resource state, and a fresh dollar cap must be checked with Jethro
before provisioning or resuming compute.

Fresh initial states are deliberately outside this M4 session. M4 minimizes the
known exact counterexample. Generalization to fresh states belongs to M6 and
must not be inferred from this evidence.

## Components and data flow

`src/robot_debug/reduce.py` is a pure deterministic kernel. It owns rectangle
validation, candidate generation, and the adaptive four-of-five decision. It
does not launch subprocesses or read artifacts.

`scripts/run_failure_search.py` gains backward-compatible rectangular config
support. Existing square callers keep using `side`; the reducer supplies
`width` and `height`. Mixing the two forms is rejected.

`scripts/run_failure_reduction.py` owns the session state machine. It reuses
the established evaluator launcher and evidence validation, writes the session
summary atomically after every attempt, and can resume without rerunning a
completed stage. It emits enough lineage for the existing viewer to show the
parent and reduced attempts immediately.

The summary and replay manifest record:

- parent and candidate geometries and normalized areas;
- ordered candidate decisions and every attempt outcome;
- accepted-reduction lineage;
- episode and wall-clock budgets consumed;
- stop reason and final certified rectangle;
- model, task, seed, repository revision, config paths, and replay command;
- nominal sentinel/control outcomes.

## Model and agent routing

The stronger OpenAI coordinator retains architecture, red decisions, Git
integration, independent review, evidence interpretation, and all Nebius
lifecycle/spending authority.

- **DeepSeek Flash:** suitable only for the pure reducer kernel and its unit
  tests. This is bounded, deterministic, and isolated from credentials and
  external systems. It requires Jethro's explicit execution authorization, a
  dedicated worktree, and a task handoff document satisfying `AGENTS.md`.
- **Terra:** owns the integration-heavy rectangular config contract and reducer
  session driver. These tasks require understanding the existing harness and
  artifact semantics but are bounded by this design.
- **Luna:** owns mechanical, interface-stable work after the schema is frozen:
  viewer presentation of reduction lineage, usage documentation, and focused
  regression checks. Luna does not choose the algorithm, evidence gate, or
  cloud budget.

No two workers may edit the same files concurrently. The OpenAI coordinator is
the only integration owner and the only actor allowed to run the paid session.

## Acceptance criteria

1. Pure tests prove candidate nesting, bounds, deterministic order, coarse-to-
   fine progression, early pass/reject, and budget exhaustion.
2. Existing centered-square and position-grid tests remain unchanged in
   behavior after rectangle support is added.
3. A fake evaluator integration test proves resumable persistence, parent
   validation, candidate acceptance/rejection, infrastructure aborts, and the
   23-episode ceiling without cloud access.
4. A dry run produces a viewer-readable catalog with explicit parent/reduced
   lineage and a replay manifest.
5. A later approved Nebius run either produces a smaller certified rectangle
   with passing nominal controls or an honest bounded result explaining why no
   smaller case was certified.

## Claim boundary

Successful M4 evidence supports: “Within this tested nested-rectangle search
and retry budget, the system reduced a reproducible failure to this smaller
replayable condition.” It does not support universal failure coverage, causal
localization, global minimality, or robustness across tasks and initial states.
