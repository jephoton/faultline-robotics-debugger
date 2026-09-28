# M3 Exact-VM Watchdog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Arm and dry-run verify an independent workstation process that stops only the approved Nebius VM at a fixed UTC deadline and proves the VM reached `STOPPED`.

**Architecture:** A pure guard core validates an ignored JSON run record, queries the exact VM, persists an append-only JSONL audit log, and uses a monotonic wait until the UTC deadline. A Windows Python 3.11 `arm` wrapper starts `watch` detached and hidden before any VM start; each Nebius call is a subprocess to the existing WSL CLI, so no token is copied into the record. A fake command seam makes all tests local.

**Tech Stack:** Python 3.11 standard library (`subprocess`, `datetime`, `json`, `os`, `pathlib`, `time`), existing WSL Nebius CLI, `unittest`, Windows Python 3.11. No real `start`/`stop` in implementation tests.

---

## Scope, ownership, and safety gate

**Accepted design:** `docs/superpowers/specs/2026-09-29-m3-exact-vm-watchdog-design.md`. A smaller implementation agent owns `src/robot_debug/vm_watchdog.py`, `scripts/run_vm_watchdog.py`, and `tests/test_vm_watchdog.py`. A separate pilot-runner agent may work in parallel in an isolated worktree; paths do not overlap. The coordinator owns integration and all real Nebius lifecycle actions. Independent spec and quality reviewers are read-only. Green: pure tests, local files, dry-run code. Amber: exact bounded retry intervals and process-launch handshake; explain at review. Red: target VM/project, deadline, numeric cap, live `stop`, `start`, or any security/credential change—Jethro decides at the live gate.

Never embed the live instance ID, project ID, account email, token, SSH key, or a personal absolute path in tracked code/docs. The run record and logs live under ignored `artifacts/m3-control/<run-label>/`. The guard must never enumerate VMs to choose a target or interpret a successful stop RPC as `STOPPED` without a subsequent exact-ID read.

## Task 1: Pure record and state-machine tests

**Files:** Create `tests/test_vm_watchdog.py`, `src/robot_debug/vm_watchdog.py`.

- [ ] Write red tests for a record containing `schema_version=1`, `instance_id='computeinstance-test123'`, `project_id='project-test123'`, `deadline_utc` in RFC3339 UTC, `run_label='m3-pilot'`, and `wsl_cli_path='/home/test/.nebius/bin/nebius'`. Reject a wrong ID prefix, missing field, relative or non-UTC deadline, already elapsed deadline, or log path outside the selected ignored control root. Assert no credential-like field is accepted into the persisted record.
- [ ] Define a narrow `GuardRecord` dataclass and `load_record(path, *, control_root, now_utc)` that checks exact keys, strings, UTC datetime, and resolved path containment. Construct the command as an argument array, never a shell string: `['C:\\Windows\\System32\\wsl.exe', '--exec', cli_path, 'compute', 'instance', 'get', '--id', instance_id, '--format', 'json', '--no-browser', '--timeout', '30s', '--no-check-update']`. Use an injected `invoke(argv)` for tests.
- [ ] Add red/green fake-command tests for read-back parent mismatch refusal, an `armed` event after exact-ID/project verification, no `stop` before deadline, a single exact-ID `stop` at deadline, subsequent exact-ID polling until `status.state == 'STOPPED'`, already-stopped target, bounded retry on CLI failure, and final `stop_unconfirmed` after retry exhaustion. Use injected `now()`/`sleep()` to avoid real waits. Log every state transition as one flushed, fsynced JSONL record with a UTC timestamp; test that an exception leaves a diagnostic event.
- [ ] Run `$env:PYTHONPATH='src'; & 'C:\Windows\py.exe' -3.11 -m unittest tests.test_vm_watchdog -q` and `git diff --check`. Commit the module/tests as `feat(cloud): add exact-VM guard core`.

## Task 2: Detached arm and safe CLI

**Files:** Create `scripts/run_vm_watchdog.py`; extend `tests/test_vm_watchdog.py`.

- [ ] Add CLI modes `check`, `arm`, and `watch`. `check` validates the record and performs only the exact-ID `get`; it must never call `stop`. `watch` writes `armed` only after verifying target/project, waits until the deadline, then performs the stop/poll state machine. `arm` uses Windows `subprocess.Popen` with `CREATE_NO_WINDOW | DETACHED_PROCESS` to launch the same Python script in `watch` mode, with stdin closed and stdout/stderr directed to files beneath the ignored control directory. It waits for `armed` plus a live child process for a bounded handshake and records the PID; it must refuse a second active arm for the same run record.
- [ ] Use an exclusive `arm.lock`/pid record to prevent two guards. A stale lock is fail-closed and requires human verification of the exact VM state before removal; no auto-steal. Test a second arm refusal, child exits before `armed`, missing log, malformed CLI JSON, expired auth, and no silent success. Expose a `--fake-cli` test seam only in tests or an explicit local-test mode that cannot invoke real stop.
- [ ] On Windows, run fake-CLI integration tests that assert spawned guard survives parent `arm` exit and emits `armed`, then simulated deadline `stop_confirmed`, without touching Nebius. Run full Windows suite and `git diff --check`; commit `feat(cloud): arm detached VM watchdog`.

## Task 3: Review, runbook, and live-use boundary

**Files:** `docs/codex-handoff/RUNBOOK.md`, `docs/codex-handoff/STATE.md`, `docs/experiments/m3-parallel.md` (coordinator only).

- [ ] Independent spec review checks exact immutable target, parent read-back, deadline behavior, no early stop, durable logs, stop polling, and fail-closed arm. Independent quality review checks subprocess argument safety, record/log path containment, detached-process lifecycle, and no credential exposure. Resolve Important findings before integration.
- [ ] Coordinator reruns Windows full suite, `git diff --check`, scoped secret scan, and a real read-only `check` against the currently stopped VM using an ignored run record. `check` must visibly issue no stop. Do not run `arm` with a live deadline or start the VM in this task.
- [ ] Document verified commands, backup guest timer, workstation/network/auth risks, recovery of stale locks, emergency console action, and disk retention cost. Commit `docs(cloud): record M3 watchdog procedure`.
- [ ] Stop for a new cost checkpoint: verify credit balance/expiry in console, target VM/region/state, quota/capacity, live VM+disk price, exact UTC deadlines, 9% tax assumption, and remaining US$75 envelope. Calculate a numeric worst-case pilot cap and ask Jethro to approve it separately before arming the real guard or starting the VM. A pilot result never automatically authorizes the 48 comparison episodes.

## Self-review and handoff

The first task is pure and independently testable; the second adds the process wrapper without changing the guard's target logic; the third validates real read-only preflight and documentation. The pilot runner and guard can be implemented concurrently only in separate worktrees, with the coordinator integrating and reviewing both. No billable command is in the implementation scope.
