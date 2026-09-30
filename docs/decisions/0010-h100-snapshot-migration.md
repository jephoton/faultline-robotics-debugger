# ADR 0010: Preserve the L40S VM and screen tasks on a cloned H100 VM

**Status:** Accepted migration direction on 2026-09-30; provisioning and spend pending separate approval.

## Context

The existing L40S-A VM failed two separately guarded starts with Nebius `NotEnoughResources` before guest access. Its platform is immutable, and its managed 200-GiB boot disk would be at risk if the original VM were deleted. Capacity advice for the same-project H100 shape was materially stronger than for L40S-A or L40S-D, although advice is not a placement guarantee. The three-task nominal screen has not run.

## Decision

Use a disk snapshot to create a **separate** H100 VM in the same Nebius project, retaining the stopped L40S-A VM and its original boot disk unchanged. Reuse the pinned software environment only after verifying that the cloned guest boots and serves the intended model. Run the already-approved *experiment design*—one nominal episode each for LIBERO Object task IDs 0, 1, and 2—only after a fresh numeric spending cap and exact-VM lifecycle controls are approved. The earlier US$3 L40S cap does not transfer to this migration.

## Alternatives considered

- Retry or wait for L40S-A: least migration work, but two unchanged starts timed out and current capacity advice remains low.
- Clone onto L40S-D: lower hourly estimate but similarly low advised availability and still requires a snapshot/new VM.
- Clone onto H100: higher hourly cost and untested compatibility, but the strongest observed availability signal. This is Jethro's choice for the next bounded screen, not a permanent platform standard.

## Consequences and safeguards

Snapshot and cloned-disk storage may bill even while both VMs are stopped. Their live prices, current account balance, H100 calculator price, capacity, and quota must be verified before creation; snapshot pricing was not established from the public pricing page. The original VM and disk must not be deleted or reconfigured as part of the screen. An exact-ID workstation watchdog must be armed before starting the new VM; guest shutdown is backup. Source transfer stays private, and temporary SSH ingress is removed after use. H100 timing cannot be compared directly with the previous L40S fixed-work throughput result. Any eventual task success is a one-state compatibility observation, not a reliability baseline.

Revisit this choice if H100 capacity falls, snapshot/clone pricing breaches an acceptable cap, the clone cannot boot or serve the pinned checkpoint, or the task catalog differs. See [the migration plan](../superpowers/plans/2026-09-30-m3-h100-snapshot-screen.md).
