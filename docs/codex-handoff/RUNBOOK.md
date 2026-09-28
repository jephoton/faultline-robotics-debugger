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

Verified after the local M3 implementation/spec review: 172 tests pass with
Windows Python 3.11. This does not validate Docker descendant containment.

Also run `git diff --check` before committing. Use Conventional Commit
messages and stage only task-related paths.

## Cloud safety

Before any Nebius start, confirm authentication, tenant/project, balance,
expiry, GPU quota/capacity, exact rates, VM state, and the user-approved cap.
Arm independent cleanup, copy evidence before media, and verify the VM is
stopped and temporary network rules are absent after every attempt.
Do not start the M3 live session merely because local tests pass: its runner
still needs a containment decision, an external VM-stop watchdog, and a
separately approved run-specific cap. After any uncertain timeout or
interruption, stop and verify the exact VM before another mode; do not rely
on a momentary absent-container check.
