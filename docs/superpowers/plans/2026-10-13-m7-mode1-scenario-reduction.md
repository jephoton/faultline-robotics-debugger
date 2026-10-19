# M7 mode 1: screen for a natural failure and reduce its scenario

**Goal:** (1) Find a start state from which GR00T N1.7 reproducibly fails a
LIBERO-10 task without any perturbation. (2) Reduce the differences between
that start and the nearest passing start to a minimal cause, with Nemotron
proposing the order and a hypothesis, and save it as a replayable case.

**Design:** ADR 0028 (accepted October 13), inside ADR 0027; early-decided
gates from ADR 0029 (labelled M3). **Spend cap:**
US$4.00 for this phase (image smoke, screen, reduction smoke, reduction, one
retry). No GPU Job runs before the project owner approves this plan.

## Flow

```text
scenario-smoke Job ─► scenario-screen Job ─► local: pick failing start,
                                              nearest passing reference,
                                              difference table, Nemotron
                                              hypothesis and order
                                          ─► scenario-reduce Job
                                          ─► local: report, explanation,
                                              hypothesis verdict, case
```

The Token Factory call stays on the workstation; no key enters a Job.

## Components and ownership

| Unit | Files | Owner |
| --- | --- | --- |
| A. Suite and start selection | `scripts/run_failure_search.py` (`_write_config`), `src/robot_debug/libero.py`, `src/robot_debug/job_entry.py`, `scripts/serverless_prefetch.py`, tests | agent S (simulator side) |
| B. Scenario start and validity | `src/robot_debug/libero.py`, new `src/robot_debug/scenario_import.py`, `src/robot_debug/external_reset.py` (generalise, no behaviour change for accepted demos), tests | agent S |
| C. Scenario state model | new `src/robot_debug/scenario_state.py`, tests | agent P (pure side) |
| D. Scenario reducer | new `src/robot_debug/scenario_reduce.py`, tests | agent P |
| D2. Early-decided gates (M3) | new `src/robot_debug/decided_gate.py`, used by `scenario_reduce.py`, tests | agent P |
| E. Reference choice and Nemotron hypothesis | new `src/robot_debug/scenario_hypothesis.py`, `src/robot_debug/token_factory.py` (additive), new `scripts/plan_scenario_reduction.py`, tests | agent P |
| F. Job modes | `src/robot_debug/job_runtime.py`, `job_workload.py`, `job_entry.py`, new `src/robot_debug/scenario_experiment.py`, `scripts/prepare_serverless_job.py`, tests | agent S after A–E merge |
| G. Report and case | new `scripts/report_scenario_reduction.py`, case writer in `src/robot_debug/scenario_experiment.py`, tests | agent S |
| H. Image, Jobs, docs | image v12, `docs/experiments/m7-scenario-reduction.md`, `FEEDBACK.md`, `STATE.md`, `PROJECT_PLAN.md` | coordinator only |

Agents S and P work in parallel in separate worktrees (no shared files: S
owns `libero.py`, `run_failure_search.py`, `job_*`; P owns the three new pure
modules and the additive `token_factory.py` change). The coordinator merges
P first, then S, then hands F and G to agent S. Implementation agents use a
smaller model (Sonnet). The coordinator owns all cloud resources, image
pushes and GitHub pushes. No AI co-author trailers or "Generated with"
lines.

## A. Suite and start selection (amber)

- `_write_config` gains `suite` (default `libero_object`) and
  `init_state_index` (optional). Defaults leave existing YAML byte-identical
  (existing tests unchanged).
- `DiagnosticLIBEROBenchmark` accepts `init_state_index`: the episode starts
  from that benchmark init state instead of the harness's episode index.
  Before coding, verify in the pinned harness (`35f1200`) how upstream
  `LIBEROBenchmark.reset` picks init states and the per-suite step limit
  (expected 520 for LIBERO-10); record both in the experiment note.
- Suite to checkpoint map: `libero_object` and `libero_10` →
  `nvidia/gr00t17-lerobot-libero_{suite}-640`. Pin the LIBERO-10 revision in
  `serverless_prefetch.py` (resolved once from the Hugging Face API, a
  read-only call). One suite per Job (one model server).
- Every Job and case records suite, task, init state index and checkpoint
  revision.

## B. Scenario start and validity (amber)

- New benchmark option `scenario_start` (`{"candidate", "metadata_out"}`
  paths, same shape as `external_reset`). The candidate is a JSON document:
  `schema_version`, `suite`, `task_id`, `state` (flat MuJoCo state vector),
  `source` (for example `{"kind": "benchmark", "init_state_index": 23}` or
  `{"kind": "hybrid", "reference": 7, "applied": [...]}`), `state_sha256`.
  It uses the task's own scene XML (no model XML in the candidate), so state
  length must equal the environment's.
