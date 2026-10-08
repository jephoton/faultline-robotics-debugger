# Faultline verified project runbook

> Generated operational context. Commands are relative to the repository root.

## Local environment

The repository uses a Linux virtual environment at `.venv/` under WSL. Set the
source path for direct module execution:

```bash
export PYTHONPATH=src
```

## Viewer

Faultline is the official name. Updated package installs expose
`faultline-viewer`; the existing `robot-debug-viewer` command is retained as
a compatibility alias. Direct `robot_debug.viewer.server` module commands
below remain valid. The GitHub repository is now
`https://github.com/jephoton/faultline-robotics-debugger`; the local directory
remains `nebius-nvidia-hackathon`.

Confirm the configured remote without changing it:

```powershell
git remote get-url origin
```

Current Windows main viewer with registered case explanations:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
C:/Windows/py.exe -3.11 -m robot_debug.viewer.server --artifacts artifacts --cases artifacts/cases --host 127.0.0.1 --port 8765
```

Reports are local immutable sidecars; opening or refreshing the viewer never
calls the provider. An absent interpretation is an honest factual fallback,
not a successful model explanation. API checks do not replace visual browser QA.

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
the benchmark reporter. The September 29 live pilot passed and its copied
evidence is under ignored `artifacts/m3-pilot-live-20260929/`; do not rerun
without a new cap and refreshed resource preflight.

The separately approved full M3 comparison also completed September 29.
Its ignored source evidence is under `artifacts/m3-comparison-20260929/`;
`evaluation/m3_comparison.md` is the no-cost fail-closed report and
`warm-cost-report/m3_comparison.md` allocates compute-only warm-mode cost.
See `docs/experiments/m3-parallel.md` before interpreting either report.
The viewer health endpoint returned `ok` and its catalog indexed the new
episodes. The VM was stopped and its temporary SSH ingress removed.

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
read-only `check` returned zero. The guard was then armed for the approved
pilot, and the VM was independently stopped after results were copied. Its
retained disk remains billable; decide retention within the approved window.
Before the full comparison, a plain detached guard disappeared without a
terminal log event. A Windows Task Scheduler-owned process running the same
exact-VM `watch` command remained `Running` throughout that session; the
task was stopped and unregistered only after `STOPPED` was independently
verified. Treat process liveness as a pre-start gate on any future session,
and re-authenticate the CLI before starting: one M3 start request reached
Nebius just as local OAuth expired and had to be stopped through the console.

## Adaptive diagnostic loop (local validation only)

The new `scripts/run_diagnostic_loop.py` connects the existing position-grid
search, five-replay confirmation, and rectangle reduction to the one-GPU
1/2/4-evaluator scheduler. `sequential` uses one worker; `adaptive` chooses
bounded concurrency from the recorded M3 warm timing table. Both require a
fresh results directory, explicit episode/wall/dollar bounds, and the same
frozen scenario contract. A dry run uses synthetic outcomes and writes fake
evidence; it does **not** evaluate GR00T or measure cloud speedup.

```powershell
$env:PYTHONPATH = 'src'
& 'C:\Windows\py.exe' -3.11 scripts/run_diagnostic_loop.py `
  --upstream-root . --project-root . --results-root '<fresh-ignored-results-root>' `
  --policy sequential --launch-cutoff-seconds 600 --episode-limit 100 `
  --hourly-rate-usd 1 --max-estimated-usd 10 --dry-run
```

Use the same command with `--policy adaptive` and the same results root to
create the second synthetic session. `robot_debug.diagnostic_report.compare_sessions`
accepts their decoded `session_summary.json` objects. It can establish logical
agreement, but returns no warm speedup for dry runs. The saved report distinguishes
extra speculative attempts from outcome drift. Real results require the pinned
Linux evaluator/model environment, a refreshed cloud preflight, an independent
exact-VM stop guard, and a separately approved cap. Local code readiness is not
permission to start a VM.

Verified before local integration into `main`: Windows Python 3.11 full discovery passes 298
tests with four POSIX-only skips. The focused WSL POSIX suite passes 92 tests:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_parallel_eval_driver tests.test_diagnostic_round \
  tests.test_diagnostic_loop_driver tests.test_diagnostic_report -q
```

The POSIX suite includes a real CLI SIGTERM sent while an evaluator child is
active; it verifies a partial session and an absent evaluator PID afterward.
Docker-daemon request quiescence still cannot be proven by a local process
test. `elapsed_seconds` and `warm_diagnostic_estimate_usd` cover only the
diagnostic window, not VM allocation/startup/shutdown. Full allocation and
posted billed costs remain unknown until lifecycle and billing evidence is
captured and reconciled.

## Multi-job portfolio (local synthetic validation)

The manifest must contain exactly three distinct `libero_object` task IDs,
one seed, one perturbation family, and the pinned model identity. Task IDs
`[0, 1, 2]` are **synthetic test identities only** until the selected live
tasks have passed nominal screening and Jethro has approved them. Save the
following as a manifest in an ignored scratch directory:

```json
{
  "suite": "libero_object",
  "task_ids": [0, 1, 2],
  "seed": 7,
  "family": "agentview_rect_occlusion",
  "checkpoint_id": "nvidia/gr00t17-lerobot-libero_object-640",
  "checkpoint_revision": "1499db357f6ca3762b56c2e8c00b530eb9a09444"
}
```

From the repository root, run once per mode with different fresh ignored
results roots. `--dry-run` uses fake successful outcomes; it exercises
routing/accounting but cannot measure GR00T or justify a speedup claim.

```powershell
$env:PYTHONPATH = 'src'
& 'C:\Windows\py.exe' -3.11 scripts/run_diagnostic_portfolio.py `
  --manifest '<ignored-manifest.json>' --mode sequential-jobs `
  --results-root '<fresh-ignored-sequential-root>' --upstream-root . `
  --project-root . --episodes 3 --seconds 600 --estimated-usd 10 `
  --hourly-rate 1 --dry-run
```

Repeat with `--mode adaptive-portfolio` and a different fresh results root.
Decode each `portfolio_summary.json` and pass the two mappings to
`robot_debug.portfolio_report.compare_portfolios`. The report requires
complete, matched live sessions with reconciled wave ledgers before it shows
a warm diagnostic speedup. Neither this estimate nor the hourly-rate bound
is a posted cloud bill. Before removing `--dry-run`, verify the pinned Linux
evaluator, exact task selection, and actual served model ID/revision on the
intended cloud environment. The manifest rejects other checkpoint labels,
but cannot prove what a separate localhost model server loaded. Obtain a
fresh numeric spend cap and satisfy the cloud safety gates above. The
portfolio CLI has **not** yet been run on Nebius. The M5 viewer does not yet
consume portfolio summaries.

Final local acceptance on September 30: Windows Python 3.11 full discovery
passed 344 tests (four POSIX-only skips); focused WSL lifecycle/driver
passed 66; paired fresh synthetic CLI sessions passed and produced no
speedup claim. The report's claim guard passed an independent review.
