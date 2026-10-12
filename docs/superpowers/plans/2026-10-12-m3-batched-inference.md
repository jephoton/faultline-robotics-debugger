# M3: batched GR00T inference experiment

**Goal:** Find where the shared GR00T server becomes the bottleneck as evaluator
workers increase, then test whether batching concurrent requests raises
replay throughput by at least 15% without changing outcomes.

**Design:** ADR 0025 (accepted October 12). **Timebox:** 3 working days
(ADR 0023). **Spend cap:** US$1.50 AI Cloud for all Jobs in this plan.

## Workload

- Frozen equal-work manifest: the certified case, 12 nominal repeats then 12
  reduced-mask repeats (`(0.625, 0, 0.375, 0.375)`), task 0, seed as in M3.
  24 items divide evenly across 4, 8 and 12 workers.
- Known outcomes: nominal succeeds, reduced mask fails (M3 and M4 evidence).
- A **phase** = one `(workers, max_batch_size)` pair run over the whole
  manifest against a freshly started model server. Unbatched phases use
  `max_batch_size = 1` (upstream `predict()` path behind the lock).

| Job | Phases (in order) | Deadline | Worst case |
| --- | --- | --- | --- |
| Smoke | parity check, then `(4, 4)` on 4 items | 18 min | US$0.52 |
| Measurement | `(8,1)`, `(8,8)`, `(12,1)`, `(12,12)`, `(4,1)` | 32 min | US$0.93 |

Most informative phases run first so a deadline still leaves a comparison.
Total worst case US$1.45 ≤ US$1.50. The measurement Job runs only after the
smoke Job passes and Jethro sees its result.

## Components and ownership

| Unit | Files | Owner |
| --- | --- | --- |
| A. Batch server | `scripts/model_servers/faultline_groot_server.py`, `tests/test_groot_batch_server.py` | implementation agent |
| B. Parity check | `scripts/model_servers/groot_batch_parity.py`, `tests/test_groot_batch_parity.py` | implementation agent |
| C. Runtime wiring | `src/robot_debug/job_entry.py`, `job_runtime.py`, `job_workload.py`, `scripts/prepare_serverless_job.py`, tests | implementation agent |
| D. Phase runner and summary | `src/robot_debug/batch_experiment.py`, `tests/test_batch_experiment.py` | implementation agent |
| E. Local report | `scripts/report_batch_experiment.py`, `tests/test_report_batch_experiment.py` | implementation agent |
| F. Image, Jobs, docs | image rebuild, `docs/experiments/m3-batched-inference.md`, `FEEDBACK.md`, `STATE.md`, `PROJECT_PLAN.md` | coordinator only |

Units A–E are sequential-ish but small; one implementation agent does them in
order. The coordinator owns all cloud resources, the image push and pushes to
GitHub. Commit messages must not include AI co-author trailers.

## A. Batch server (model environment) — amber

`scripts/model_servers/faultline_groot_server.py` runs under the model
environment's Python (`/opt/model-env/bin/python`), like upstream
`lerobot.py`. It must not import `robot_debug` (not installed there).

- `class FaultlineGrootServer(LeRobotModelServer)` from
  `vla_eval.model_servers.lerobot`, launched with upstream
  `vla_eval.model_servers.serve.run_server`, accepting the same `--args.*`
  flags plus `--args.max_batch_size` (upstream already supports it) and
  `--args.timing_log` (path).
- `predict_batch(obs_batch, ctx_batch)`: build each item's raw frame exactly as
  upstream `predict()` does (image map, resize, state, task), then run
  `prepare_observation_for_inference` and `self._preprocess` **once on the
  stacked batch** (tasks as a list), one `predict_action_chunk`, one
  `self._postprocess`, and split along dim 0 into per-item
  `{"actions": (n_steps, action_dim) float32}`. If the processor rejects a
  batched input, raise a clear `RuntimeError` (the smoke Job must fail
  loudly, not silently fall back).
- Keep `predict()` as upstream's for `max_batch_size == 1`.
- Timing: wrap `on_observation`, `predict` and `predict_batch` to append one
  JSON line per inference call to `timing_log`:
  `{"t": monotonic, "batch_size": n, "inference_ms": x, "wait_ms": [per item ms from observation arrival to inference start]}`.
  Buffered writes, flushed at most once per second and on shutdown; never
  log observations, images or task text.
- Pure helpers (`stack_frames`, `split_actions`, timing record builder) are
  importable without torch so they can be unit-tested on Windows with stub
  `vla_eval` modules in `sys.modules`.

## B. Parity check (model environment, GPU) — amber

