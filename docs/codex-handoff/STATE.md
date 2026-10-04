# Current project state

> Generated current-state context. Update after material implementation,
> architecture, workflow, or risk changes.

## Expanded M3 frozen as optional stretch — October 2

Jethro accepted freezing expanded M3 and keeping it as a stretch goal if time
and interest permit; see `docs/decisions/0011-freeze-expanded-m3.md`. Do not
resume the launcher implementation, portfolio comparison or associated UI
automatically. Existing run caps are exhausted; future paid work requires fresh
preflight and approval. Preserve completed fixed-replay HPC evidence, integrated
scheduler/guest code and unfinished host work. No deletion or formal-methods
architecture has been approved. The core product prioritizes the robotics
failure-to-regression workflow; planning its next bounded step is next, with
project-name brainstorming still queued. This overrides older execution
instructions below. The portfolio overview is optional, not a core M5 gate.

## M5A complete; next gates are M5B/C — October 4

The scope-approved `docs/superpowers/plans/2026-10-03-m5-case-workbench.md` divides M5
into A: offline case inspection/export on existing evidence; B: one externally
supplied, genuinely restorable simulation episode; C: grounded Nemotron
explanations. Jethro accepted the read-only-viewer/CLI boundary. An isolated
Luna builder completed the approved task-local media fix, integrated as
`1d79c01` after independent spec and quality review. IDs 0/1/2 all resolve saved
screen video/trace; M4 retains 22/22 videos and traces with no warnings. Root prepared
`docs/superpowers/specs/2026-10-03-m5-case-contract-design.md` for the exact A1
review gate; Jethro approved it with "go". The bounded schema-kernel plan
`docs/superpowers/plans/2026-10-03-m5-case-schema.md` was implemented by a balanced
smaller agent in isolated `codex/m5-case-schema` and integrated as `46a3419`/
`d29f87a` after independent spec/quality review. `cases.py` validates structure,
computes deterministic identity and lists missing recipe prerequisites; it
does not inspect files or certify imported evidence. Ten focused tests pass.
Source reconciliation, persistence and CLI are integrated on main as `4851908`
through `9c87294` after independent spec/quality repair cycles. Fresh integrated
suite: 454 tests, four skips. Root registered the saved M4 case in ignored
`artifacts/cases`, matched all 22 episode IDs and videos/traces, exported metadata
to `artifacts/m5-export-20261003-reviewed` and reimported it in a separate ignored
workspace. Summary/replay/aggregate hashes match the pre-import baseline.
The case is inspectable; checkpoint/upstream-harness/image pins are missing;
exact aggregate-linked historical policy identity is absent; fresh replay is
unverified. Do not fabricate those pins or upgrade imported claims.
The viewer journey is integrated as `01c8ea2`, `557c00b`, and `2e2e125` after
independent spec and quality reviews. It exposes GET-only case/readiness/recipe
APIs, exact-ID evidence scoping, four independent capability labels, selected
reduction lineage and a static CLI export template. Technical details collapse
to keep paired videos prominent. Real browser checks verified both recordings,
linked playback, traces, keyboard focus and refresh stability; 375/768/1440px
layouts have equal evidence panels and no horizontal overflow. The operator
walkthrough is `docs/setup/case-workbench.md`. The owned main viewer runs at
http://127.0.0.1:8765/ with ignored `artifacts/cases` registrations.
M5A is complete; full M5 is not. Two read-only
feasibility scouts completed B/C research; no external sample acquired or
provider request sent. Specific sample-acquisition and Nemotron model/data/cap
decisions were queued asynchronously while offline implementation continued.
CLI-first and independent capabilities are recorded in ADRs 0012/0013. Exact
external format, simulator restore adapter, hosted model/input, data transfer
and live budgets remain gated. M3's unfinished launcher is not a dependency.

Fresh integrated Windows Python 3.11 suite: 468 tests run successfully, four known
platform skips. Safety-test fixtures print simulated stop/argument errors;
this test run did not access or start cloud resources.

## Completed evidence

