# Serverless Job Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Run future bounded robot diagnostics as finite Nebius GPU Jobs while preserving all historical evidence.

**Architecture:** One container, one warm localhost model server, one active direct evaluator. Separate simulator/model environments; stage closed outputs to private Object Storage and retrieve them for the existing viewer.

**Tech Stack:** Python stdlib/unittest, pinned LIBERO container, GR00T/LeRobot, Nebius CLI Serverless Jobs, private bucket mounts, JSON/JSONL/SQLite/MP4.

## Ownership, concurrency and gates

The user approved [the topology and storage](../../decisions/0018-serverless-jobs-for-future-runs.md),
then one US$3 / one-hour single-L40S validation allowance and 24-hour private
output retention. This is not permission to start before local image checks.
Actual balance/expiry are unknown; Jethro asserted adequate funds and declined
the console check. Record this exception rather than treating them as verified.
Root owns docs, integration, registry/cloud state and any spending. A balanced
smaller-model builder owns Tasks 1–3 in a clean attached worktree; Terra is not
available, use `gpt-5.6-sol` at medium. Root supplies task text. A separate
read-only packaging probe can run concurrently with Task 1 and root's preflight.
Independent spec review precedes independent quality review for each batch.
Builders never submit Jobs, publish images, provision storage, or push Git.

Dependency map: `runtime kernel → entrypoint → image probe → Job configuration → live pilot → recovery/viewer acceptance`.
`read-only cloud preflight` and `packaging research` can overlap the kernel.
No overlapping builder file ownership. Root cherry-picks only reviewed commits.
No agent edits historical artifacts, M3 launchers, or external replay.

### Task 1: Direct evaluator containment kernel — green

Files: create `src/robot_debug/job_process.py`, `tests/test_job_process.py`.

- [ ] Write failing unittest fixtures for an argv builder and real POSIX process
  lifecycle. Define the callable contract below; driver callback compatibility
  is `runner(command, cwd=path, check=False)` returning a CompletedProcess.

```python
# Expected public contracts; timeout applies to the whole owned process group.
direct_command("/opt/conda/envs/libero/bin/vla-eval", ["vla-eval", "run", "--config", "a.yaml"])
# => ["/opt/conda/envs/libero/bin/vla-eval", "run", "--config", "a.yaml", "--no-docker"]
DirectEvaluator(executable=path, timeout_seconds=5, env=process_env,
                log_root=fresh_logs)(command, cwd=upstream, check=False)
```

- [ ] Reject unexpected commands, invalid finite deadlines, duplicate/direct
  flag misuse and non-POSIX production execution; never use a shell.
- [ ] Test successful return, nonzero return, timeout, interrupt and an evaluator
  whose leader exits while a child remains. Use `sys.executable` fixture programs
  and actual process-group inspection, not mock-only lifecycle claims. Clean
  every test-owned group in fixture teardown. Launch no Docker/cloud command.
- [ ] Implement `start_new_session=True`, file-backed logs and bounded TERM/KILL
  cleanup/reaping/group-absence confirmation on success and failure. If cleanup
  is uncertain raise an infrastructure exception; do not return a valid outcome.
  Do not copy the M3 Docker-name observer into this direct runtime.
- [ ] Run red then green: `C:/Windows/py.exe -3.11 -m unittest tests.test_job_process -v`
  with source path set. Run POSIX cases under WSL; Windows skips are not acceptance.
- [ ] Commit explicit files: `feat(jobs): contain direct evaluator process groups`.
- [ ] Independent spec then quality review; fix and recheck before integration.

### Task 2: Sequential Job entrypoint and closed-file export — green/amber

Files: create `src/robot_debug/job_runtime.py`, `scripts/run_serverless_workload.py`,
`tests/test_job_runtime.py`. Do not modify existing search/reduction drivers.

- [ ] Write failing fixtures around a `run_workload(config, *, model_factory,
  evaluator_factory, exporter, clock)` seam. Configuration allowlists `pilot`,
  `search`, `grid`, `reduce`; rejects unknown keys, unsafe run IDs, secret values,
  deadlines outside `(0, 3000]`, and reuse of output directories.
- [ ] Implement the wrapper using Task 1's callback in the existing drivers:

```python
driver.run_session(upstream_root=simulator_root, project_root=project_root,
                   results_root=run_root,
                   launch_cutoff_seconds=remaining_launch_seconds,
                   command_runner=direct_evaluator)
```

- [ ] Pilot uses `run_failure_search._write_config` for two separate one-episode
  stages: task/state 0, seed7, nominal and rectangle(.5,0,.375,.375), full recording.
  Parse real aggregates with existing helpers. Missing MP4 or trace is partial
  infrastructure evidence. Do not assert that the masked outcome must fail.
- [ ] Start the model in its own group with pinned checkpoint validation;
  bound startup and require a WebSocket handshake. Give each evaluator a timeout
  within the remaining whole-workload deadline. TERM closes both groups. Model
  exit/readiness failure blocks evaluation. No auto retry or parallel workers.
- [ ] Keep each child environment separate (`PYTHONPATH` for project src and
  installed simulator only; model checkout source only for the model process).
  Record actual versions, refs, timings and backend in a new provenance sidecar.
