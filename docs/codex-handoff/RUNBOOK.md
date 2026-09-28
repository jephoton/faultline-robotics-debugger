# Verified project runbook

> Generated operational context. Commands are relative to the repository root.

## Local environment

The repository uses a Linux virtual environment at `.venv/` under WSL. Set the
source path for direct module execution:

```bash
export PYTHONPATH=src
```

## Viewer

```bash
.venv/bin/python -m robot_debug.viewer.server \
  --artifacts artifacts \
  --port 8765
```

Verify:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
Invoke-RestMethod http://127.0.0.1:8765/api/runs -TimeoutSec 30
```

## Tests

Focused viewer suite:

```bash
PYTHONPATH=src .venv/bin/python -B -m unittest \
  tests.test_viewer_catalog tests.test_viewer_server -v
```

Complete suite when all development dependencies are installed:

```bash
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
```

Verified Windows Python 3.11 alternative when the WSL environment lacks test
dependencies:

```powershell
$env:PYTHONPATH = 'src'
& 'C:\Windows\py.exe' -3.11 -m unittest discover -s tests -v
```

Verified after pilot/watchdog integration: 242 tests pass,
with 3 POSIX-only skips, on Windows Python 3.11. The focused lifecycle and
driver suites also pass under WSL (66 tests), including real POSIX signals:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_m3_posix_lifecycle tests.test_parallel_eval_driver -q
```

The ledger writes `submitting_unknown` before enqueueing a case and
`completing_pending` with its full result before releasing Future ownership.
This preserves conservative evidence if interruption lands at a save boundary;
`results`, `valid_count`, and `in_flight_ids` are derived from the ledger.
For the production launcher, `launches/<case-id>.json` records the exact
evaluator PID and expected `vla-eval-<pid>` container name immediately after
`Popen`, before waiting. These tests do not prove Docker-daemon-level
containment.

An explicit `scripts/run_parallel_eval.py ... --resume` is only for a partial
session whose existing manifest and ledger validate, all attempted cases are
terminal-valid, and the remaining cases are proven `prepared` with no stale
output or launch sidecar. A per-session exclusive lease prevents concurrent
resumes; a stale lease after a crash is intentionally not stolen automatically.
Resolve it only after verifying the exact evaluator/VM state. A resumed mode is
marked and rejected by the throughput reporter; rerun a fresh mode for a fair
1/2/4-worker comparison.

Also run `git diff --check` before committing. Use Conventional Commit
messages and stage only task-related paths.

## Cloud safety

Before any Nebius start, confirm authentication, tenant/project, balance,
expiry, GPU quota/capacity, exact rates, VM state, and the user-approved cap.
Arm independent cleanup, copy evidence before media, and verify the VM is
stopped and temporary network rules are absent after every attempt.
Do not start the M3 live session merely because local tests pass. The runner
has POSIX process-group termination plus exact-container cleanup checks, but
cannot rule out a Docker daemon request still in flight. The pilot requires
arming the implemented exact-VM stop watchdog and a separately approved
run-specific cap. After any uncertain timeout or interruption, stop and verify the exact
VM before another mode; do not rely on a momentary absent-container check.

The local M3 pilot command is `PYTHONPATH=src python3 scripts/run_parallel_eval.py
pilot --upstream-root <pinned-harness> --project-root <repo> --results-root
<ignored-results> --launch-cutoff-seconds <seconds> --item-timeout-seconds
<seconds>`. It fixes two workers and one nominal plus one M4 reduced-mask
case, writes `m3-pilot-workers-2/`, and cannot resume. A valid pilot requires
both expected outcomes and non-empty traces and MP4s. It is not accepted by
the benchmark reporter. No live pilot has been run.

The workstation watchdog is `PYTHONPATH=src python3 scripts/run_vm_watchdog.py
check|arm|watch --record <ignored-record.json> --control-root
<ignored-control-root>`. The JSON record contains only schema version, one
exact instance ID, one exact project ID, future UTC deadline, run label,
absolute WSL CLI path, and absolute JSONL log path under the control root.
Use a fresh ignored run directory for each arm; an existing lock or log is a
fail-closed refusal. Never clear a stale lock without checking the exact VM
in Nebius first. `check` is read-only; `arm` starts a detached Windows guard
and requires a durable `armed` event before the execution owner may start
the VM. The guard stops/polls the exact VM at its deadline. An unconfirmed
stop is urgent manual-console action, not success. Do not use `arm` until a
fresh balance/expiry, quota/capacity, full-rate, deadline, guest-backup, and
Jethro-approved numeric cap gate is satisfied. Windows must stay awake and
network/WSL authentication must remain available; the guest timer is backup.
The retained disk bills even after the VM stops. The September 29 real
read-only `check` returned zero and the VM remained `STOPPED`; no real arm or
stop was tested.
