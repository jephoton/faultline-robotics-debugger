# M3 three-task nominal screen: allocation attempts

**Status (October 1, 2026): two L40S placement failures followed by an H100 clone that booted but remained unreachable over SSH. No episode ran.** These are infrastructure outcomes, not evidence about task IDs 0, 1, or 2 or the portfolio scheduler.

## Frozen scope and local proof

Jethro selected LIBERO Object task IDs `(0, 1, 2)` as nominal-screening candidates and approved a maximum **US$3 incremental spend / 60 minutes VM-on** on the existing L40S VM. The run would use only the first nominal episode of each task (`episodes=3` shared attempt ceiling), no occlusion search, and no benchmark speedup claim. Commit `9344c62` added an exact three-case dry-run regression. The Windows suite passed 345 tests (4 skips); the focused WSL lifecycle/driver suites passed 66.

Before the start, the console showed US$9.96 balance. The Nebius calculator quoted US$1.7468/hour for the VM and US$0.0194444/hour for the retained disk, pre-tax. Capacity advice showed one available on-demand slot for the exact `gpu-l40s-a` shape in `eu-north1`, but labeled availability `LOW`. The exact VM was read back as `STOPPED` in the intended project. These figures are preflight observations, not a posted invoice.

## Control and outcome

A Windows Task Scheduler-owned exact-VM guard read the stopped target, logged `verified` and `armed` durably at 12:57:36 UTC, and held a 13:55:00 UTC stop deadline. The reviewed source at commit `9344c62` was packaged as a private local Git bundle; it was **not** pushed or transferred to the guest.

One regular-instance start was requested at 12:58:49 UTC. Its operation ended at 13:04:21 UTC with Nebius `NotEnoughResources`: VM scheduling timed out for the existing `1gpu-16vcpu-64gb` shape. The instance never reached a usable guest, so no guest shutdown backup, model/task-catalog verification, evaluator, or episode ran. The initial SSH attempt timed out while the VM was still `STARTING`; this is consistent with the failed start, not a model failure.

The temporary workstation-`/32` SSH ingress rule was deleted. The exact instance was independently read back as `STOPPED`, the security group listed only its standing egress rule, and only then was the scheduled guard stopped and unregistered. The ignored guard log and operation identity are preserved locally. No compute-charge claim is made until billing posts; the retained disk remains billable.

## Second attempt under renewed approval

Later on September 30, Jethro explicitly requested a same-VM retry under the prior US$3/60-minute maximum and asked to skip a fresh balance check. The prior US$9.96 reading was **not** treated as a current balance. The CLI again read the exact VM `STOPPED`; fresh calculator estimates were unchanged at US$1.7468/hour for compute and US$0.0194444/hour for disk. Capacity advice again showed one exact-shape on-demand slot but `LOW` availability. A separate reviewed source bundle contained commit `e64f5e8`.

The fresh OS-owned exact-VM guard logged `verified` and `armed` at 13:33:11 UTC, with a 14:31:00 UTC deadline. One regular-instance start was requested at 13:34:10 UTC. Operation `computeoperation-e00d6gtknq7b7ewdff` ended at 13:39:40 UTC with the same `NotEnoughResources` VM scheduling timeout for `1gpu-16vcpu-64gb`. It did not reach guest access; no source transfer, model preflight, or evaluator occurred. The exact VM was independently read back as `STOPPED`, the security group still contained only its standing egress rule (no retry ingress rule had been created), and then the guard was stopped and unregistered. The second ignored guard log is retained locally. Posted billing remains unverified.

After this repeat, read-only capacity advice still showed `LOW` availability for L40S-A. It showed four L40S-D 1-GPU/16-vCPU/96-GiB slots at `LOW` availability and H100 1-GPU/16-vCPU/200-GiB slots at medium/high availability. Calculator quotes were US$1.8172/hour and US$3.85/hour respectively, pre-tax. These are possible *new resource designs*, not approved substitutions or guarantees of scheduling; the stopped VM's existing boot disk and model cache are tied to the current setup.

## Capacity diagnosis (read-only)