- `scenario_import.py` validates candidates fail-closed (exact keys, finite
  numbers, length, suite and task match, hash) and builds candidates from a
  benchmark init state. The existing external demo path keeps its pinned
  hashes and behaviour; a shared validation helper is factored out only if it
  changes no existing test.
- Reset: `set_init_state(state)`, forward, then the **validity check** before
  settling: any contact between bodies of different entities with
  penetration deeper than 5 mm marks the scene `invalid_scene`. The episode is
  then ended immediately and recorded with that outcome, never as a policy
  failure. Valid scenes settle as usual (`num_steps_wait`).
- **Layout export:** on first reset per task, write a layout sidecar: for
  every joint its name, type, qpos and qvel address, and the owning entity
  (robot, or object body name). This is what lets the pure side name
  differences.
- The sidecar records state hash before and after settling, validity, the
  deepest penetration and per-object settle displacement.

## C. Scenario state model (green, pure)

`scenario_state.py`, numpy only, tested with synthetic layouts:

- `entities(layout)`: robot (arm joints and gripper) and each free-joint
  object (position xyz, rotation quaternion).
- `differences(failing, reference, layout)`: per entity, position offset
  (metres), rotation angle (degrees, quaternion distance), joint offsets.
  Below the noise floor (position 2 mm, rotation 1 degree, joint 0.5 degree)
  an entity counts as unchanged. Output is a stable, ordered table.
- `hybrid(reference, failing, selection, layout)`: `selection` maps entity to
  `{"position": t, "rotation": t}` (or `{"joints": t}` for the robot), with
  `t` in [0, 1]: position and joints interpolate linearly, rotation by slerp.
  Unselected entities keep the reference. Velocities are set to zero (benchmark
  starts are at rest; asserted in the smoke).
- Deterministic hashing of hybrid states for caching and replay.

## D. Scenario reducer (amber, pure)

`scenario_reduce.py`, family-agnostic like `threshold_search.py`:
`run_scenario_reduction(evaluate, differences, *, order, attempts=5,
required_failures=4, bisection_steps=4, max_candidates=30)` where
`evaluate(selections, attempts)` runs several candidates concurrently and
returns their outcomes.

1. **Gates.** The failing start must fail at least 4 of 5; the reference must
   succeed 5 of 5 (if not, try the next nearest reference, at most two;
   otherwise stop `reference_not_passing`).
2. **Ranked probe.** Test single entities alone in the given order (Nemotron's
   ranking, or the fixed order: largest difference first). A singleton that
   reproduces is already 1-minimal (removing it gives the passing
   reference); skip to step 4.
3. **Delta debugging** over entities (ddmin with subsets and complements;
   independent candidates in a round run concurrently, two at a time on 12
   workers) until no single entity can be removed.
4. **Split.** For each surviving object, test position-only and
   rotation-only; keep the smallest part that still reproduces (both if
   neither alone does).
5. **Shrink.** For each surviving part, bisect `t` from 1 towards 0
   (`bisection_steps` steps, so tolerance 1/16 of the original difference),
   other parts held at their current values.

Rules: a candidate reproduces only with at least 4 of 5 policy failures;
`invalid_scene` counts as not reproducing and is reported; any infrastructure
error stops with `infrastructure_error`. Results are cached by hybrid hash.
Stop reasons: `reduced`, `failing_not_reproducible`, `reference_not_passing`,
`budget_exhausted`, `deadline_exhausted`, `infrastructure_error`. The result
records every candidate, its outcomes, the final selection, the number of
reruns, and how many candidates the ranked probe saved compared with starting
straight at step 3 (counted, not claimed as a measured speedup).

**Early-decided gates (D2, ADR 0029, labelled M3).** `decided_gate.py`
decides a 4-of-5 gate at 4 failures or 2 successes, and the reference's
5-of-5 pass gate at its first failure. The reducer submits attempts through
it: once a candidate is decided, its not-yet-started attempts are skipped as
`decided_skipped`; started attempts finish and are recorded without changing
the decision. Workers freed this way take attempts of other independent
candidates (a ddmin round, or two bisection points at once). Tests assert
that every decision equals the all-five-attempts decision for all 32 outcome
sequences, and count the skipped attempts.

Tests: synthetic evaluators with a known culprit (single entity, a pair,
rotation-only, threshold at t = 0.4), stochastic evaluators, invalid scenes,
reference fallback, budget and deadline, and the exact candidate sequence
for a fixed order.

## E. Reference choice and Nemotron hypothesis (amber)

- `nearest_reference(failing_index, screen_results, states, layout)`: among
  starts of the same task that succeeded in the screen, the smallest summed
  object distance (position in cm plus rotation in degrees divided by 10);
  returns the ranked fallbacks too.