- [ ] Export closed local files to fresh run-specific persistent destination.
  Reject symlinks, path escape, preexisting destinations and private-key/token
  files. Copy to unique staging names; publish file hash manifest last. Simulate
  copy failure and verify no successful final manifest. Preserve partial evidence
  as explicitly partial after verified cleanup, never copy a live recording DB.
- [ ] Test all modes with injected fixtures, no GPU/provider/secrets; prove the
  original driver defaults and algorithms are unchanged. Add actual interrupted
  process/export acceptance under POSIX.
- [ ] Commit `feat(jobs): run sequential diagnostics with durable evidence export`.
- [ ] Independent spec then quality reviews before root integration.

### Task 3: Image and prepare-only Job configuration — green/amber

Files: create `deploy/serverless/Dockerfile`, `deploy/serverless/Dockerfile.dockerignore`,
`configs/serverless-job.example.json`, `scripts/prepare_serverless_job.py`,
`tests/test_serverless_job_config.py`, `docs/setup/serverless-jobs.md`.

- [ ] Derive from the exact existing LIBERO digest; reset inherited entrypoint
  and shell, preserve its simulator environment/source. Clone model bridge at
  its exact SHA to `/opt/upstream`, build a separate Python3.12 model environment
  from its pinned LeRobot source. Follow probe evidence for dependencies; record
  installed packages and test torch/torchcodec compatibility. No new policy.
- [ ] Copy only `src`, `scripts`, `configs`, required project metadata and license.
  Build context explicitly excludes `.git`, `.env*`, artifacts, keys, model-cache
  and datasets. Use the Dockerfile-specific ignore filename so repository-root
  context builds actually apply it; a nested ordinary `.dockerignore` is ignored.
  Do not install project dependencies into the untouched simulator
  just to import our adapter; provide source paths explicitly.
- [ ] Add failing pure preparation tests. `prepare(config)` returns an argv list
  beginning `nebius ai job create`; never invokes subprocess/network. Require
  immutable image digest, one-GPU preset, safe run name, explicit subnet and
  private bucket, one-hour provider timeout, restart-policy never and selectors
  rather than secret values. Inject runtime JSON as a read-only file.
- [ ] Example file contains illustrative selectors/IDs only, clearly invalid
  for submission until configured. Default is prepare-only; no `--execute` path.
  Document exact create/get/logs/cancel/download workflow using installed CLI help,
  no guessed REST schema. Store actual Job ID locally and resume observing it;
  never recreate on an ambiguous submit response.
- [ ] Build locally, inspect both Python environments, direct evaluator help,
  project adapter imports, model imports and absence of baked secrets/weights.
  GPU/renderer/inference remain explicitly unverified until the paid pilot.
- [ ] Run focused tests and full suite before `feat(jobs): package configurable serverless runtime`.
- [ ] Independent spec then quality review; root alone publishes an approved
  image to a private registry after pricing/retention gates.

### Task 4: Live pilot and recovery — red cap, then bounded amber

Root owns all commands and temporary resources. The fresh US$3 allowance is
specific to this one-hour single-L40S validation; no earlier cap is reusable.

- [ ] Read-only: account/project/region active state, Serverless support, GPU quota,
  exact-shape capacity, live resource/disk/bucket/registry rates, actual available
  balance and expiry. Token Factory balance is not AI Cloud balance.
- [ ] Propose one numeric all-in cap, selected one-GPU shape, maximum allocation
  duration and storage-retention deadline; wait for approval before provision,
  registry publication or Job submission. Include image pull/model download/startup,
  temporary storage and applicable tax, not just episode wall time.
  Jethro approved US$3 / one hour / 24-hour output retention on October 6;
  do not request it again unless a resource/price/scope change exceeds it.
- [ ] Configure secrets locally/SecretStash without asking for token text in chat.
  Create only approved private resources. Prepare one stable configuration and
  record its hash. Arm a workstation exact-Job cancel-and-poll deadline before
  submission; the provider one-hour timeout and container deadline are backups.
- [ ] Submit once; persist exact Job identity. Recover uncertain submission by
  unique name lookup before any retry. No automatic resubmission or second test.
- [ ] Recover logs, videos, traces, aggregates and provenance into a new ignored
  artifacts directory. Verify manifest hashes and actual readable media/JSONL.
  Observe the Job terminal state; cancel/poll if required. Retain only resources
  within approved duration; deletion needs explicit target/approval checks.
- [ ] Show new paired recordings in the existing viewer. Compare outcomes honestly
  without relabeling historical cases. Any failed pilot yields partial evidence,
  cause and remaining work rather than a migration-complete claim.
- [ ] Update `FEEDBACK.md`, `docs/dev-log.md`, root roadmap and existing handoff
  files with observed behavior, estimates versus posted billing, and setup/recovery
  commands. Commit `docs(jobs): record serverless validation and recovery`.

## Completion boundary

Migration is complete only after local reviews/image validation and one live Job
recovers complete fresh robot evidence with a terminal resource state. It makes
the existing serial diagnostic workloads deployable; it does not complete M5B,
prove a new HPC result, improve Nemotron semantic grounding, or confer public
submission readiness. Preserve all old evidence throughout.
