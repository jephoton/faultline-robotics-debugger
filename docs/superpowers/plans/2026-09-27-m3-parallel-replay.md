# M3 Parallel Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether 1, 2, or 4 concurrent evaluators on one Nebius GPU VM confirm and replay the known M4 failure faster and at lower cost per valid episode.

**Architecture:** Generate one immutable 16-item manifest (eight nominal and eight reduced-mask repeats of task 0/episode 0/seed 7). A small project-owned scheduler runs each item through the existing one-episode `vla-eval` configuration against one shared GR00T server, with at most N concurrent processes and a unique output path per item. A separate reporter validates equal work and computes speed, cost, and outcome-drift measures from the three durable mode records. Keep the adaptive M4 reducer sequential and unchanged.

**Tech Stack:** Python 3.11 standard library, `unittest`, existing `run_failure_search._write_config` and `_load_stage_results`, pinned AllenAI VLA evaluation harness, GR00T N1.7 LIBERO Object on Nebius, JSON evidence, existing local viewer.

**Design:** `docs/superpowers/specs/2026-09-27-m3-equal-work-parallel-evaluation-design.md`; accepted decision `docs/decisions/0006-single-vm-parallel-replay.md`.

---

## Boundaries and checkpoints

- **Accepted:** one GPU VM, one shared model server, 1/2/4 evaluator processes, identical fixed repeats. Repeats of seed 7 are a systems workload, not fresh-state generalization.
- **Not accepted by this plan:** billable provisioning, a dollar cap, a new search algorithm, additional perturbations, model/simulator changes, multiple VMs, or public performance claims.
- **M3 result:** speed is measured first; cost per valid episode follows from actual billable elapsed time. If concurrency changes outcomes or produces invalid evidence, do not report equivalent-work speedup.
- **Live-run red gate:** after local dry-run, verify active Nebius account/project, credits and expiry, quota/capacity, live full VM plus storage price, server readiness, and resource state. Calculate a run-specific worst-case cap including startup and teardown margin; ask Jethro to approve it before any VM start. Keep the overall US$75 ceiling and reserve intact.
- **Single external owner:** the coordinator owns Nebius lifecycle, session launch, artifact copying, teardown, and Git integration. Agents may build or review local code in disjoint paths but do not start cloud resources.

## File map and ownership

| Unit / owner | Files | Contract |
| --- | --- | --- |
| Pure workload/metrics / implementation worker | Create `src/robot_debug/parallel_eval.py`, `tests/test_parallel_eval.py` | Immutable case IDs, equal-work manifest, worker assignment, metrics and drift checks; no subprocess/cloud |
| Local runner / implementation worker after interface freeze | Create `scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py` | One process per exact-case repeat, bounded concurrency, unique configs/results, durable attempt records and hard launch cutoff |
| Evidence integration / coordinator | Create `docs/experiments/m3-parallel.md`; modify `README.md`, `docs/codex-handoff/RUNBOOK.md`, `docs/codex-handoff/STATE.md`, `PROJECT_PLAN.md` after measured evidence | Reproduction commands, figures, limits, roadmap state |
| Review / independent reviewer | No implementation-file ownership | Compare spec and manifest/record evidence; audit unsafe launch paths, output collisions, equal-work math, and claims |

Parallel work is useful only after the pure contract is frozen: independent review and documentation preparation may then run alongside the runner. Keep the pure module and runner ownership disjoint. The coordinator resolves integration, runs the full suite, and presents the local dry-run evidence and proposed live cap at a learning checkpoint.

## Task 1: Verify pinned harness behavior and freeze the work identity

**Owner:** coordinator. **Autonomy:** Green research; amber workload-count rationale. No cloud.

**Files:** Create `docs/experiments/m3-parallel.md`.

- [ ] **Step 1: Inspect the exact pinned harness revision before using concurrency.** Read `src/vla_eval/orchestrator.py`, CLI `run` flags, Docker launch behavior, result filename rules, and GR00T server concurrency handling at revision `35f1200eb15608aa898f727a3722f7eef889c6cd`. Record the source URLs/commit in `docs/experiments/m3-parallel.md`. The known orchestrator work list is `(task, episode_index)` and cannot directly encode eight distinct repeats of episode index 0; therefore use the project-owned scheduler unless exact-code inspection disproves this.
- [ ] **Step 2: Fix the manifest identity contract.** Every entry is `{ "case_id": "nominal-01" | "mask-01", "kind": "nominal" | "mask", "repeat": 1..8, "task_id": 0, "episode_index": 0, "seed": 7, "env_seed": 7, "rectangle": null | {"x": 0.625, "y": 0.0, "width": 0.375, "height": 0.375} }`. Sort nominal 01–08 then mask 01–08. The exact same JSON-serialized manifest and SHA-256 digest must appear in every mode record. Record M4 provenance and why distinct episode indices would be a different experiment.
- [ ] **Step 3: Commit the research/contract note.** Run `git diff --check`; stage only `docs/experiments/m3-parallel.md`; commit `docs(hpc): fix M3 replay workload contract`.

