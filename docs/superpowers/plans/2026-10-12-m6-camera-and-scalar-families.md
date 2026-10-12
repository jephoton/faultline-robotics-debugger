# M6: camera reliance and scalar image families

**Goal:** (1) Test whether GR00T's failure under the reduced agent-view mask
depends on the camera, using wrist-camera conditions. (2) Extend Faultline's
find, confirm and reduce loop to four single-strength image families and
report each family's smallest reproducibly failing severity.

**Design:** ADR 0026 (accepted October 12). **Spend cap:** US$3.00 after
Jethro's top-up; no GPU Job before he confirms the new balance. **Target:**
built and reviewed by October 14, results by October 16, M7 from October 23
at the latest.

## Components and ownership

| Unit | Files | Owner |
| --- | --- | --- |
| A. Perturbations | `src/robot_debug/image_perturbation.py` (new), `src/robot_debug/occlusion.py`, `src/robot_debug/libero.py`, tests | implementation agent |
| B. Config writer | `scripts/run_failure_search.py` (`_write_config`), tests | implementation agent |
| C. Threshold engine | `src/robot_debug/threshold_search.py` (new), tests | implementation agent |
| D. Serverless modes | `src/robot_debug/job_runtime.py`, `job_workload.py`, `batch_experiment.py` (reuse), new `src/robot_debug/m6_experiment.py`, `scripts/prepare_serverless_job.py`, tests | implementation agent |
| E. Report | `scripts/report_m6_experiment.py`, tests | implementation agent |
| F. Image, Jobs, docs | image v11, `docs/experiments/m6-camera-and-scalar-families.md`, `FEEDBACK.md`, `STATE.md`, `PROJECT_PLAN.md` | coordinator only |

One implementation agent does A to E in order. The coordinator owns all cloud
resources, the image push and GitHub pushes. No AI co-author trailers.

## A. Perturbations (amber)

- **Wrist occlusion:** `DiagnosticLIBEROBenchmark` accepts an optional
  `wrist_occlusion` mapping (same `RectOcclusion` schema) applied to
  `images["wrist"]`, independent of `agentview_occlusion`. Existing configs
  without it behave byte-identically.
- **Scalar families** (`image_perturbation.py`): `ScalarPerturbation(kind, severity)`
  with `kind` in {darken, noise, blur, contrast} and `severity` in [0, 1].
  Mapping: darken multiplies by `1 - 0.95 s`; noise adds Gaussian noise with
  sigma `100 s` (uint8 clip); blur applies a Gaussian of sigma `8 s` px;
  contrast maps `x -> mean + (1 - 0.9 s)(x - mean)` per image. `s = 0` is the
  identity. Pure numpy (no new dependencies); blur via a separable kernel.
- **Determinism:** noise uses `numpy.random.default_rng(seed)` where the seed
  is a stable hash of (episode seed, step index, camera name, kind, severity),
  so a replay reproduces every frame. Unit tests assert identical output for
  identical inputs and different output for a different step.
- Applied in `make_obs` to **both** cameras; the recorded agent-view video
  shows the perturbed frame so demos match what the policy saw. Order: scalar
  family first, then any occlusion.
- Sidecar records include the perturbation spec for replay.

## B. Config writer (green)

`_write_config` gains optional `wrist_occlusion` (rectangle dict) and
`image_perturbation` (`{"kind", "severity"}`) parameters, validated, emitted
under the benchmark params. Defaults leave existing YAML byte-identical
(existing tests unchanged).

## C. Threshold engine (amber)

`threshold_search.py`, pure and family-agnostic:

- `run_threshold_search(evaluate_level, *, sweep=(0.2, 0.4, 0.6, 0.8, 1.0), attempts=5, required_failures=4, bisection_steps=4)`
  where `evaluate_level(severity, attempts) -> list[outcome]` runs the
  attempts (in parallel inside the runner).
- Sweep in increasing order; stop at the first level with at least 4 of 5
  policy failures. Lower bound = the previous sweep level (or 0.0). Bisect
  `bisection_steps` times: a reproducible midpoint becomes the new upper
  bound, otherwise the new lower bound. Result: `threshold_severity`
  (smallest reproducible tested level), `lower_bound`, per-level attempt
  outcomes, physical parameter values and `stop_reason` in
  {threshold_found, no_reproducible_failure, budget_exhausted,
  deadline_exhausted, infrastructure_error}.
- Infrastructure errors are never counted as policy failures; any invalid
  attempt stops that family with `infrastructure_error`.
- Tests: synthetic deterministic and stochastic evaluators (monotone
  failure-probability curves), the exact sequence of severities tried, the
  no-failure case, and deadline handling.

## D. Serverless modes (amber)

Reuse the M3 machinery in `batch_experiment.py` (prefetch once, faultline
server with `max_batch_size = 12`, untimed warm-up, concurrent evaluator pool
with cancellation, SQLite scrub, per-run summaries, export). Factor out a
shared runner rather than copying it.

- `m6-smoke`: nominal x6; reduced agent-view mask + wrist black x12; same
  rectangle on wrist only x12; and severity 0.6 x2 for each of the four
  families. 12 workers, one server.
- `m6-threshold`: nominal controls x5, then the four families' threshold
  searches **concurrently**, sharing the 12-worker pool (each level's 5
  attempts run in parallel). A family that cannot start before the launch
  deadline is `deadline_exhausted`.
- Config validation: mode-specific fields only (conditions fixed for smoke;
  `families`, `sweep`, `attempts`, `required_failures`, `bisection_steps`
  bounded for threshold). The prepare script's batch-deadline guard covers
  both new modes (`deadline_seconds` at least 1000).
- Summary JSON `m6/m6_summary.json`: per condition outcome counts and
  durations; per family the full threshold result; nominal control results;
  timing and memory snapshots. Nominal controls must all succeed or the
  family results are marked `nominal_failed`.

## E. Report (green)

`scripts/report_m6_experiment.py SUMMARY.json` writes Markdown: the wrist
table (condition, successes and failures, median duration) and a threshold
table (family, threshold severity and physical value, lower bound, levels
tried, stop reason), plus a plain-language reading.

## Tests and commits

TDD with fakes; full Windows suite green before each commit. Commits:

1. `docs(m6): accept camera reliance and scalar family design`
2. `feat(m6): add wrist occlusion and scalar image perturbations`
3. `feat(m6): emit wrist and scalar perturbations in evaluator configs`
4. `feat(m6): add generic sweep-then-bisect threshold search`
5. `feat(m6): run M6 smoke and threshold workloads on Serverless`
6. `feat(m6): report M6 experiment results`
7. `docs(m6): record M6 results`

## Review and cloud gates

1. Independent review of A to E (noise determinism, camera keys, threshold
   logic and stop reasons, concurrency and cleanup, backward compatibility).
2. Coordinator builds image v11, runs the in-image test subset and a
   no-network check that the LIBERO observation image keys are `agentview`
   and `wrist`, pushes, and verifies tag to digest.
3. **After Jethro confirms the top-up:** smoke Job (deadline 1080 s, worst
   case about US$0.55). Show Jethro the wrist result and frames proving each
   family perturbs both cameras.
4. Main threshold Job (deadline sized from the smoke timings, at most
   2400 s, worst case about US$0.85). Watchdogs enforce the remaining cap.
5. Jethro interprets the wrist and threshold results before any claim.

## What would change direction

- A family never fails up to s = 1.0: report it as robust in this range; do
  not widen ranges without a new decision.
- Nominal controls fail under the new code: stop; the perturbation plumbing
  changed the unperturbed path.
- Smoke shows a family has no visible effect on frames: fix before the main
  Job.
