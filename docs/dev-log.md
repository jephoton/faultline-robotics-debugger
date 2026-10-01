# Development issue log

This log records observed engineering issues separately from provider
feedback in [`FEEDBACK.md`](../FEEDBACK.md). A risk identified by review or
tests is not necessarily a failure seen in the live pilot.

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
