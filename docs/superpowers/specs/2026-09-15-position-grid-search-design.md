# Fixed-Area Position-Grid Search Design

**Status:** accepted from Jethro's September 15 approval of the recommended
position search; exact ordering and matched-control gates are bounded amber
details selected after independent code and experiment-validity review.

## Question

At a constant 25% image area, does moving the accepted opaque black occlusion
to a different part of the policy's agent-view image produce a repeatable task
failure for the same GR00T/LIBERO initial state?

This is the next M2 search increment. It is not failure reduction, adaptive
search, parallel scaling, or a new perturbation family.

## Frozen experiment identity

- GR00T and LIBERO checkpoint revisions remain exactly those recorded in
  `docs/experiments/first-failure-search.md`.
- Use LIBERO Object task 0, episode 0, `seed=7`, and `env_seed=7`.
- Change only `agentview`; wrist view, state, physics, instruction, and success
  predicate remain unchanged.
- Use an opaque black square with width and height `0.50`.
- Interpret `x` and `y` as normalized image-array top-left coordinates.

## Preregistered sequence

Run one unoccluded episode-0 sentinel, then search these previously untested
positions in order:

| Order | Stage | `x` | `y` |
| ---: | --- | ---: | ---: |
| 1 | `grid-x000-y050` | 0.00 | 0.50 |
| 2 | `grid-x050-y050` | 0.50 | 0.50 |
| 3 | `grid-x000-y000` | 0.00 | 0.00 |
| 4 | `grid-x050-y000` | 0.50 | 0.00 |
| 5 | `grid-x025-y050` | 0.25 | 0.50 |
| 6 | `grid-x000-y025` | 0.00 | 0.25 |
| 7 | `grid-x050-y025` | 0.50 | 0.25 |
| 8 | `grid-x025-y000` | 0.25 | 0.00 |

The four extreme placements run first to maximize spatial separation. The
lower-image placements run first as a documented search heuristic, not a claim
that image coordinates identify a physical workspace direction. The already
successful center `(0.25, 0.25)` is prior-session evidence and is not billed
again in this grid.

## Gates and stop rules

1. If the fresh nominal sentinel succeeds, begin the grid. If it is a task
   failure, stop as `nominal_sentinel_failed`. Infrastructure or malformed
   evidence stops with its own classification.
2. A completed `success=false` episode is the first apparent policy failure.
   Stop grid discovery immediately; never continue until a more convenient
   candidate appears.
3. Run five fresh exact replays of that position. At least four policy failures
   among five valid replays makes it reproducible. Infrastructure or invalid
   evidence stops interpretation rather than counting as a policy outcome.
4. If the candidate is reproducible, run five fresh unoccluded episode-0
   controls. At least four successes among five valid controls is required for
   the phrase "perturbation-associated failure."
5. If the apparent failure does not repeat, stop and report flakiness. If all
   eight cells succeed, report a bounded negative result. Do not enlarge the
   grid, area, task, or perturbation family within this session.

Any launch cutoff, infrastructure error, or invalid evidence during replay or
matched controls stops the corresponding phase with a durable phase-specific
terminal reason. An incomplete set is never passed to a 4/5 gate. If all five
controls are valid but fewer than four succeed, record
`reproducible_failure_nominal_controls_failed`; do not imply that controls were
absent.

## Evidence contract

Use a new session directory so the completed severity-search evidence remains
immutable. The atomic summary records:

- the ordered grid, square geometry, episode identity, seeds, replay count,
  matched-control count, and launch cutoff;
- every attempted stage and its exact `x`, `y`, `width`, `height`, color, and
  opacity;
- the first apparent failure, replay outcomes, control outcomes, elapsed time,
  and terminal reason; and
- infrastructure and invalid-evidence states separately from policy outcomes.

Every launched episode retains aggregate JSON, SQLite, JSONL, and MP4 evidence.
Coordinate-bearing stage names and complete YAML parameters make a cell
replayable without interpreting labels such as "top-left."

## Viewer and demo boundary

The existing viewer already preserves the perturbation mapping. Add the `x,y`
coordinates to equal-area run labels so the eight cells are distinguishable.
A heatmap is deliberately deferred until real grid evidence exists; the MVP
demonstration can compare nominal, discovery, replay, and control videos using
the existing workbench.

## Episode and cost boundary

- No failure: 9 new episodes (one sentinel plus eight cells).
- Non-reproducible candidate: 7--14 episodes, depending on discovery order.
- Reproducible candidate with controls: 12--19 episodes.
- Hard maximum: 19 episodes, one GPU, one sequential worker.

The September 15 timings suggest roughly 7--9 minutes of evaluator work plus
model and VM startup. A future 26-minute ceiling would have been about US$0.834
at the last verified all-in rate, but that is planning evidence only. Live
price, balance, capacity, authentication, and a new user-approved cap are
mandatory before cloud execution.

## Claim boundary

A positive result may say that, for this frozen checkpoint and exact initial
state, one position produced a repeatable failure while matched fresh nominal
controls succeeded. A negative result may say no failure was observed at the
eight newly tested coarse-grid positions. Neither result establishes causality,
exhaustive spatial coverage, general robustness, or behavior on other tasks,
states, seeds, or perturbation families.