## Task 2: Pure manifest, assignment, and report arithmetic

**Owner:** implementation worker. **Autonomy:** Green. No cloud.

**Files:** Create `src/robot_debug/parallel_eval.py`, `tests/test_parallel_eval.py`.

- [ ] **Step 1: Write failing `unittest` cases.** In `tests/test_parallel_eval.py`, cover: `build_manifest(8)` returns 16 unique IDs and exactly eight of each kind; `assign_items(manifest, workers)` for 1/2/4 assigns each ID exactly once; invalid worker counts/repeat counts raise `ValueError`; `manifest_hash` is stable across modes; `summarize_modes` rejects missing/duplicate case IDs, mismatched manifest digests, and any incomplete/invalid mode before calculating comparable speedup. Use a synthetic record with `workers=1, elapsed_seconds=160, valid_count=16, cost_usd=1.6` and `workers=2, elapsed_seconds=100, valid_count=16, cost_usd=1.0`; expect throughput 360 versus 576 valid/hour, speedup 1.6, efficiency 0.8, cost/valid $0.10 versus $0.0625. Run `$env:PYTHONPATH='src'; & 'C:\Windows\py.exe' -3.11 -m unittest tests.test_parallel_eval -v`; expect `ImportError` or assertion failures before implementation.
- [ ] **Step 2: Implement `build_manifest(repeats_per_case: int = 8) -> list[dict]`.** Construct exact values from Task 1; reject bool/non-int/zero; use `range(1, repeats_per_case + 1)`, stable zero-padded case IDs, and a newly allocated rectangle dict per mask case. `manifest_hash(items)` serializes with `json.dumps(items, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')` and returns SHA-256 hex. Do not put host paths or run mode into the manifest.
- [ ] **Step 3: Implement `assign_items(items, workers) -> list[list[dict]]`.** Accept only workers in `(1, 2, 4)`; assign item index `i` to `i % workers`; verify IDs unique before assignment. This is assignment metadata for audit—the runtime scheduler may dispatch each worker's next item as its previous process finishes. Do not use different seed or image geometry by mode.
- [ ] **Step 4: Implement `summarize_modes(records: list[dict]) -> list[dict]`.** Require exactly one record for each worker count, identical manifest hash and case-ID multiset, one terminal valid result per item, and finite positive elapsed seconds. Compute `valid_count / (elapsed_seconds / 3600)`, baseline elapsed divided by mode elapsed, and speedup/workers. Accept `cost_usd: null` for local tests and emit `cost_per_valid: null`; when a finite nonnegative cost is supplied, divide by valid count. Also emit per-kind outcome counts and `outcome_drift` when a case's outcome differs from the 1-worker mode. Reject invalid/incomplete comparisons rather than silently dropping results; retain their raw records for diagnosis.
- [ ] **Step 5: Run focused tests and commit.** Command from Step 1 must pass. Run `git diff --check`; stage the two owned files; commit `feat(hpc): define fixed replay workload and metrics`.

## Task 3: Bounded local runner and evidence validation

**Owner:** implementation worker, after Task 2 interface freeze. **Autonomy:** Green implementation; amber launch/timeout policy within the accepted design. No cloud until Task 6.

**Files:** Create `scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py`. Reuse, do not modify, `scripts/run_failure_search.py`.

