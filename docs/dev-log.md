# Development issue log

This log records observed engineering issues separately from provider
feedback in [`FEEDBACK.md`](../FEEDBACK.md). A risk identified by review or
tests is not necessarily a failure seen in the live pilot.

## M5A: task-local media compatibility — October 3

### Case import review (local fixtures, not provider incidents)

The first importer/store/CLI unit passed 440 tests (four platform skips), but
independent spec review reproduced a false historical-confirmation path:
parent episode masks could disagree with the declared parent geometry while
their outcome counts still matched. The review also reproduced arbitrary
lineage/measurement payload leakage, Boolean seeds comparing equal to integer
seeds, optional-media loss disabling otherwise intact inspection, supplemental
profile loss downgrading unrelated historical proof, and contradictory policy
identity being classified as absent proof. Repairs and regression tests are in
progress before integration; a green suite alone did not establish correctness.

Root's read-only check of the real saved M4 bundle resolved 22 videos and 22
traces. It reported missing checkpoint, simulator-image and upstream-harness
pins, and no aggregate-linked exact policy identity. These are legacy metadata
limitations, not fresh replay failures. No original source files, cloud resources
or provider requests were changed during these checks.

### Case schema review

The approved case contract is being implemented as a pure schema kernel before
source reconciliation and CLI persistence. It computes recipe identity and
missing-input lists, not historical failure confirmation. Root inspected saved
M4 source layout independently; see
[`the source map`](research/2026-10-03-m5-existing-m4-source-map.md).

Quality review reproduced an escaped lone-surrogate string leaking an encoding
exception instead of `CaseValidationError`. Direct-Python oversized integers
also exposed serialization inconsistencies. These are local malformed-input
issues, not provider incidents. The builder added UTF-8 JSON serializability
regressions, stable validation errors and NUL-path rejection; independent spec
and quality rechecks passed. Integrated as `46a3419` and `d29f87a`. Ten focused
tests pass. No importer, file-integrity check or verified-failure badge is
implemented by this pure kernel.
Fresh integrated Windows Python 3.11 full suite: 400 tests, four known platform
skips, no failures. Safety-test stop warnings are simulated fixture output.

The task-filtered diagnostic benchmark keeps the global task ID in aggregates,
but the harness names selected-task recordings using local ordinal zero. The
viewer previously looked only for the global filename stem, so saved task-1/2
recordings could appear unavailable despite existing. This is our catalog
integration bug, not a Nebius or NVIDIA failure or a cost-saving recording choice.

`1d79c01` prefers unique contained global matches, then permits local-zero
lookup only when the exact benchmark/filter and all episode identities prove
the mapping. Ambiguous or escaping media produces warnings, never an arbitrary
selection or loss of otherwise valid episode metadata. Global IDs stay intact.
Independent spec and quality review passed; focused catalog/server suites each
passed 14 tests. Root verified all three real screen recordings/traces resolve,
and all 22 M4 videos/traces plus reduction evidence remain available, with zero
catalog warnings. No new robotics runs, provider calls or artifacts were created.

The proposed M5A case contract is separate: independent inspection, recipe,
exercised-replay and historical-confirmation capabilities. Root incorporated
review findings requiring aggregate/summary reconciliation, dependency-specific
source invalidation and validated normalized reimport before asking Jethro to
approve that contract. Importer and dependent UI code have not started.

## M3: parallel replay, pilot, and equal-work comparison