Unblocked M5C preparation: the proposed offline packet/report contract is
`docs/superpowers/specs/2026-10-04-m5-offline-explanation-contract-design.md`.
It strips arbitrary case strings and paths, keeps reported raw/gate outcomes
separate, validates cited episode IDs and preserves deterministic summaries
when supplied interpretations fail. No API client, key loader or provider call
is included. Await Jethro's contract review before writing its detailed smaller-
model implementation plan; credentials do not block that offline increment.

October 4 M5 follow-up: ADR 0014 accepts the 744.1 MiB sample acquisition and
text-only Nano Nemotron pilot (ten calls / US$0.02 maximum). Sample bytes/hash
verified in ignored `artifacts/m5-sample-preflight`; actual demo_0 has 148
steps, 110-value simulator states, matching init_state, model XML and paired
128px camera data. BDDL content absent; XML assets/runtime compatibility are
not self-contained or exercised. See the new external-sample research note.
The isolated h5py environment needed pip truststore, with TLS kept enabled.
No relevant inference key is configured in process/user/machine variables or
a repo env file; an async request asks Jethro to save NEBIUS_API_KEY in ignored
root .env and report Token Factory balance/expiry. Never print or commit it.
Public cookbook lowercase API identifier and regional base differ from older
examples; verify exact account catalog before requests. No inference or VM
start occurred. Next is adapter design/client planning, not live replay.

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
- The October 1 hotspot H100 screen passed one nominal episode each for
  LIBERO Object IDs 0/1/2 (alphabet soup, cream cheese, salad dressing), seed 7,
  reset index 0. Exactly three valid attempts, no invalid/uncertain attempts,
  and three videos/traces were independently verified. This is compatibility
  evidence, not a reliability or diagnostic-speedup result.

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
full diagnostic portfolio comparison has begun. The nominal-only screen is
complete; a separately scoped comparison remains the next material decision.
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
task IDs/instructions beyond task 0 and live selector compatibility were
then unverified; the later live nominal screen verified task mapping, not
multi-worker performance. Jethro approved the narrow adapter and the work-conserving
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
candidates; their runtime catalog and one nominal episode each were verified
in the later hotspot retry below, not during this local checkpoint.
The [bounded screening plan](../superpowers/plans/2026-09-30-m3-three-task-nominal-screen.md)
received a US$3/60-minute approval. Its September 30 first start and a later
separately approved same-cap retry were both blocked before guest access by
`NotEnoughResources`, despite one `LOW`-availability slot in capacity advice.
No task episode ran in those two attempts. The VM was confirmed
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
was unresolved in that attempt. Fabric Manager also failed at boot, with
inference impact then untested. No guest source transfer or robot episode occurred. The clone was
stopped early and independently verified `STOPPED`; local serial/lifecycle
evidence is retained. Cleanup is verified: temporary clone/managed disk,
snapshot, ingress rule, and scheduled guard are removed; only the original
stopped VM and ready disk remain.
The original L40S VM remains stopped and untouched. That one-start authority
was exhausted; the subsequent separately approved retry is recorded below.
After switching to a phone hotspot, credential-free probes received SSH
banners from GitHub on ports 22 and 443. This confirms outbound SSH to those
endpoints only, not Nebius connectivity or hotel filtering. The active egress
address changed; refresh the narrow ingress rule for any future approved run.
The [hotspot retry plan](../superpowers/plans/2026-10-01-m3-hotspot-h100-retry.md)
received explicit US$6 total/45-minute/one-start approval and completed.
Fresh balance was US$9.53 with no displayed expiry. Source `797df18` repaired
the actual CLI manifest mapping and added an explicit adaptive worker cap;
nominal-first admission applies only to explicitly capped adaptive mode.
The focused suites passed 34 tests; Windows Python 3.11 passed 349 with four
platform skips. The live screen used cap 1 and exactly three physical attempts.
SSH succeeded shortly after boot on the hotspot. H100 CUDA computation,
runtime task catalog, cached revision-resolution log, and model-server
checkpoint-ID loading log were verified; the server did not separately log
a loaded revision hash.
Fabric Manager remained failed on the Pre-NVL5/NVSwitch warning path; actual
single-GPU inference worked, without a driver repair or universal claim.
All three nominal tasks succeeded. Partial exit `shared_budget_exhausted`,
`certified=false` is expected: no search, repeats, or reduction were allowed.
Warm time was 93.4031 seconds, estimated US$0.116754 pre-tax. Start-to-stop
operation bounds were 09:21:36–09:38:07 UTC, about US$1.35 compute including
assumed tax before storage, not posted billing. Evidence is local/ignored
under `artifacts/m3-hotspot-screen-live-20261001/`.
Cleanup is independently verified: temporary clone/managed disk, snapshot,
ingress, and guard are removed; only original stopped VM/ready disk remain.
The retry authority is exhausted. Next: plan separately capped repeatability
controls, H100 worker calibration, and budget-matched sequential/adaptive
task-level diagnosis. No additional paid start is authorized. Do not infer
H100 worker performance from historical L40S timings. Posted billing remains
unreconciled and the original disk continues accruing storage charges.

