# M3 reusable interruption-safe launcher

**Status:** Accepted October 1 by Jethro: reusable workstation scheduled
controller plus existing guest pair. This approval covers local implementation,
not a new paid start. No robot configuration changes are proposed.

## Problem and scope

The October 1 comparison allocation became billable before guest setup or
the prepared paired runner was launched. Chat interruption halted the driver;
the independent watchdog eventually stopped the idle VM. The existing guest
`run-pair.sh` already runs the paired commands after launch. The missing part
is a persistent owner across start, connection, setup, launch and recovery.

Build this once and reuse it with a fresh private run record. Do not create
another launcher for each run. This is execution tooling, not a new M3 search
algorithm, model, simulator, scheduler or experiment.

## Alternatives and recommendation

1. **Recommended: workstation scheduled controller plus existing guest pair.**
   Windows Task Scheduler owns a hidden controller before the first start.
   It reuses the exact-VM watchdog and existing CLI/SSH workflow. It survives
   chat termination while the workstation, network and authentication work.
2. **Guest service only.** Good after deployment, but does not solve the
   interruption between VM start and initial source transfer/setup.
3. **Separate always-on cloud controller.** Removes laptop dependence but adds
   deployment, credential management and cost. Outside this bounded fix.

The recommendation does not guarantee survival of workstation sleep/reboot,
loss of network, expired authentication or provider faults. Keep the guest
shutdown backup; report unconfirmed cleanup as unresolved. A standalone
controller can execute approved operations but cannot grant itself authority.

## Ownership and immutable inputs

Root remains sole external-resource owner. The scheduled controller is its
execution mechanism, not a second cloud actor. Root does not manually start,
stop, delete or launch experiments while the controller owns a run. The
independent watchdog only performs its established exact-ID emergency stop.

Each ignored run record binds one existing stopped temporary VM, its managed
disk, its source snapshot, the temporary ingress rule, the original protected
VM/disk, project, immutable code/config identities, SSH host verification,
absolute local/guest paths, numeric cap, one-start approval, compute deadline,
storage deadline and cleanup policy. No credentials or tokens in records.
Production command construction uses validated argv, not interpolated shell
strings containing record values. Never discover targets by name or glob.

Provisioning the stopped clone remains a root-controlled, separately gated
step; the first version does not automate account selection, snapshot creation,
quota changes, top-ups or resource migration. Storage is billable before VM
start: prepare/test the controller before provisioning, and track the snapshot
deadline from actual creation, not from controller launch. If registration
fails, root performs approved temporary cleanup without starting compute.

## Persistent workflow

1. **Prepare:** validate recorded approval and exact resource ownership; freeze
   source/config bundle; verify authentication non-interactively and available
   balance/prices under the separately approved preflight. Unknown billing or
   expired approval fails closed. Verify stopped state and guard readiness.
2. **Arm:** register the controller as a hidden, non-restarting scheduled task,
   acquire an exclusive local run lease and write a durable ready handshake.
   Root must read that handshake and task/process liveness before the controller
   is permitted to start. A local permission file releases only this run.
3. **Start once:** write and fsync `start_intent` before issuing the sole exact-ID
   start request; use an operation identity when available and read-back.
   Never reissue start after timeout or crash. A lost response is uncertain
   authority, not permission to retry. Consult read-back for stop/recovery.
4. **Ready:** bounded SSH/boot probes, pinned source transfer, unchanged GPU,
   checkpoint/catalog/model checks, guest shutdown backup and durable guest
   launch intent. Enforce existing pair remaining-time gates. Failures do not
   initiate a new VM, driver repair or experimental configuration change.
5. **Run:** invoke the existing paired sequence with immutable matched limits.
   Preserve exit 1 for inspection; reject invalid/uncertain ownership before
   adaptive mode. Record guest process/session identity before acknowledging
   launch. A lost SSH acknowledgement never causes a duplicate guest launch.
6. **Recover:** copy completed artifacts incrementally to unique mode/job/case
   paths. Exclude incomplete files from verified inventory until transfer and
   checksum checks pass. Retain logs/status for partial attempts; do not count
   setup evidence as policy episodes or turn partial results into speedup.