The same instance successfully started several times on September 29. Its operation history shows no instance update between the last successful stop and the two September 30 starts. Both new operations reached Nebius scheduling, spent about five and a half minutes in `STARTING`, and terminated with `NotEnoughResources` for the unchanged `1gpu-16vcpu-64gb` preset. There was no guest or SSH access to diagnose, and no evidence implicates the image, GR00T server, evaluator, or portfolio code. This isolates the immediate failure to regular-VM placement for that exact platform/preset; it does not reveal Nebius's internal scheduling reason beyond insufficient available hardware.

Nebius's [error guide](https://docs.nebius.com/compute/virtual-machines/not-enough-resources) identifies regional supply pressure as a cause when restarting stopped VMs. Its [capacity-advisor guide](https://docs.nebius.com/compute/virtual-machines/capacity-advisor) says an `available` count is a quota-and-capacity estimate at `effective_at`, not a launch guarantee; `LOW` explicitly means creating resources might not be possible. A later read showed the exact shape at `available=1`, `limit=32`, `LOW`; quota was not the observed error. Other presets on the same L40S-A platform shared that low-capacity signal, so merely changing vCPU/RAM on this VM is not a demonstrated remedy.

The [Nebius Compute API](https://github.com/nebius/api/blob/main/nebius/compute/v1/instance.proto) marks a VM's `resources.platform` immutable. The existing 200-GiB Network SSD boot disk is managed by the stopped VM, so deleting that VM would delete its disk unless its ownership is first changed correctly. No such update or deletion was attempted. Read-only CLI inspection confirms that the same project offers both L40S-D and H100 1-GPU presets, and that Nebius supports snapshots from the existing disk and managed boot disks sourced from a snapshot. A snapshot-based new VM is therefore a plausible non-destructive migration path, but its snapshot cost, creation time, H100/L40S-D runtime compatibility, and live scheduling success have **not** been tested.

At the September 30 calculator rate, L40S-D was US$1.8172/hour with four advised slots at `LOW`; H100 was US$3.85/hour with medium/high advised availability. These exclude additional cloned-disk/snapshot storage and tax. The [public pricing page](https://nebius.com/prices) lists an H100 rate increase effective October 1, so refresh the calculator and cap immediately before any approved migration. The H100 option has stronger capacity evidence but changes hardware and cannot be compared directly with the previous L40S throughput measurements.

## Next gate

Do not count either attempt as a nominal screen or automatically retry with preemptible capacity, another GPU shape, or a different task. Decide with Jethro whether to wait for the current VM's exact shape or investigate a new resource and cache-transfer path under a separately priced cap. Before another paid start, revisit the balance/retention risk that was explicitly skipped for this retry. If the task screen eventually runs, verify served checkpoint and runtime task catalog before launching any evaluator, and interpret each task's episode separately.

## H100 migration preflight (September 30, read-only)

Jethro selected a separate snapshot-backed H100 VM, preserving the original L40S VM and disk. The CLI again read the exact original VM as `STOPPED` and its 200-GiB Network SSD boot disk as `READY`, AMD64, and still managed by that VM. The intended console project matched the CLI project. No snapshot or new VM existed at this check; no billable mutation was made.

The H100 `gpu-h100-sxm` / `1gpu-16vcpu-200gb` preset is available to this project. On-demand capacity advice for its four `eu-north1` fabrics showed 32/32 `HIGH`, 28/32 `MEDIUM`, 32/32 `HIGH`, and 32/32 `HIGH` at its effective timestamp. This is a much stronger placement signal than L40S-A's `LOW`, but not a reservation or successful start. The project calculator returned US$3.85 per H100 VM-on hour before tax on September 30; [Nebius's detailed pricing](https://docs.nebius.com/compute/resources/pricing#nvidia-h100-nvlink) lists US$4.50/hour from October 1, so the higher rate governs the proposed cap. The signed-in console showed US$9.89 balance; no credit-expiry date was displayed. Recheck balance, rate, and capacity immediately before an approved creation/start.

The same calculator returned US$0.0194444/hour for each 200-GiB Network SSD disk. [Nebius's snapshot pricing](https://docs.nebius.com/compute/resources/pricing#disk-snapshots) separately lists US$0.071/GiB per 730 hours, about US$0.01945/hour for a complete 200-GiB snapshot. The docs say snapshots support boot disks, remain in the source project, and are billed as complete disk copies. The CLI supports snapshot creation from the exact disk and snapshot-backed managed boot disks. Its VM-create default is running, so the H100 clone must use explicit `--stopped`; guest boot and pinned-model compatibility remain untested.

Conservative proposed bound: 60 minutes H100 VM-on at the **new** US$4.50 rate, plus 24 hours each for snapshot, cloned disk, and retained original disk, totals about US$5.90 pre-tax or US$6.43 with an assumed 9% tax. The incremental portion excluding the already-retained original disk is about US$5.92 with that tax assumption. Recommend a **US$7.50 maximum total project spend attributable to this bounded attempt**, one H100 start, 60-minute exact-VM stop deadline, and removal of the temporary snapshot/clone within 24 hours after evidence is copied and stop confirmed. This has about US$1.07 headroom over the conservative estimate and would leave at least US$2.39 of the displayed balance if the cap is fully consumed. It is a proposal, not an approval or guarantee; no posted billing is yet available. The original L40S VM/disk are excluded from cleanup and remain untouched.

The local WSL `unittest` run of `tests.test_diagnostic_portfolio_cli` passed 7/7 tests, including the three exact nominal requests and no search. This is only local contract evidence; runtime task mapping and H100 compatibility still need live verification.

## October 1 approved H100 attempt

Jethro approved US$7.50 total, one H100 start, at most 60 minutes VM-on,
and deletion of only the temporary clone/managed disk and snapshot after
evidence copy within 24 hours. Fresh preflight found US$9.55 balance, no
displayed expiry, the original VM stopped with its managed disk ready, and
H100 availability `HIGH`/`MEDIUM`. The live compute estimate was US$4.50/hour
pre-tax. The focused Windows Python 3.11 CLI tests passed 7/7.

Independent command review found that adaptive mode could select four
workers from historical L40S measurements and had no two-worker cap flag.
The screen therefore selected `sequential-jobs` (one evaluator), preserving
the three nominal requests and avoiding a hardware-inappropriate allocation.
This is a compatibility screen, not a throughput comparison. No command was
actually launched on the guest.

The exact stopped source disk produced a ready AMD64 snapshot; a separate
snapshot-backed H100 VM was created explicitly stopped. Its OS-owned exact-VM
watchdog logged `verified` and `armed` at 08:31:49 UTC with a 09:30 deadline.
One start reached `RUNNING`. Serial logs show the guest booted, configured its
new private address and MAC, listened on `ssh.socket`, and completed cloud-init
at 08:34:22 UTC. Its backup shutdown was scheduled for 09:29:22 UTC.

SSH nevertheless repeatedly timed out. Read-back confirmed the attached
security group had a ready stateful TCP/22 allow rule restricted to the
workstation's current public `/32`, verified from Windows and direct WSL
egress. An independent Windows TCP probe also timed out. This rules out a
WSL-only problem and provides evidence against stale clone network identity;
it does **not** establish the remaining cause or prove provider fault. Serial
logs also reported a failed NVIDIA Fabric Manager service, whose relevance
to GPU readiness could not be tested without guest access.

The coordinator requested an early stop at 08:39:51 UTC rather than consume
the full deadline on an inaccessible guest. Boot logs and lifecycle records
were copied to the ignored local control directory before cleanup. No source
transfer, served-checkpoint verification, task-catalog check, model server,
evaluator, episode, trace, or MP4 resulted. Posted billing is still unverified;
the cap is not the actual charge. A future paid retry requires a new bounded
decision informed by access-path diagnosis, not an automatic replacement VM.

Stop completed at 08:41:25 UTC. After copying the final shutdown logs and
stopped-instance read-back, the temporary VM (including its managed clone
disk), snapshot, and temporary SSH rule were deleted under the approved scope.
Fresh lists verified only the original stopped L40S VM and original ready
managed disk remain, no snapshot remains, and the group has only its standing
egress rule. The scheduled watchdog task was removed after stop confirmation.
The deleted clone/snapshot are not recoverable through this project; the
untouched original disk remains the source cache. The roughly ten-minute
start-to-stop operation window implies about US$0.82 compute including assumed
9% tax as a conservative estimate, not a posted charge; storage is separate.