| Issue | Evidence and cause | Resolution or boundary | Status |
| --- | --- | --- | --- |
| Evaluator timeout could leave work behind | A local POSIX reproduction showed the pinned harness CLI exiting on SIGTERM while its spawned Docker-client child survived; the old parent-only cleanup reported success too early. | Each evaluator now has its own process group; timeout closes the launch gate, terminates the group, and checks its exact container. A delayed-child regression passes. Docker-daemon requests can still be in flight, so uncertainty aborts the mode and the independent VM watchdog bounds cloud spend. | Local bug reproduced and fixed; residual daemon risk remains. |
| Episode ownership could become ambiguous on interruption | Tests reproduced interruption after submission but before Future registration; review found a second gap when a completed Future was removed before its result was saved. Several mutable lists represented the same attempt. | A durable per-case ledger records intent before submit and result before releasing ownership. Unknown attempts cannot be retried automatically or counted valid. | Local bug reproduced and fixed. |
| Launch or resume could duplicate uncertain work | A missing persisted launch identity made it unsafe to infer whether an evaluator/container had started; partial sessions could not simply rerun missing-looking rows. | Persist exact evaluator PID/container sidecar. Resume only proven-prepared rows in a validated partial session; exclude resumed modes from throughput comparison. | Safety design implemented; no live resume claimed. |
| VM spend could continue after a guest hang | Process cleanup and runner deadlines do not stop the billable VM. A Python thread or Docker request can outlive the runner's summary deadline. | Exact-VM workstation guard, guest shutdown backup, approved cap, and stop verification. The pilot and full comparison were stopped after evidence copy, before guard deadlines. | Mitigation exercised, not a proof against workstation sleep/network/auth loss. |
| Initial pilot SSH and server launch failed | A previously removed temporary SSH ingress rule caused TCP timeout. A first model-server command used the wrong working directory and could not find its script. | Created a temporary narrow SSH rule, launched from the pinned harness directory, then removed the rule after the run. | Operator setup errors resolved; not Nebius/model faults. |
| Plain detached guard disappeared | The Windows watchdog logged `armed` but its process later vanished without a terminal log event. The cause was not established; a process handle alone was not sufficient liveness evidence. | For the separately approved full run, Windows Task Scheduler owned the same exact-VM guard. Its state remained `Running` during all modes; the task was removed only after independent `STOPPED` verification. Guest shutdown remained backup. | Workaround exercised; investigate the plain-detach lifetime before relying on it again. |
| CLI authentication expired after a start reached Nebius | The start operation succeeded but the local CLI demanded OAuth while waiting for completion. The VM was briefly running without a usable CLI session. | Stopped the exact VM through its console, verified `STOPPED`, renewed CLI auth through the existing browser session, then used a fresh start. | Operator/auth lifecycle incident; not a failed benchmark attempt. |
| M3 throughput and cost needed separate evidence | The two-episode pilot was not an equal-work comparison. The subsequent 1/2/4 modes all completed 16/16 valid repeats with no outcome drift, but provider usage posting lagged. | Fail-closed report shows 1.966× and 3.715× warm speedups. Record warm compute allocations separately from end-to-end VM cost, disk, tax, and the aborted start. Reconcile when billing posts. | Throughput measured; billed cost pending. |
| Three-task screen starts could not allocate the exact VM | On September 30, capacity advice showed one `LOW`-availability L40S-A slot before each of two separately approved starts. Both operations timed out with `NotEnoughResources`; the instance returned to `STOPPED` before any episode. | Treat advice as nonbinding. Preserve both failed operations as infrastructure evidence, verify `STOPPED` and no temporary ingress after each attempt, and require a user-led resource/cap decision before another start; do not substitute a shape or preemptible VM silently. | No robot-task result; billing reconciliation pending. |

The key boundary is **one Nebius VM with several evaluator processes and one
shared GR00T model server**—not several independently started VMs. See the
[M3 experiment record](experiments/m3-parallel.md), [containment design](superpowers/specs/2026-09-28-m3-evaluator-containment-design.md), and [attempt-ownership design](superpowers/specs/2026-09-28-m3-attempt-ownership-design.md).

## October 1 H100 compatibility-screen access failure

The separate snapshot-backed H100 clone reached `RUNNING`; serial logs
confirmed its new network identity, SSH socket listener, cloud-init completion,
and guest shutdown backup. SSH and an independent Windows TCP/22 probe still
timed out after the current workstation `/32` rule was read back ready in the
attached security group. The source IP was also verified without an HTTP proxy.
The remaining access-path cause is unresolved; no stale-network or provider
fault claim is justified. The clone also logged a Fabric Manager startup
failure, not yet diagnosed or shown to block inference. The attempt was stopped
early without an episode. See [the screen record](experiments/m3-three-task-screen.md).

Independent review of that earlier attempt also found that the adaptive command had no two-worker cap
and may select four workers using historical L40S estimates. The nominal screen
proposed the existing one-worker `sequential-jobs` mode instead; the later real
CLI check below corrected that unexecuted proposal. Do not reuse
L40S allocation measurements as H100 performance evidence.

After Jethro switched from hotel Wi-Fi to a phone hotspot on October 1,
credential-free WSL probes received SSH protocol banners from `github.com:22`
and the control endpoint `ssh.github.com:443`. The hotspot therefore permits
outbound SSH to these endpoints. This is not an A/B comparison with the hotel
network and does not prove Nebius reachability or establish the earlier cause;
the temporary H100 VM was already deleted. No compute was started. The public
egress address changed, so any future temporary ingress rule must be refreshed
from the active network immediately before guest access.

## October 1 hotspot screen: contract fixes and successful execution

- A real subprocess CLI dry run caught an argparse mismatch: `manifest` was
  passed to a function expecting `manifest_path`. It also showed sequential
  mode's three attempts would progress task 0 into search, not screen three
  tasks. Before VM start, regressions and independent review validated an
  explicit `--max-workers` cap and nominal-first admission for explicitly
  capped adaptive mode. Uncapped/default and sequential behavior are preserved.
  Commits `b9da038` and `797df18` are integrated into main. Focused CLI/runner/
  report tests passed 34; the Windows suite passed 349 with four platform skips.
- First GPU/catalog probes selected the lightweight evaluator Python or
  container system Python, which lack the model/simulator dependencies.
  Correct model-cache Python and the pinned container's `libero` Conda
  environment passed. Offline `uv` attempted dependency refresh; directly
  invoking its existing cached interpreter avoided downloads. These were
  operator environment-selection mistakes, not invalid robot episodes.
