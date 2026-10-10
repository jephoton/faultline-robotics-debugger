# Serverless Preflight Deadline Repair Plan

**Goal:** Repair two reproduced deadline regressions in Claude's Object Storage
recovery without changing model pins, evaluator algorithms or deployment shape.

**Architecture:** Pass one original absolute monotonic deadline from entrypoint
through workload orchestration. Run the existing export probe in a separately
owned, bounded CPU subprocess so a stalled bucket mount prevents model startup.
Reuse the reviewed process-group cleanup; no threads pretending to cancel I/O.

**Scope:** Green/amber within the accepted finite Job design. No Job creation,
new provider call, package installation, credentials, image publishing or GPU.
Root owns docs, integration, Docker/cloud and spending. A smaller capable builder
owns only job_entry.py, job_workload.py, test_job_entry.py and
test_serverless_workload.py in a clean existing attached worktree. Map:
deadline/probe builder || root read-only pilot evidence recovery -> independent
spec/quality review -> root tests -> image rebuild/probes. Do not edit exporter,
model/process kernels, historical results or the prepared failed-Job config.

## Required repair

- [ ] Reproduce the review's integration regression before fixing it: entrypoint
  starts at clock100 with duration2400; preflight advances to400; real workload
  and injected model must receive readiness deadline2486, not2786. Keep the
  original configuration unchanged and preserve intended duration in records.
- [ ] Add optional trusted `absolute_deadline=None` to `run_workload`. Validate
  an explicit value as an ordinary finite number, not bool; never permit it to
  extend `started + config['deadline_seconds']`. The launch cutoff is
  `min(started + duration, absolute_deadline) - 14` when supplied; existing direct
  callers retain their prior duration behavior. Passed deadlines already spent
  produce partial/deadline_exhausted without creating any evaluator or model.
  Entry `main` passes its original deadline by this keyword, and the factory
  retains the same original deadline. No clock/deadline reset after preflight.
- [ ] Retain `export_preflight(layout, run_id)` as the child-side plain operation.
  Add a bounded parent helper using the simulator `sys.executable`, shell=False,
  start_new_session=True, DEVNULL stdin and exclusive file-backed local logs.
  Invoke Python with a fixed `-c` program importing this helper from the trusted
  project src; serialize only trusted layout paths and validated run_id as a
  JSON argv argument. Never transmit environment secrets into the probe, never
  print argv/env/log content, and do not expose this as an arbitrary command API.
- [ ] Use a 30-second probe cap further shortened by remaining original budget
  minus the existing 14-second cleanup reserve. Recheck remaining time before
  spawn and before waiting. No spawn when remaining <=0. On timeout, exception,
  SIGINT/SIGTERM or normal child exit, call close_owned_process_group and prove
  absence before continuing. Nonzero, timeout or cleanup uncertainty is a fixed
  runtime/preflight failure, exit3; SIGTERM retains143 after confirmed cleanup.
  Preflight success alone is not remote durability proof or model readiness.
- [ ] Keep unique remote probe directories and the SIGTERM handler installed
  before the parent helper. Keep downloader rehash as authoritative durability
  acceptance; do not restore rename or destination inode assumptions.
- [ ] Test actual POSIX child timeout and orphan cleanup using CPU fixtures,
  plus SIGTERM during preflight, expired budget/no spawn, nonzero exit, unique
  paths, no model creation after a failed probe, and deadline forwarding.
  Use the existing fixture subreaper/owned-group teardown so tests cannot leave
  children. Inject only subprocess fixture argv at the low-level seam, never
  production test-only behavior. Existing exporter/error/privacy tests must pass.

## Checks and commits

```powershell
$env:PYTHONPATH='src'
C:/Windows/py.exe -3.11 -B -m unittest tests.test_job_entry tests.test_serverless_workload -v
```

Run the same modules under WSL with PYTHONPATH=src, then the existing
test_job_process/test_job_model/test_job_runtime suites. Actual POSIX tests are
required; Windows skips are not lifecycle proof. Check Python3.8 grammar and
git diff --check. Commit separate coherent fixes:
`fix(jobs): preserve absolute deadline across export preflight` and
`fix(jobs): bound export preflight process lifetime`. Independent review must
rerun the original clock reproduction and actual timeout fixtures before root
integration. Root reruns full tests and updates the handoff/dev log/feedback.

## Next gate

The currently pushed repaired image at c91383c still has these deadline bugs.
After integration root rebuilds cached application layers and checks imports,
exit codes and preflight fixtures without a GPU. A further paid Job is a new
attempt: the original single-Job approval does not silently authorize it. Obtain
an explicit retry cap and fresh resource checks before submission. Preserve the
failed Job's exact identity and partial objects; never resubmit under its name.