- `request_scenario_hypothesis` in `token_factory.py` (additive): sends the
  task instruction and the difference table only (no images, no IDs), asks for
  a JSON ranking of entities and a one-paragraph hypothesis. Model: Nemotron
  3 Ultra, Super if Ultra is not in the catalog (checked by a catalog read).
  Invalid JSON, unknown entity names or an unavailable model fall back to
  the fixed order and say so; the response is stored beside the case.
- `scripts/plan_scenario_reduction.py SCREEN_SUMMARY --task T --start S
  [--env-file .env]` writes the reduce config: suite, task, failing start,
  reference and fallbacks, differences, order and hypothesis.
- After the reduce Job: the existing explanation path (Nano) explains the
  verified result, and the case records the hypothesis verdict
  (`confirmed`, `partly`, `refuted`) by comparing the ranked top entity
  with the reduced selection (a mechanical rule, not an LLM judgement).

## F. Job modes (amber)

Reuse the M3/M6 runner (`batch_experiment.py` prefetch, server with
`max_batch_size=12`, untimed warm-up, `EvaluatorPool` with 12 workers,
SQLite scrub, export). Functional names; ADR 0027's spec-driven mode will
wrap them later.

- `scenario-smoke` (LIBERO-10, one task): init start 0 twice; one hybrid
  between starts 0 and 1 (objects from start 1, robot from 0); one
  deliberately overlapping candidate expected to be `invalid_scene`; layout
  export. Shows the new checkpoint loads, starts are selectable, hybrids
  restore with matching hashes and validity detection works.
- `scenario-screen`: config `suite`, `task_ids`, `start_indices`,
  `attempts=1`, `confirm_attempts=4`. Every first attempt runs, then failing
  starts get 4 more. Summary: per task and start the outcomes and steps, the
  state vector and layout per task, and the list of starts failing at least
  4 of 5.
- `scenario-reduce`: config from E. Runs D with the pool. Summary: the full
  reduction result, attempts skipped by early decisions plus videos of the failing start, the minimal hybrid and
  the reference.
- The prepare script's deadline guard covers all three modes (at least
  1000 s). Config validation bounds every field.

## G. Report and case (green)

- `scripts/report_scenario_reduction.py SUMMARY.json` writes Markdown: the
  screen table, the difference table, every candidate with outcomes, the
  minimal cause in one sentence, the hypothesis and its verdict, reruns and
  cost.
- A case record (videos, minimal selection, replay recipe as a scenario
  candidate file, hypothesis, explanation) in a schema the later UI step
  will render; the current viewer at least lists it with its videos.

## Tests and commits

TDD with fakes; full Windows suite green before each commit; in-image
subset before each Job. Commits:

1. `docs(m7): plan mode 1 scenario screening and reduction`
2. `feat(m7): select LIBERO suite and benchmark start per stage`
3. `feat(m7): start episodes from validated scenario states`
4. `feat(m7): model scenario differences and hybrid start states`
5. `feat(m3): decide repeatability gates as soon as the outcome is fixed`
6. `feat(m7): add ranked delta-debugging scenario reducer`
7. `feat(m7): choose reference starts and request Nemotron hypotheses`
8. `feat(m7): run scenario smoke, screen and reduce workloads`
9. `feat(m7): report reduced scenarios as cases`
10. `docs(m7): record scenario screen and reduction results`

## Review and cloud gates

1. Independent review of A–G (state layout and slicing, slerp and
   interpolation, validity threshold, ddmin correctness and 1-minimality,
   concurrency and cleanup, early-decided gate equivalence, Nemotron
   fallback, backward compatibility).
2. Coordinator builds image v12 (adds the LIBERO-10 checkpoint prefetch),
   runs the in-image subset and a no-network check that LIBERO-10 starts
   load and the state length matches, pushes, verifies tag to digest.
3. **Smoke Job** (deadline about 1080 s, worst case about US$0.55).
4. **Screen Job** (deadline sized from smoke timings; expected about 25
   minutes, about US$0.8; worst case capped by watchdog). Show the project owner the
   screen table and the candidate failure before planning the reduction.
5. Local planning step (Nemotron call costs cents on Token Factory).
6. **Reduce Job** (expected about 20 minutes, about US$0.7).
7. Watchdogs enforce the remaining US$4.00 cap across all Jobs.
8. The project owner interprets the minimal cause and the hypothesis verdict before any
   claim.

## What would change direction

- No start fails at least 4 of 5 in the screen: stop and return to the project owner
  (widen the screen, another suite, or an engineered start labelled as such).
- The reference never passes 5 of 5: report it; do not loosen the gate
  without a decision.
- Most hybrids are `invalid_scene`: revisit the threshold or interpolation
  before spending more.
- The failure needs every difference (nothing reduces): that is a valid
  result ("the whole arrangement matters"); report it honestly.