- Hotspot SSH succeeded. Fabric Manager remained failed with the logged
  Pre-NVL5/NVSwitch warning, but CUDA computation and all three nominal episodes
  passed. No driver change or blanket dismissal of the service failure occurred.
- New task-filtered harness runs name videos/traces `task0000_ep0000_*` using
  local task ordinal zero, even when aggregate task IDs are globally 1 or 2.
  The current viewer globs by global task ID, so those recordings are not
  resolved there. Media were recovered and independently verified; a scoped
  reader compatibility fix is pending. Preserve the user's one-representative-
  nominal default, and do not broaden it into show-all navigation silently.

See [the completed screen and cleanup](experiments/m3-three-task-screen.md).

### What the fixes mean in plain language

The successful run kept the same policy, checkpoint, simulator, tasks, and
reset state. The changes repaired how we reached or invoked that setup:

1. **CLI argument mismatch:** the command-line parser called the manifest
   argument `manifest`, but the receiving function expected `manifest_path`.
   Explicitly mapping the name fixes the handoff; a subprocess regression
   tests the real command, not just a direct function call.
2. **Wrong three-attempt schedule:** sequential mode spends its attempts
   progressing one task's diagnosis. Three attempts therefore did not mean
   three tasks. Explicitly capped adaptive admission now runs each ready
   task's nominal case before advancing into search. A one-worker cap keeps
   this screen sequential in execution, while round-robin admission chooses
   the three intended tasks. Default uncapped behavior was left unchanged.
3. **Wrong Python environment:** the evaluator, model server, and simulator
   have different dependencies. Selecting the existing model interpreter and
   simulator Conda environment fixed the probes without reinstalling packages
   or changing the checkpoint.
4. **Remote access:** the retry used the hotspot's freshly checked source
   address in its narrow SSH rule, and credentialed access worked. This is a
   successful recovery, not proof of the hotel network's exact fault.

The Fabric Manager warning was **not fixed**: CUDA and real episodes passed
despite it on this single GPU. The viewer's global-versus-local task filename
mismatch is also **not fixed yet**; it cannot be described as missing recording.
No additional billable run is implied by delivering the saved media.

## October 1 comparison interrupted before guest execution

The assistant turn was interrupted after the new H100 start request but
before source transfer or launch of the prepared paired runner. The scheduled
watchdog remained independent of the turn: after two CLI timeout failures,
it recorded STOPPED confirmation inside the 90-minute boundary. No diagnosis
ran, so no comparison media exists. The temporary-storage cleanup deadline
was missed until the turn resumed and exact-resource deletion was verified.

**Why:** the safety controller persisted, but the workflow controller did
not exist yet. A watchdog is a brake, not a driver: it can stop spending but
cannot finish unissued model/evaluator commands. This is not a concurrency,
policy, or simulator defect. Guest shutdown logs do not establish the cause
of the two workstation CLI timeouts.

**Resolved:** independently rechecked STOPPED, recovered serial/lifecycle
evidence, and deleted only the approved temporary resources. **Not resolved:**
workflow continuity across assistant interruption. Another paid run requires
a separately planned/reviewed persistent execution owner, fresh balance/cap,
and no change to the currently working model/simulator configuration.
See [the interruption record](experiments/m3-portfolio-comparison.md).

## October 1 launcher: bounded local recovery fixes

The shortest-path launcher work preserves the successful robot configuration.
Independent record review caught ownership gaps: the store needed to bind to
the original immutable record and its exact run directory, and hold an OS
lease rather than infer ownership from a stale file. These are implemented and
reviewed. A separate crash-boundary test caught a truncated JSONL tail: reading
the last complete events is safe, but appending after incomplete bytes would
corrupt the next event. The store now refuses that append without modifying the
journal; it does not silently repair history. The integrated Windows suite
passes 380 tests with four platform skips.

Guest-script review found two integration mismatches, fixed on the guest
branch and passing targeted spec review: checking the bundle hash alone did
not prove that the executed checkout matched the frozen commit; and wave
results needed reconciliation against the authoritative attempt ledger before
allowing the adaptive mode. Windows test fixtures also needed explicit LF
bytes when invoking Bash through WSL; the committed scripts were already LF.
Quality review also caught a runner-exception summary that could authorize the
next mode after prior valid waves. The validator now rejects internal runner
exceptions while preserving legitimate budget-limited partial results. Spec
and quality reviews approved the guest scripts, and they are integrated; the
fresh full suite passes 385 tests with four platform skips. Host-controller
integration and actual scheduled fake acceptance remain pending. These are
local project defects, not Nebius or NVIDIA model failures. No cloud run was
started. Publication retries failed with an HTTPS low-speed timeout; these
changes are committed locally, not confirmed pushed.
