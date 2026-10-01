# Current project state

> Generated current-state context. Update after material implementation,
> architecture, workflow, or risk changes.

## Completed evidence

- The nominal baseline passed 20/20 episodes.
- Centered opaque-square occlusions through 25% image area succeeded.
- The fixed-area position grid found a reproducible failure at normalized
  `x=0.50, y=0.00`: discovery plus 5/5 replays failed, while the nominal
  sentinel and 5/5 fresh nominal controls succeeded.
- The September 27 M4 session reduced the 25%-area parent to a certified
  14.0625%-area rectangle at `x=0.625, y=0, width=0.375, height=0.375`.
  Its accepted cases failed 4/4, while five fresh nominal controls succeeded.
  The 12-candidate-attempt budget ended before proving a minimum.
- The ignored local M4 artifact tree contains 22 aggregates, traces, MP4s,
  SQLite recordings, the summary, and the replay manifest.

## Current implementation

- The read-only viewer runs from `src/robot_debug/viewer/` and scans artifacts
  on each catalog request.
- The viewer deduplicates copied aggregates, prefers media-bearing records,
  and displays accepted reduction lineage. Its M4 catalog indexes all 22
  episodes with no missing media or warnings.
- M3 local work is integrated into `main`; publication remains a separate
  user-controlled action. The fixed 16-item manifest, bounded 1/2/4-worker
  scheduler, evidence validation, fail-closed comparison reporter,
  process-group containment, and durable per-case attempt ledger are
  implemented. Exact evaluator launch identity is written before waiting, and
  safe partial sessions can resume only proven-prepared cases. Windows Python
  3.11 passed 212 tests (2 POSIX-only skips); the focused WSL signal/driver
  suites passed 57 tests.
  A separately labeled two-case pilot command and exact-VM workstation
  watchdog are also implemented. The pilot requires trace, MP4, and expected
  nominal/failure outcomes; the benchmark reporter rejects pilot summaries.
  The guard arms while the VM is stopped, keeps an immutable exact target,
  bounds individual CLI calls, and reports unconfirmed stops as errors.
  Integrated Windows Python 3.11 passed 242 tests (3 POSIX-only skips), and
  focused WSL driver/lifecycle tests passed 66. The September 29 two-episode
  Nebius pilot passed: one nominal success and one reduced-mask failure, both
  with valid traces and videos. The separate full M3 comparison then completed
  48/48 valid episodes with no outcome drift. Warm 1/2/4-worker times were
  610.247/310.472/164.256 seconds (1.000/1.966/3.715× speedup). All 48
  MP4s and traces are in ignored local artifacts and visible in the viewer.
  See `docs/experiments/m3-parallel.md`.
- The accepted one-GPU adaptive diagnostic loop is integrated locally in
  `main`, not yet a live end-to-end cloud comparison.
  It combines the prior eight-position grid, five-replay confirmation, M4
  reduction, and nominal controls with the M3 durable scheduler and 1/2/4
  worker selector. The reporter replays saved ordered results, separates
  speculative extra attempts from outcome drift, and refuses speedup claims
  from fake runs. Windows Python 3.11 passed 298 tests (four POSIX skips);
  focused WSL passed 92, including a real SIGTERM during an active evaluator.
  Two inspected synthetic sessions reached the same certified rectangle.

## Next material decision

Jethro redirected M3's next experiment toward portfolio-first HPC: schedule
distinct LIBERO Object task-level find → confirm → reduce jobs across one GPU,
starting with the existing occlusion family. The decision is recorded in
`docs/decisions/0009-portfolio-first-hpc.md`; the design spec is approved and
`docs/superpowers/plans/2026-09-30-m3-multi-job-portfolio.md` scopes local
implementation. M5 now includes a proposed portfolio overview in the viewer.
M6 explicitly adds another perturbation family and exploration of
other LIBERO suites. The former single-loop US$4/90-minute live proposal is
paused, not authorized. The portfolio core is locally implemented; no live
portfolio run has begun.
The September 29 read-only preflight found a US$10.42 balance, the exact VM
stopped, the same US$1.7468/hour pre-tax VM rate, and zero regular launch
slots for its exact L40S shape (low chance). Refresh all of this and verify
the watchdog before any new numeric-cap request or VM start. The local code
reports only warm diagnostic estimates; VM allocation/startup and posted
billing are not yet captured. Do not call the fixed-work M3 3.715× throughput
result an end-to-end adaptive-loop speedup. The current viewer has not been
wired to these new session summaries; it still displays the prior M2/M4 cases
and fixed M3 comparison.

