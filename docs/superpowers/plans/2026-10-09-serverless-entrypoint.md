# Serverless Entrypoint and Model Prefetch Plan

**Goal:** Finish migration Task 2 production wiring: pinned model prefetch,
production model/evaluator factories, provenance sidecar and the image
entrypoint `scripts/run_serverless_workload.py`. No cloud, Docker or GPU work.

**Boundary:** green/amber detail inside ADR 0018 and the October 6 migration
plan. No policy, simulator, algorithm, spend or topology change. Root (Claude
Code session) owns implementation and integration; an independent reviewer
checks spec and quality before the image build.

## Decisions (amber, explained at checkpoint)

- **Model inputs.** Prefetch exactly the three repositories the historical
  offline VM required (`docs/superpowers/plans/2026-09-14-bounded-cloud-session-execution.md`):
  checkpoint `nvidia/gr00t17-lerobot-libero_object-640@1499db35…`, base
  `nvidia/GR00T-N1.7-3B@2fc962b9…` and gated `nvidia/Cosmos-Reason2-2B`.
  Cosmos was never pinned historically; resolve `main` and record its commit.
- **Pin enforcement.** Download pinned repos by commit into a fresh job-private
  `HF_HOME`, then point that cache's `refs/main` at the approved commit and
  verify `local_files_only` resolution, matching the old `model-launch.sh`
  check. The server keeps the historical repo-ID argv and runs with
  `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`.
- **Secrets.** `HF_TOKEN` reaches only the prefetch process. Model server and
  evaluator environments drop secret-like variables. The exporter receives the
  token value to scan evidence for accidental leakage.
- **Deadlines.** Prefetch runs inside the workload's model factory, so its
  time counts against the same whole-workload deadline; it is capped at
  1200 s and leaves at least 600 s for start-up, evaluation and cleanup.
- **Signals.** First SIGTERM raises `KeyboardInterrupt` into the existing
  workload cleanup/export path; later SIGTERMs are ignored. Exit codes: 0
  complete, 1 partial, 143 SIGTERM, 130 SIGINT, 2 configuration error.

## Files

- Create `scripts/serverless_prefetch.py` (model env, Python 3.12, standalone).
- Create `src/robot_debug/job_entry.py` (simulator env, Python 3.8 grammar).
- Create `scripts/run_serverless_workload.py` (thin CLI wrapper).
- Create `tests/test_job_entry.py`.

## Tasks

- [ ] Tests for config loading limits, environment filtering, model argv
  equivalence with `scripts/cloud_guest/model-launch.sh`, prefetch argv/env,
  bounded prefetch timeout and failure cleanup (real POSIX child), provenance,
  exit-code mapping and SIGTERM translation. Commit
  `feat(jobs): wire serverless entrypoint with pinned model prefetch`.
- [ ] Prefetch script unit test with a fake `huggingface_hub` module.
- [ ] Windows and WSL focused suites, full suite, Python 3.8 grammar check.
- [ ] Independent spec/quality review; fix, then update handoff and the
  migration plan's Task 2 checklist.

## Next boundary

Local image build and native image probes (Task 3 remainder), then the read-only
cloud preflight and the already approved US$3 single-L40S pilot (Task 4).