7. **Stop and clean:** stop early when finished or when further work is unsafe;
   independently confirm exact VM stopped. Delete only recorded temporary
   resources under the explicit policy, respecting the storage deadline even
   if media recovery is incomplete. Report lost media honestly. Never delete
   the original VM/disk. Remove the watchdog only after stop verification.
8. **Terminal:** write local summary, artifact inventory, operation timeline,
   verified/unconfirmed cleanup and any unresolved uncertainty. Root reads
   status and runs the existing comparison reporter and independent review.

Use append-only phase events and atomic status snapshots. External mutations
have durable intent records written before command submission. Events are
recovery evidence, not proof that a remote operation completed. Bounded retries
are allowed for reads and exact-ID stop; starts and experiment launches are
never blindly repeated. Deadline takes precedence over completeness.

## Reattachment, not unsafe resume

`status` is read-only and works after a chat reconnects. Invoking `start` again
against an existing run refuses mutation and points to status. Task Scheduler
must not automatically restart the controller after it exits or after reboot.
If the controller itself dies, recovery is explicitly stop/copy/cleanup-only
after checking its lease and remote ownership; it does not continue diagnostic
work or extend approval. Existing uncertain-case and comparison-resume gates
remain unchanged. This version does not promise exactly-once distributed
execution; ambiguous side effects fail closed.

## Proposed implementation boundaries

- `src/robot_debug/cloud_run_record.py`: strict immutable record, containment,
  approval/deadline and protected-resource checks; atomic state/event storage.
- `src/robot_debug/cloud_run_controller.py`: phase machine with injected clock,
  filesystem and command adapter; lifecycle/transfer orchestration only.
- `scripts/run_cloud_comparison.py`: prepare/arm/status/recover entry point,
  hidden Windows scheduled-task wiring, validated production commands and
  explicit local-test backend that cannot invoke WSL, SSH or Nebius.
- `scripts/cloud_guest/`: sanitized reusable versions of existing preflight,
  model/pair launch and validation scripts. Parameterize paths/identities only;
  keep policy/inference commands and experimental semantics unchanged.
- `tests/test_cloud_run_record.py`, `tests/test_cloud_run_controller.py`,
  `tests/test_cloud_run_cli.py`: local deterministic safety and lifecycle tests.
- Existing `vm_watchdog.py`, portfolio core and evidence reporter remain
  unchanged unless an independently reproduced integration defect requires
  a narrowly reviewed fix. No viewer changes in this scope.

## Local acceptance evidence before spending

Tests must prove no start before durable controller-ready and watchdog-armed
handshakes; duplicate invocation refusal; crash between start intent and reply
does not restart; lost guest-launch reply does not duplicate episodes; mismatched
target/protected disk prevents mutation; expired auth and failed readiness lead
to bounded stop/recovery; deadline prevents adaptive launch; transfer interruption
keeps incomplete media unverified; exact cleanup with absent/already-deleted
targets preserves originals; unconfirmed stop retains the guard and reports
error; fake CLI mode cannot reach production commands.

Run a scheduled local fake backend through a parent-process exit: it must
continue to terminal, emit copied fake media inventory and show exactly one
start/guest launch. Separately kill the controller at mutation boundaries and
verify recovery refuses new work. Tests cannot prove cloud capacity, real
authentication lifetime or laptop sleep survival; document those limitations.

## Agent handoff and gates

After topology approval, write a self-contained implementation plan with
commands, tests and small conventional-commit boundaries. Assign a smaller
capable builder to controller code/tests in a suitable isolated worktree;
assign a read-only independent reviewer to failure injection and authority
contracts. Parallelism: reviewer analyzes the contract while builder implements;
final review depends on implementation evidence. Root owns integration and
all production resource mutation. No overlapping edits, no agent cloud starts.

Green: local tests, serialization, documentation and routine fixes. Amber:
phase wiring, bounded retry/transfer mechanics within this contract. Red:
new topology, changed experiment limits/semantics, new paid allocation or cap,
new resource/deletion authority, and publication without user approval.

No cloud execution is authorized by approval of this design or its future
implementation plan. The exhausted October 1 allocation is not reusable spend
authority. Fresh balance/billing, pricing, capacity and numeric-cap approval
remain a separate live-run gate. Project-name brainstorming remains the next
product-facing local task; this launcher is the immediate execution blocker.