- [ ] **Step 1: Write failing fake-runner tests.** Inject a callable with the same `subprocess.run(argv, cwd=..., check=False, timeout=...)` shape that writes a one-episode aggregate to the config's unique output directory. Test 1/2/4 maximum in-flight calls with `threading.Event` barriers; never exceed requested workers. Verify 16 unique config paths and output directories, all aggregates classified by `_load_stage_results(..., expected_count=1)`, and each task/episode index equals 0. Test a nonzero exit, missing aggregate, wrong episode index, an expired launch cutoff, and one `TimeoutExpired`: all remain explicit invalid/infrastructure attempts, stop new launches, preserve completed records, and never increment `valid_count`. Test refusal of a nonempty results directory and no automatic relaunch of uncertain in-flight work. Run `$env:PYTHONPATH='src'; & 'C:\Windows\py.exe' -3.11 -m unittest tests.test_parallel_eval_driver -v`; expect failure before implementation.
- [ ] **Step 2: Build each one-episode config using the existing helper.** For `item` call `base._write_config(config_path=session/'configs'/f"{case_id}.yaml", output_dir=session/'runs'/case_id, project_root=project_root, stage_name=f"m3-{case_id}", episode_indices=(0,), **({} if item['rectangle'] is None else item['rectangle']))`. Invoke `[base._resolve_evaluator_command(Path(sys.executable)), 'run', '--config', str(config_path)]` with `cwd=upstream_root`, `check=False`, and a positive per-item timeout argument. Do not pass `--shard-id` to sixteen one-item invocations: that would shard away work.
- [ ] **Step 3: Bound and persist scheduling.** `run_mode(..., workers: int, repeats_per_case: int = 8, launch_cutoff_seconds: float, item_timeout_seconds: float, command_runner=subprocess.run, monotonic_clock=time.monotonic)` creates a fresh `m3-workers-N` session via `base._prepare_session_directory`, writes the manifest before launch, and uses `ThreadPoolExecutor(max_workers=workers)` to keep at most N evaluator subprocesses active. Submit the next item only after a prior item finishes, cutoff permits it, and no invalid/infrastructure stop has occurred. Persist `session_summary.json` atomically before and after each attempt via `base._atomic_write_json`, including planned IDs, in-flight IDs, all terminal records, config/output relative paths, start/end monotonic durations, and stop reason. Never treat an unreturned subprocess as success. Let already-running attempts finish on stop, then return a partial mode record.
- [ ] **Step 4: Validate exact evidence.** A zero exit is insufficient: require exactly one aggregate, one task, one episode, `task_id == 0`, `episode_index == 0`, and a policy outcome from `base._load_stage_results`. Mark `invalid_evidence` for missing/mismatched artifacts; `infrastructure_error` for process failure or timeout. Require `record_video: true` in generated configs for this first M3 comparison so every completed result is visually inspectable; verify the recording file exists before labeling it replayable. Keep all output paths under the session root, with no overwrites.
- [ ] **Step 5: Add CLI and local smoke.** CLI accepts `--upstream-root`, `--project-root`, `--results-root`, `--workers {1,2,4}`, `--launch-cutoff-seconds`, and `--item-timeout-seconds`; it does not provision compute or query Nebius. A fake-evaluator test must complete three separate modes on the same manifest and use Task 2's reporter successfully. Run the focused test and full suite: `$env:PYTHONPATH='src'; & 'C:\Windows\py.exe' -3.11 -m unittest discover -s tests -q`. Both must pass. Run `git diff --check`; stage the two owned files; commit `feat(hpc): run bounded parallel replay modes`.

## Task 4: Mode reporter and evidence presentation

**Owner:** implementation worker for code, coordinator for public prose. **Autonomy:** Green, with amber interpretation checkpoint.

**Files:** Modify `scripts/run_parallel_eval.py`; create `tests/test_m3_report.py`; modify `docs/experiments/m3-parallel.md`.

- [ ] **Step 1: Test three-mode ingestion.** Add a `report` CLI subcommand that reads three explicit mode-summary paths; reject duplicate worker counts, a different manifest hash, missing items, and invalid/partial modes. Synthetic 160s/100s/80s data should yield speedups 1.0/1.6/2.0 and efficiencies 1.0/0.8/0.5. Assert cost/valid uses each mode's actual `cost_usd`, not worker count times unit price. Test outcome-drift flagging with one `mask-01` success in the 4-worker mode while it fails in baseline.
- [ ] **Step 2: Emit `m3_comparison.json` and a concise Markdown table.** Include `schema_version`, manifest hash, work count, per-mode valid/invalid counts, nominal/mask outcome counts, elapsed seconds, billable seconds, estimated cost with rate basis, throughput, speedup, efficiency, cost/valid, drift IDs, and source-summary paths. The `report` command takes three explicit `--mode-summary` paths plus optional `--hourly-rate-usd` and three `--billable-seconds WORKERS=SECONDS` values. Require all four cost inputs together; compute each mode's `cost_usd = hourly_rate_usd × billable_seconds / 3600`. The local dry-run omits cost inputs, emits null costs, and labels cost unavailable. Do not infer billable seconds from simulator runtime.
- [ ] **Step 3: Document interpretation limits.** `docs/experiments/m3-parallel.md` explains fixed repeat workload, one shared server, deterministic assignment, how to inspect per-item videos in the existing viewer, raw source paths, warm versus end-to-end clocks, and that this does not measure adaptive reducer speedup or new-state generalization. Run focused and full tests, `git diff --check`; commit `feat(hpc): report comparable replay throughput`.

