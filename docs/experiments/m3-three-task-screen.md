# M3 three-task nominal screen: first live attempt

**Status (September 30, 2026): blocked by exact-shape capacity before any episode.** This is an infrastructure outcome, not evidence about task IDs 0, 1, or 2 or the portfolio scheduler.

## Frozen scope and local proof

Jethro selected LIBERO Object task IDs `(0, 1, 2)` as nominal-screening candidates and approved a maximum **US$3 incremental spend / 60 minutes VM-on** on the existing L40S VM. The run would use only the first nominal episode of each task (`episodes=3` shared attempt ceiling), no occlusion search, and no benchmark speedup claim. Commit `9344c62` added an exact three-case dry-run regression. The Windows suite passed 345 tests (4 skips); the focused WSL lifecycle/driver suites passed 66.

Before the start, the console showed US$9.96 balance. The Nebius calculator quoted US$1.7468/hour for the VM and US$0.0194444/hour for the retained disk, pre-tax. Capacity advice showed one available on-demand slot for the exact `gpu-l40s-a` shape in `eu-north1`, but labeled availability `LOW`. The exact VM was read back as `STOPPED` in the intended project. These figures are preflight observations, not a posted invoice.

## Control and outcome

A Windows Task Scheduler-owned exact-VM guard read the stopped target, logged `verified` and `armed` durably at 12:57:36 UTC, and held a 13:55:00 UTC stop deadline. The reviewed source at commit `9344c62` was packaged as a private local Git bundle; it was **not** pushed or transferred to the guest.

One regular-instance start was requested at 12:58:49 UTC. Its operation ended at 13:04:21 UTC with Nebius `NotEnoughResources`: VM scheduling timed out for the existing `1gpu-16vcpu-64gb` shape. The instance never reached a usable guest, so no guest shutdown backup, model/task-catalog verification, evaluator, or episode ran. The initial SSH attempt timed out while the VM was still `STARTING`; this is consistent with the failed start, not a model failure.

The temporary workstation-`/32` SSH ingress rule was deleted. The exact instance was independently read back as `STOPPED`, the security group listed only its standing egress rule, and only then was the scheduled guard stopped and unregistered. The ignored guard log and operation identity are preserved locally. No compute-charge claim is made until billing posts; the retained disk remains billable.

## Next gate

Do not count this as a nominal screen or automatically retry with preemptible capacity, another GPU shape, or a different task. Recheck exact-shape availability and balance later, then agree on a fresh bounded start attempt. If the task screen eventually runs, verify served checkpoint and runtime task catalog before launching any evaluator, and interpret each task's episode separately.
