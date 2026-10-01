# M3 live portfolio comparison: interrupted startup

**Status:** No sequential/adaptive comparison was launched. The single
approved October 1 allocation is stopped and its temporary resources are
deleted. This is an execution interruption, not a robot-policy result.

## Approved scope and prepared work

Jethro approved US$8 total, one H100 start, a 90-minute maximum, and cleanup
of the temporary snapshot-backed VM/disk and snapshot, preserving the
original L40S setup. The frozen [execution plan](../superpowers/plans/2026-10-01-m3-live-portfolio-comparison.md)
uses the same three LIBERO Object tasks, checkpoint, simulator, masks,
diagnostic gates, and recording as the successful nominal screen. It pairs
whole-job sequential execution with an adaptive two-evaluator cap and
identical 111-attempt / 1800-second / US$2.25 warm limits per mode.

Independent review caught that the runner's time limit closes admission but
does not terminate already-active evaluators. Two possible 300-second tails
were reserved without changing the evaluator or the simulator. Local focused
tests passed 34; full Windows Python 3.11 passed 349 with four platform skips.
The plan was committed and pushed at `7d08e01`. Private orchestration scripts
were syntax checked and independently reviewed before start.

## Actual execution and interruption

The exact-VM scheduled watchdog recorded verified STOPPED and armed at
10:19:56 UTC. The one start request began at 10:20:32 UTC and completed
at 10:22:42 UTC. The assistant's execution was interrupted during startup,
before credentialed guest access, source transfer, model-server launch,
runtime preflight, or either portfolio command. No automatic diagnostic
controller was yet running; the independent watchdog could stop the VM
but could not execute the unfinished workflow.

At its 11:46 UTC deadline, the watchdog's first two CLI stop calls timed out.
It subsequently recorded stop requested and independently confirmed STOPPED
at 11:47:44 UTC, inside the 90-minute allocation boundary. On resumption at
13:35 UTC, a fresh CLI read again verified STOPPED. Shutdown serial logs and
the durable guard record were preserved locally. This does not prove which
component caused the two CLI timeouts or prove the guest backup timer caused
shutdown; no such attribution is made.

There are **zero comparison episodes, zero new videos, and zero new traces**.
The previous three nominal videos/traces remain intact and are not comparison
evidence. A working configuration and prepared scripts are not a completed
experiment, nor evidence of speedup.

## Cleanup and cost boundary

After copying available lifecycle/serial evidence, the exact temporary VM
and its managed disk, snapshot, narrow SSH rule, and scheduled watchdog were
removed under the existing cleanup approval. Fresh lists verified only the
original stopped L40S VM and its ready managed disk remain, no snapshots
remain, and the security group contains only standing egress. The deleted
temporary resources cannot be recovered; the source cache and prior episode
artifacts are preserved.

The three-hour temporary-storage cleanup deadline was 13:15:57 UTC and was
missed while execution was interrupted; cleanup was performed on resumption
around 13:36 UTC. Record this as a control-layer failure, not compliance with
the planned retention limit. The approximately 87m12s start-request-to-guard-
confirmation envelope implies about US$7.13 compute including assumed 9%
tax. Temporary/source storage accrual is separate; these are estimates, not
posted billing or a reconciled cap claim. The preflight displayed US$8.52
balance is not a current remaining balance.

## Next execution gate

The one-start authority is exhausted. Do not restart the original or create
another clone automatically. Before another paid start, inspect balance and
outstanding charges, obtain a new numeric cap, and settle an interruption-safe
workflow: the cloud lifecycle should not depend on an active assistant turn
after the VM has become billable. Reusing the model/simulator configuration
does not solve that orchestration gap. Prepare/review any such controller
locally before spending; keep it separate from policy and scheduler behavior.
Project-name brainstorming is the next local task and needs no paid compute.