## Task 5: Independent review and local learning checkpoint

**Owner:** coordinator; independent reviewer reads only. **Autonomy:** Green review, then human interpretation before claims.

- [ ] **Step 1: Review diff against the accepted spec and ADR.** Confirm exact same 16-item manifest across modes, bounded concurrency, no task/seed/geometry drift, unique output paths, no silent retries, no cloud calls, truthful missing-video handling, and no secrets or large artifacts staged. Ask the reviewer to challenge result comparability and cutoff behavior, not to restate implementation.
- [ ] **Step 2: Run independent verification.** On Windows Python 3.11: `$env:PYTHONPATH='src'; & 'C:\Windows\py.exe' -3.11 -m unittest discover -s tests -q`; expect all tests pass. Run `git diff --check` and `git status --short`; any unstaged task file or failure must be reconciled before the cloud gate.
- [ ] **Step 3: Present learning checkpoint to Jethro.** Show the fake-run evidence, the exact 16 cases, the process/server topology, expected bottlenecks, and an estimate of total 1+2+4 mode duration. Ask Jethro to predict whether two or four workers will help, then compare after the live result. Do not turn the prediction into a claim.

## Task 6: Separate paid-run authorization and bounded 1/2/4 execution

**Owner:** coordinator only. **Autonomy:** Red for cap approval, amber execution within approved cap. Stop here until approved.

- [ ] **Step 1: Preflight the real resource.** Refresh Nebius sign-in locally if needed. Read active tenant/project, credit balance/expiry, GPU quota/capacity, exact full VM rate and storage/network charges, existing VM/boot-disk state, and model-server readiness. Calculate `cap = (maximum planned billable VM hours × live full-resource hourly price + estimated storage/network) × safety margin`; show the numeric input values and proposed cap to Jethro. No start before approval.
- [ ] **Step 2: Arm cleanup and run a two-episode one-worker live pilot outside the comparison.** Run one nominal and one reduced-mask case to verify task/seed/geometry, server connectivity, aggregates, traces, and videos. Inspect outcomes and per-item time. The complete planned maximum is therefore 2 pilot + 48 comparison episodes, plus any explicitly counted infrastructure retries; do not silently add retries. Stop on drift from M4 known behavior, invalid evidence, or model-server instability. Recalculate the remaining approved cap before the full three-mode comparison; never silently raise it.
- [ ] **Step 3: Execute the identical fixed manifest at 1/2/4 workers.** Keep one model server and one GPU VM; record VM start/stop time, startup/download time, warm mode time, CPU/RAM/GPU memory/utilization and queue/request timing where observable. Stop launching on the approved cutoff. Copy summaries and representative media to local ignored artifacts, verify counts and hashes, then stop compute and remove temporary ingress. Preserve partial data if stopped.
- [ ] **Step 4: Reconcile billing and outcomes.** Supply the verified hourly rate and each mode's measured billable seconds to the reporter, verify all 48 comparison items or explicitly mark a partial session, and compare outcomes with M4 and across worker counts. Allocate shared startup/teardown time explicitly in a separate end-to-end cost column rather than hiding it in warm costs. If drift exists, investigate before reporting performance as equivalent work. Document measured speedup, efficiency, cost per valid episode, bottleneck, and limitations in `docs/experiments/m3-parallel.md`. Update `PROJECT_PLAN.md`, `README.md`, and handoff state/runbook. Run local suite and `git diff --check`; stage only documentation and small summary fixtures, never large artifacts or credentials; commit `docs(hpc): record bounded M3 results`.

## Final acceptance

- [ ] A local fake-evaluator pass proves one manifest, unique outputs, concurrency ceilings, cutoff, evidence validation, and no silent retry.
- [ ] The full Python suite passes and independent review finds no cloud or evidence-safety bypass.
- [ ] A separately approved, bounded Nebius session yields complete comparable 1/2/4 data—or is accurately labeled partial/invalid—and compute is stopped with ingress removed.
- [ ] The report links to inspectable source evidence, states whether faster workers actually lowered cost per valid episode, and does not claim whole-reducer or universal failure-search speedup.
