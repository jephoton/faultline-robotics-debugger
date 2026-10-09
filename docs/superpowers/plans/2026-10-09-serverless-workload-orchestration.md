# Serverless Workload Orchestration Implementation Plan

> **For agentic workers:** Use subagent-driven-development, with independent
> spec then quality review before integration. Steps use checkboxes.

**Goal:** Join the approved serial drivers to a bounded model/evaluator/export
lifecycle through injectable interfaces before wiring the production model.

**Architecture:** A workload owns one model lifetime and invokes at most one
evaluator at a time. It computes remaining time before every launch, stops
dispatch on infrastructure trouble, closes the model, and only then exports
closed evidence. Existing discovery/grid/reduction algorithms stay unchanged.

**Tech Stack:** Python standard library, existing driver callbacks, unittest
fixtures, JSON evidence and the reviewed closed-file exporter.

## Scope, autonomy and ownership

This is the next green/amber portion of Task 2 in the approved October 6
migration plan. It introduces no new cloud topology, policy, perturbation,
algorithm or experiment. Production model startup/handshake, signal/deadline
enforcement, CLI/image wiring and live acceptance remain separate requirements;
this injectable layer alone must not be called a runnable Serverless product.

One smaller builder (`gpt-5.6-sol`, medium; Terra unavailable) owns only new
`src/robot_debug/job_workload.py` and `tests/test_serverless_workload.py` in a
clean attached worktree. Root owns this plan, integration, provider state and
documentation. Map: orchestration builder || root dependency/image inspection
-> spec review -> quality review -> root tests/integration. No overlapping file
ownership. Root supplies the full task text at handoff. No cloud/API call,
model download, secret access, image publication or external-state replay.

## Interfaces and invariants

```python
@dataclass(frozen=True)
class WorkloadPaths:
    project_root: Path
    upstream_root: Path
    work_root: Path
    export_root: Path

def run_workload(config, *, paths, model_factory, evaluator_factory,
                 exporter=export_closed_evidence, clock=time.monotonic):
    ...
```

Use `validate_workload_config` unchanged: exactly schema_version, mode, run_id,
deadline_seconds. Roots are trusted wiring, not arbitrary workload JSON fields.
Require existing ordinary link-free roots; reject overlapping work/export roots
and any existing `root/run_id` destination before starting a model. Create the
new local run directory exclusively. Do not erase or resume existing runs.

Factory contracts, tested with fixtures rather than a GPU:

```python
model = model_factory(log_root=run_root / 'logs')
model.start()
model.wait_ready(deadline=absolute_launch_deadline)
model.check_alive()  # raises InfrastructureError if dead
model.close()        # returns only after confirmed group absence; otherwise raises
runner = evaluator_factory(timeout_seconds=remaining_launch_seconds,
                           log_root=run_root / 'logs')
runner(command, cwd=paths.upstream_root, check=False)
exporter(run_root, paths.export_root / config['run_id'],
         status='complete' or 'partial', cleanup_confirmed=True)
```

The model factory must not start anything as a side effect. `close` must be
attempted even if `start`, readiness or dispatch fails. Its successful return
is the injected contract, not independent evidence of real process cleanup.
Production wiring must supply real bounded implementations before a live run.

Set the absolute launch deadline once at entry: start+deadline_seconds-14.
The 14-second reserve covers the approved maximum two TERM/KILL cleanup windows,
not export duration. A nonpositive remaining interval launches nothing and
records deadline exhaustion. Never reset the whole-workload clock after startup.
Check clock and model liveness before and after each evaluator call. Do not
create a runner when no time remains. Production blocking calls and export still
need their real deadline/TERM enforcement; injected tests do not prove that.

For search/grid/reduce invoke the corresponding existing `run_session` with
`results_root=run_root`, a launch cutoff equal to the current remaining interval,
the bounded callback and the supplied monotonic_clock. Import:
`scripts.run_failure_search`, `scripts.run_position_grid_search`, and
`scripts.run_failure_reduction`. Do not edit these files, constants or algorithms.
An infrastructure error must latch permanently: if a driver catches it and
asks to launch again, the callback refuses without creating another evaluator.

For pilot, generate two one-episode configs using search `_write_config`:
task 0, state/episode 0, seed 7; nominal then rectangle x=.5,y=0,w=.375,h=.375.
Each config uses full step/video recording. Use the existing aggregate parser
with expected_count=1. A valid masked success is allowed; this is deployment
validation, not a requirement that every masked run fail.

