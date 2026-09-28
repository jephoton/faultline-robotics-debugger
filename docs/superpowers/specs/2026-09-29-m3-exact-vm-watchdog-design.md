# M3 exact-VM external watchdog design

**Status:** accepted for implementation planning on September 29, 2026. **This design does not authorize starting or stopping the VM.**

## Safety objective

The M3 Python runner, its evaluator children, and Docker all run inside one Nebius VM. If the runner hangs, an absent-container poll cannot prove a Docker daemon request has ended; the VM may continue billing. A watchdog outside the VM must retain one immutable target instance ID, project ID, and absolute UTC deadline, then issue a stop for only that instance and verify `STOPPED`. It is independent of the guest process and Codex turn, not of the workstation's power/network or Nebius control plane. The existing guest timer is backup only; before a live run, refresh it to a deadline no later than the approved maximum if possible.

## Components and data flow

Implement a small Python 3.11 standard-library watchdog as a detached Windows workstation process. It invokes the existing Nebius CLI inside WSL as a child for each control-plane call, using local credentials without copying tokens. This keeps the guard alive if an individual WSL CLI call exits or hangs, though it still depends on Windows being awake and WSL being available. Input is a validated local JSON run record under an ignored directory, containing schema version, exact `computeinstance-...` ID, exact `project-...` ID, UTC deadline, CLI path, and an approved run label. Reject missing or malformed identifiers, past deadlines, paths outside the intended local log root, and a mismatched read-back of the instance's parent project. The record and append-only timestamped JSONL log contain no credentials.

An arm step starts one detached watchdog process *before* VM start, waits for a durable `armed` log entry, and verifies that the process remains alive. The watchdog first performs a read-only exact-instance lookup, then waits until the deadline without changing the VM. At the deadline it issues `nebius compute instance stop --id <immutable-id>`, polls the same ID until `STOPPED`, and logs every command result and state. Transient API failures get bounded retries; after the retry window, log `stop_unconfirmed` and surface urgent manual-console action. Never enumerate VMs to choose a target, stop by display name, use a broad filter, or act on a different project/instance. Do not declare success on a command exit alone.

The execution owner records the watchdog PID, deadline, exact target, and log path before starting the VM. Keep the guard armed during setup, pilot, artifact copy, and cleanup. A manual early stop is permitted for invalid evidence; after independently confirming the exact VM is `STOPPED`, the guard may exit or be cancelled. Never cancel it merely because the runner printed a summary. Disk charges continue while the VM is stopped and require a separate retention/deletion decision.

## Failure modes and limits

If the workstation sleeps, powers off, loses network, or the CLI authentication expires, this guard may not execute; the guest shutdown timer and a human console check are backup layers. An unexpected VM start failure, watchdog death, wrong project/VM read-back, or ambiguous stop status aborts the experiment. The watchdog is a cost boundary, not a proof that evaluator processes, Docker, or the model server shut down cleanly. No automation may silently increase the approved deadline or run cap.

## Local validation and live gate

Use fake CLI subprocesses and a clock seam to test: exact-ID-only stop, parent mismatch refusal, no stop before deadline, stop/poll success, retry exhaustion, malformed records, single-arm behavior, and durable log on exception. A dry run may query the real stopped VM read-only but must never send `stop` or `start`. Before paid use, verify real Nebius account/project, credit balance and expiry, one-L40S quota/capacity, full running VM plus disk rate, the VM's stopped state, the proposed deadline and tax/margin calculation, and Jethro's **separate approval of a numeric run-specific cap**. Test arming/health and guest backup first. If any input is unavailable, do not start.

## Alternatives considered

- Manual timer: easy but depends on a person noticing the deadline; insufficient as the sole cap boundary.
- Guest shutdown timer: useful backup but fails with guest failure and cannot bound a VM stuck outside the OS.
- Nebius-native scheduled stop: potentially stronger, but no exact-resource, timed-stop feature has been verified for this account; do not invent or rely on one.

The accepted approach is the workstation guard plus guest and manual backups, with the remaining workstation/network failure risk stated plainly.
