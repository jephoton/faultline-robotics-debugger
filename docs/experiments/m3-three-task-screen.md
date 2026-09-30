# M3 three-task nominal screen: allocation attempts

**Status (September 30, 2026): two separately approved exact-shape starts blocked by capacity before any episode.** This is an infrastructure outcome, not evidence about task IDs 0, 1, or 2 or the portfolio scheduler.

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

## Next gate

Do not count either attempt as a nominal screen or automatically retry with preemptible capacity, another GPU shape, or a different task. Decide with Jethro whether to wait for the current VM's exact shape or investigate a new resource and cache-transfer path under a separately priced cap. Before another paid start, revisit the balance/retention risk that was explicitly skipped for this retry. If the task screen eventually runs, verify served checkpoint and runtime task catalog before launching any evaluator, and interpret each task's episode separately.