### Portfolio implementation checkpoint

The local portfolio implementation is on isolated branch `codex/m3-portfolio`.
It adds a frozen three-job manifest, an exact task-ID filter in the local
`DiagnosticLIBEROBenchmark`, and config-writer support for an explicit task
and seed. The pinned upstream orchestrator otherwise truncates only a task
prefix with `max_tasks`; `episode_indices` select reset states rather than
tasks. Local fake-upstream adapter and config tests pass, but real LIBERO
task IDs/instructions beyond task 0 and live selector compatibility remain
unverified. Jethro approved the narrow adapter and the work-conserving
round-robin scheduler rule. Its pure policy is implemented and independently
reviewed; a fairness bug under changing task readiness was caught and fixed
before runner integration. The runner supplies all frozen manifest job keys,
including paused/non-ready jobs, each wave. The new CLI runs separate
sequential-job and adaptive-portfolio sessions through one durable shared
evaluator queue. Each job has its own diagnostic flow and evidence; a shared
ledger records physical launch attempts. The report replays saved flows,
reconciles wave attempts, and withholds warm speedup unless both sessions are
complete, live, budget-matched, and outcome-consistent. Two fresh synthetic
CLI sessions passed a paired smoke test without a speedup claim. Windows
Python 3.11 passed 344 tests (four POSIX-only skips); focused WSL lifecycle
and driver tests passed 66. An independent reviewer approved the report
claim guard. Jethro accepted task IDs `(0, 1, 2)` as nominal-screening
candidates; their runtime catalog and nominal validity are still unverified.
The [bounded screening plan](../superpowers/plans/2026-09-30-m3-three-task-nominal-screen.md)
received a US$3/60-minute approval. Its September 30 first start and a later
separately approved same-cap retry were both blocked before guest access by
`NotEnoughResources`, despite one `LOW`-availability slot in capacity advice.
No task episode ran, so IDs 1 and 2 remain unscreened. The VM is confirmed
`STOPPED`; temporary SSH ingress and both OS-owned guards were removed after
verification. Jethro waived the fresh balance check for the retry, so the
prior US$9.96 reading is not a current balance. The then-open resource choice
was superseded by the separate H100 decision below. Read-only diagnosis found two scheduler-level capacity timeouts on an
unchanged VM, not a guest/model/runner error; the existing platform is
immutable and its managed boot disk must not be lost during migration. H100
has stronger advised availability but a higher hourly rate and untested
runtime compatibility. See
[`m3-three-task-screen.md`](../experiments/m3-three-task-screen.md).
Jethro chose a snapshot-based **separate H100 VM** on September 30.
[ADR 0010](../decisions/0010-h100-snapshot-migration.md) and the
[H100 screen plan](../superpowers/plans/2026-09-30-m3-h100-snapshot-screen.md)
preserve the original L40S VM/disk. The subsequent approved attempt and its
cleanup are recorded below; its one-start authority is now exhausted.
The September 30 H100 read-only preflight found the original VM `STOPPED`, its
200-GiB disk `READY`, and H100 on-demand advice `HIGH`/`MEDIUM` across four
fabrics. The console balance was US$9.89, and detailed Nebius pricing lists
US$0.071/GiB/730h for snapshots. A conservative US$7.50 total cap for one
60-minute H100 start and at most 24 hours of all three 200-GiB storage objects
was proposed on September 30. Jethro approved it on October 1, including
cleanup of only the new clone/managed disk and snapshot. Fresh balance was
US$9.55 and H100 compute was US$4.50/hour pre-tax; no expiry was displayed.
The snapshot-backed H100 clone reached `RUNNING`, but SSH and a Windows
TCP/22 probe timed out despite the correct ready narrow ingress rule.
Serial logs confirmed new guest network identity, SSH socket listening,
cloud-init completion, and a shutdown backup; the remaining access cause
is unresolved. Fabric Manager also failed at boot, with inference impact
untested. No guest source transfer or robot episode occurred. The clone was
stopped early and independently verified `STOPPED`; local serial/lifecycle
evidence is retained. Cleanup is verified: temporary clone/managed disk,
snapshot, ingress rule, and scheduled guard are removed; only the original
stopped VM and ready disk remain.
The original L40S VM remains stopped and untouched. No automatic paid retry
is authorized; investigate access before proposing another bounded attempt.
The manifest rejects unsupported family/model labels, but live preflight
must independently verify the model server actually loaded the pinned
checkpoint and revision.
No portfolio episode has run; provider billing for these attempts has not
yet posted, and the retained disk remains billable.