`scripts/model_servers/groot_batch_parity.py` constructs the server class
once (same flags as the Job), builds two synthetic observations A and B
(fixed random images of the declared shapes, distinct states, the task-0
instruction), and checks with `torch.manual_seed(s)` before each call:

1. item 0 of `predict_batch([A, B])` ≈ `predict(A)`;
2. item 0 of `predict_batch([B, A])` ≈ `predict(B)`;
3. `predict(A)` and `predict(B)` differ (the check is not vacuous);
4. shapes and dtypes match.

Tolerance: max absolute difference ≤ 0.05 in action units (bf16 batch
kernels are not bitwise equal); record the observed maximum. The first slice
of a seeded batched `randn` equals the single-call draw, so this tests that
each item is routed and decoded with its own state. Writes
`parity.json` with pass/fail and maxima only. Exit code 0 pass, 1 fail.

## C. Runtime wiring — green/amber

- `model_server_argv(layout, *, server="upstream"|"faultline", max_batch_size=1, timing_log=None)`;
  `"upstream"` stays byte-identical to today's argv (existing tests must pass
  unchanged).
- `ProductionModelFactory` accepts the same options per start; the prefetch
  runs once per Job and later starts reuse it.
- New workload modes `m3-batch-smoke` and `m3-batch` in `_MODES`, with config
  fields `phases: [[workers, max_batch_size], ...]` (workers ∈ {4, 8, 12},
  max_batch_size ∈ {1, workers}), `repeats_per_kind` (2 for smoke, 12 for
  measurement) and the existing deadline fields. Validation rejects anything
  else. `prepare_serverless_job.py` accepts the new modes.

## D. Phase runner and summary — amber

`src/robot_debug/batch_experiment.py`, driven from `job_workload.py`:

- For each phase: start the model server with the phase options, wait for
  readiness, launch `workers` evaluators concurrently, each taking the next
  manifest item from a shared queue until it is empty (work stealing keeps
  12 workers busy), record per-item outcome, then stop the server and verify
  its process group is gone before the next phase. Reuse the existing owned
  process-group, deadline and progress logging helpers; never start a phase
  that cannot finish before the launch deadline (estimate from the slowest
  completed phase, or skip with `deadline_skipped`).
- The smoke mode runs the parity check (B) first and skips the phase if
  parity fails.
- Per-phase record: workers, max_batch_size, manifest hash, warm elapsed
  (first launch to last completion), valid count, outcomes by kind, drift IDs
  (any nominal failure or mask success), episodes per minute, and timing
  stats from the server log: calls, mean and p95 batch size, p50/p95
  inference ms, p50/p95 wait ms, share of wall time the GPU was busy.
- Summary: all phase records plus, for each worker count with both phases,
  `speedup = batched / unbatched` throughput and the ADR 0025 verdict
  (`works`, `no_measurable_gain`, `outcome_drift`, `parity_failed` or
  `incomplete`). Exported with the existing closed-evidence exporter.

## E. Local report — green

`scripts/report_batch_experiment.py SUMMARY.json` writes a Markdown table and
a short plain-language explanation of where the bottleneck sits, for the
experiment note. No network access.

## Tests and commits

TDD with fakes throughout; WSL- or image-only tests marked like existing ones.
Full Windows suite green before each commit
(`PYTHONPATH=src python -B -m unittest discover -s tests`). Commits:

1. `docs(m3): accept batched-inference experiment design` (ADR 0025, this plan)
2. `feat(m3): add instrumented GR00T batch server`
3. `feat(m3): add seeded batch parity check`
4. `feat(jobs): start model server variants per phase`
5. `feat(m3): run batched-inference phases in Serverless workloads`
6. `feat(m3): report batched-inference experiment`
7. `docs(m3): record batched-inference results`

## Review and cloud gates

1. Independent review of A–E against ADR 0025 (process cleanup between
   phases, deadline handling, parity validity, no secrets in logs).
2. Coordinator rebuilds the image, runs the in-image test subset, pushes and
   verifies tag → digest.
3. Delete the three leftover buckets from October 10–11 if they are empty.
4. **Smoke Job** (≤ 18 min). Show Jethro the parity and smoke result.
5. **Measurement Job** (≤ 32 min) only if smoke passed. Watchdog cancels at the
   deadline plus 3 minutes either way.
6. Jethro interprets the result against the 15% bar before any claim.

## What would change direction

- Parity fails because the processor cannot batch → try per-item preprocessing
  with an explicit per-item state for decoding (one more smoke Job only if
  budget allows); otherwise record "stuck" and move to the portfolio fallback.
- Unbatched efficiency stays near-linear at 12 workers (GPU never saturates)
  → batching cannot help on this workload; record that as the M3 finding.