Jethro clarified that autonomous execution should continue through the full
sequential/adaptive comparison, not end at media packaging for the nominal
screen. The [new execution plan](../superpowers/plans/2026-10-01-m3-live-portfolio-comparison.md)
preserves the working H100 stack and proposes US$8 total/90 minutes/one start,
with identical per-mode bounds and adaptive cap 2. Jethro approved US$8/90
minutes/one start and temporary-resource cleanup. This allocation was interrupted
during startup before guest execution: zero comparison episodes or new media.
The watchdog confirmed STOPPED within 90 minutes; temporary clone/managed disk,
snapshot, ingress rule and scheduled guard were subsequently removed, with
fresh lists verifying only the original stopped VM/ready disk remain. The
three-hour storage deadline was missed during interruption. Independent review caught the active-evaluator timeout tail:
use 1800 seconds/US$2.25 per mode, reserving five minutes per active tail
and copy/stop time. Preflight console balance was US$8.52,
active/no expiry displayed, not a current balance or billing reconciliation.
The interrupted allocation's compute envelope is about US$7.13 including
assumed tax, before storage, not posted billing. Plan checkpoint `7d08e01` is
pushed. See [the interruption record](../experiments/m3-portfolio-comparison.md).
The one-start authority is exhausted. Before another paid start, review an
interruption-safe execution controller locally, check balance/billing, and
obtain a new numeric cap. The guard is a cost brake, not a workflow driver.
Preserve all valid videos/traces, including failure episodes; use the existing
report's fail-closed speedup gate.

The user approved the goal of one reusable launcher, not changing the robot
configuration on each interruption. The [accepted launcher design](../superpowers/specs/2026-10-01-m3-reusable-launcher-design.md)
uses a scheduled workstation controller through setup plus the existing
guest pair, reusing the watchdog. The [implementation plan](../superpowers/plans/2026-10-01-m3-reusable-launcher.md)
is committed. The immutable run-record/store foundation is reviewed and
integrated. Guest scripts also passed independent spec and quality reviews and
are integrated; the fresh Windows suite passes 385 tests (four platform skips).
The unfinished fixed-purpose host assembly is preserved on
`codex/m3-reusable-launcher`, including uncommitted adapter/CLI/test files;
no builder is active. It is not approved for paid use. Independent review exposed the storage-deadline gap if the controller
dies; Jethro approved the separate cleanup task and requested the shortest
fixed-purpose path back to M3. The plan now permits independent guest-script
porting alongside targeted record review, followed by one controller/cleanup
assembly and scheduled fake acceptance. No generic workflow engine or new robot
configuration is needed. No cloud start is
authorized. Its intended boundary is surviving chat interruption, not
arbitrary laptop/network/authentication failures. This is the immediate
execution blocker only if the optional stretch is resumed; preserve experiment settings.

**Next product-facing local task: cool project name brainstorming**, requested by Jethro.
Final naming remains his decision and requires no paid compute. The
[commit audit](../milestone-commit-audit.md) records M1/M2/M3/M4 as
13/38/132/17 at frozen checkpoint `7d08e01`; these are scope-attributed
non-merge commits, not hours worked.

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

- Portfolio overview remains proposed M5 work. The new recordings for global
  task IDs 1/2 use local-ordinal `task0000` filenames; the existing viewer's
  global-ID glob does not resolve them. They are recorded and recovered, not
  missing. A scoped compatibility fix is pending; preserve one representative
  nominal visible by default as Jethro requested.

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