M4's bounded live run and evidence validation are complete; details are in
`docs/experiments/m4-reducer.md`. Jethro accepted the M3 equal-work
1/2/4-worker design on one GPU VM with a shared GR00T server, using fixed
repeats of the real M4 case. The M3 local implementation now uses the accepted
durable attempt-ownership design, exact launch-identity sidecars, and a
fail-closed resume lease. Whole-branch review and merged-result tests passed.
The 2-worker pilot and separately approved US$5/two-hour 1/2/4 comparison are
complete. The VM was independently confirmed stopped after evidence copy,
and the temporary SSH ingress rule was removed. The first plain detached
watchdog disappeared without a terminal log; the full run instead used an
OS-managed scheduled task for the same exact-VM guard, plus guest shutdown.
The scheduled task was removed after stop verification. This does not prove
the guard survives workstation sleep, lost network, or expired auth. CLI
authentication did expire during one short start, which was stopped before
the clean full run. The calculator reported $1.7468/hour for the VM and
$0.0194444/hour for disk, pre-tax, on September 29. Operation bounds give
an estimated $1.1038 compute including assumed 9% tax across both VM-on
intervals, before separate disk accrual; posted billing is pending. The root
`FEEDBACK.md` tracks submission feedback by actual tool.

The M4 reducer kernel's September 21 external-provider handoff is historical
provenance only. Jethro has retired that provider from future routing after
integration issues. See the archived handoff under `docs/codex-handoff/tasks/`
only when investigating M4 history; do not treat it as an active instruction.

## Known limitations and risks

- The WSL `.venv` may lack NumPy for the complete suite. The focused WSL
  lifecycle and driver tests, including real process signals, have passed;
  the complete suite passes with Windows Python 3.11.
- Experiment evidence is ignored and local; do not infer that it is published
  or durable off-machine.
- The retained 200 GiB boot disk continues to accrue storage cost while the VM
  is stopped. Decide storage/teardown within the pilot's approved 24-hour
  retention window; preserve any needed model cache and copied evidence
  explicitly. Both pilot and comparison temporary SSH ingress rules were
  removed.
- The position failure is empirical and spatially specific, not a causal or
  universal robustness claim.
- The M3 ledger persists `prepared`, `submitting_unknown`, `active`,
  `completing_pending`, and `terminal` per case; results and counts are derived
  from that authority. An interrupted or late completion is not counted as a
  valid replay. Resume refuses uncertain ownership, nonvalid terminal results,
  stale prepared-case artifacts, and concurrent invocations. Resumed modes
  cannot enter the throughput comparison. Process-group containment was tested
  with a delayed POSIX child, but local tests cannot prove a Docker daemon has
  no outstanding request. An absent-container check is only a local
  observation. After any uncertainty, stop and verify the exact VM before
  another mode. A stuck thread can outlive the CLI's partial-summary deadline;
  the independent VM watchdog is still the cost boundary.