After every successful evaluator return, verify the output directory from its
generated YAML (use the project's installed PyYAML dependency) has one valid
aggregate and a unique nonempty matching MP4/JSONL per expected episode. Reuse
ArtifactCatalog for pairing where possible; do not accept a different episode's
media. Infrastructure-classified episodes, nonzero exit, missing/ambiguous/empty
media, malformed aggregate, evaluator exception or model death latch partial
infrastructure status and prevent further physical launches. Do not certify
MP4 decoding or simulator replay from these file checks.

Persist `workload_summary.json` with schema_version=1, backend='nebius-serverless',
mode, run_id, status, stop_reason (fixed codes only), elapsed_seconds and pilot
outcomes when present. Use safe fixed error codes, never exception text or
environment dumps. Code choices: completed, deadline_exhausted,
model_start_failed, readiness_failed, model_died, evaluator_failed,
invalid_evidence, workload_failed, interrupted, cleanup_unconfirmed.
This backend field labels intended execution wiring; fixture runs are explicitly
synthetic and must not be represented as Nebius measurements.

Export once after model closure, as complete only if the workload and recording
checks completed without infrastructure trouble; otherwise partial. An ordinary
robot-policy failure is a valid outcome, not infrastructure failure. If cleanup
is uncertain, write local cleanup_unconfirmed status and do not call exporter.
Export failure propagates and cannot return a successful report. Preserve local
evidence. On KeyboardInterrupt, attempt closure and partial export only after
confirmed cleanup, then re-raise; restore no caller signal handlers in this
layer. SIGTERM production handling belongs to the real runtime wiring.

## TDD tasks and conventional commits

- [ ] Write a failing nominal+masked pilot fixture with actual temporary YAML,
  aggregate and paired MP4/JSONL files. Fake model records start/ready/check/close;
  fake evaluator writes files only. Assert serial ordering and closure before
  exporter, two outcomes and masked success acceptance. No subprocess/network.

```python
report = run_workload(
    {'schema_version': 1, 'mode': 'pilot', 'run_id': 'fixture',
     'deadline_seconds': 120},
    paths=paths, model_factory=model_factory,
    evaluator_factory=evaluator_factory, clock=clock)
self.assertEqual(report['status'], 'complete')
self.assertEqual(events[-2:], ['model-close', 'export'])
```

- [ ] Run `PYTHONPATH=src python -B -m unittest tests.test_serverless_workload -v`;
  confirm missing-module failure before implementing the interfaces and pilot.
- [ ] Add RED cases for invalid config/path/preexisting run, model startup or
  readiness failure, model death before/after evaluation, deadline spent on
  startup, timeout/nonzero exit, missing/wrong/ambiguous/empty media, invalid
  aggregates and cleanup failure (export must not be called).
- [ ] Add fake-clock tests: timeout supplied to the second runner decreases;
  after cutoff no runner is constructed; a driver swallowing a first error
  still cannot physically launch another evaluator. Run and confirm failures.
- [ ] Implement safe fixed-code summaries and closure/export ordering. Test
  actual exporter manifests for complete and partial fixture runs, including
  source preservation and propagation of export failures. Test KeyboardInterrupt
  closes/exports then propagates, and cleanup uncertainty blocks export.
- [ ] Exercise search/grid/reduce with monkeypatched `run_session` seams to
  assert exact existing driver/kwargs selection; preserve defaults/algorithms.
  Rerun the existing driver suites with the new tests.
- [ ] Run focused tests under Windows Python 3.11 and WSL, compile imports under
  the pinned Python 3.8 simulator image when Docker is healthy, and diff check.
- [ ] Commit only owned files:
  `feat(jobs): orchestrate serial workloads with closed evidence export`.
- [ ] Independent spec then quality review. Root reruns tests and integrates
  only approved changes; update current handoff with exact remaining boundaries.

## Acceptance boundary

This closes the injectable dispatch/cleanup/export portion, not the full
migration. Model group startup, genuine WebSocket upgrade, pinned model caches,
actual package/image provenance, real enforced deadlines/signals, final CLI,
image build and one approved GPU Job remain. Historical evidence and cases stay
unchanged. No new provider spending is authorized by this plan.
