# M7a step 3: breadth pack

**Design:** ADR 0032 (accepted October 15). **Spend cap:** US$6.00 for live
runs (raised from US$4.00 by the project owner, October 15), in the order below, cutting from the end. No paid run before the project owner
approves this plan.

## Units and ownership

| Unit | Files | Owner |
| --- | --- | --- |
| S. Suites, image catalog, scene families, instruction override (simulator side) | `src/robot_debug/libero.py`, `image_perturbation.py`, `scene_inspect.py` (if needed), `job_entry.py`, `scripts/serverless_prefetch.py`, `m6_experiment.py` (family registry and deadlines), `workloads.py` (`audit_workload` families), tests | agent S |
| L. Language: paraphrase generation, word-edit model, `paraphrase-screen` / `paraphrase-reduce` Job modes, spec/orchestrator/CLI integration for all new families and the paraphrase mode | new `src/robot_debug/paraphrase.py`, new `src/robot_debug/language_experiment.py`, `token_factory.py` (additive), `job_runtime.py`, `job_workload.py`, `scripts/prepare_serverless_job.py` (deadline guard), `spec.py`, `orchestrator.py`, `cli.py`, `configs/specs/`, report script for paraphrase runs, tests | agent L |
| C. Calibration, model comparison, image, live runs, docs | CPU probes, the paraphrase-model comparison, image v15, Jobs, experiment note, README/FEEDBACK/STATE | coordinator |

Agent S exposes, and agent L uses: an `instruction` override in
`DiagnosticLIBEROBenchmark` (the exact text the policy receives; recorded in
each episode's sidecar) and the family names below. Smaller model (Sonnet)
for S and L; TDD with fakes; Job-side code stays Python 3.8 compatible; no AI
co-author trailers.

## S. Simulator side (amber)

- **Suites:** `libero_spatial` and `libero_goal` in the suite map
  (checkpoint ids above, revisions pinned in `serverless_prefetch.py` from one
  read-only Hugging Face API call), per-suite step limits from upstream
  (`MAX_STEP_MAPPING`), task bounds 0–9, validated everywhere a suite is.
- **Image catalog** (`ScalarPerturbation` kinds, severity s in [0, 1], s = 0
  identity, both cameras, deterministic):
  `jpeg` (quality from 95 at s = 0 down to 5 at s = 1, encode/decode with the
  image's existing libraries — check what the LIBERO image has, else a pure
  numpy 8x8 DCT quantiser), `colour_cast` (per-channel gains toward a warm
  tint, up to x0.4 / x1.6 at s = 1), `motion_blur` (horizontal line kernel up
  to 31 px), `dead_pixels` (fraction 0.2 s of pixels set to 0 or 255 from a
  seeded RNG keyed like the noise family). Recorded frames show what the
  policy saw.
- **Scene families** (applied at reset, after the start state, before
  settling): `viewpoint` (agent-view camera moved up to 0.10 m sideways and
  tilted up to 10 degrees at s = 1; calibrate on CPU that s = 1 keeps the
  table and objects in view) and `lighting` (all scene light diffuse and
  ambient values scaled by 1 - 0.9 s; check shadows/headlight behaviour).
  Both deterministic; sidecar records the applied values.
- **Instruction override:** a benchmark option `instruction` that replaces
  the task language the policy receives (verify upstream where the
  instruction enters the observation); recorded per episode.
- Audit mode accepts all new families with sensible worst-case timing.

## L. Language side (amber)

- `paraphrase.py`: Token Factory call returning N (default 10) varied
  paraphrases as strict JSON; validation (non-empty, ASCII-safe, under 200
  chars, distinct, no change of the objects' or target's identity is NOT
  enforced — record it); `word_edits(original, paraphrase)` via difflib
  opcodes on tokens; `apply_edits(original, edits_subset)` producing a valid
  string; deterministic.
- `paraphrase-screen` Job: one attempt per paraphrase (plus the original as
  a control), then confirm any failure to 4 of 5 with early-decided gates;
  summary lists every instruction text and outcome.
- `paraphrase-reduce` Job: given the original and one reproducing
  paraphrase, ddmin over its word edits (reuse `scenario_reduce.ddmin` and
  the decided gates), 1-minimal set of edits, gates for the original (passes
  5 of 5) and the full paraphrase (fails 4 of 5); summary with the minimal
  instruction text and the edit list.
- Spec: `mode: paraphrase` (`task`, `start`, `count`, `nemotron.paraphrase`
  model choice), new family names in `audit.families`; orchestrator
  pipeline paraphrase -> screen -> reduce -> report -> case -> explanation;
  dry-run shows the plan.
- Report and case for paraphrase runs (original vs minimal wording, videos).

## C. Coordinator

1. Paraphrase-model comparison (Nano / Super / Ultra, a few cents): validity,
   diversity, meaning preserved; pick by the ADR 0030 rule.
2. CPU calibration of viewpoint and lighting bounds in the image (free).
3. Independent review of S and L; image v15; in-image 3.8 tests.
4. **Live runs (US$6.00 total, ledger-enforced, in order):** suite smokes for
   Spatial and Goal (one short Job each) -> catalog audit (LIBERO-Object task
   0, the four new families) -> paraphrase diagnosis (LIBERO-Object task 0)
   -> viewpoint and lighting audit. Each through `faultline diagnose`.
5. Experiment note, FEEDBACK, STATE, README breadth table.

## What would change direction

- A family never fails up to s = 1: report it as robust in range.
- No paraphrase fails reliably: report robustness to rewording (a valid
  result) and skip the reduction.
- Viewpoint or lighting bounds break the scene (objects out of view): narrow
  the bounds after calibration, before any paid run.
