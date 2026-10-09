# Serverless Model Process Implementation Plan

> **For agentic workers:** Use subagent-driven-development with independent
> spec then quality review. Steps use checkbox syntax for tracking.

**Goal:** Supply the real POSIX model-process lifetime required by the reviewed
injectable workload, using CPU fixtures before any model weights or GPU run.

**Architecture:** One owned process group runs a trusted, explicit argv. Readiness
requires process liveness and a valid local WebSocket HTTP upgrade, not merely a
listening port. Model and evaluator share the already tested bounded cleanup
primitive; factories, model caches and the production CLI remain separate.

**Tech Stack:** Python standard library compatible with Python 3.8, sockets,
subprocess, POSIX signals, unittest and actual CPU child-process fixtures.

## Accepted boundary, ownership and dependencies

This is a green/amber implementation detail of Task 2 in the accepted October 6
migration design, not a new policy, algorithm, deployment or spend decision.
Root owns integration, documentation, Docker and all external resources. One
smaller capable builder owns only `src/robot_debug/job_process.py`, new
`src/robot_debug/job_model.py`, and new `tests/test_job_model.py`, in a clean
attached worktree. Existing process tests may be edited only to add regressions
or update an internal helper seam without weakening their assertions.
Map: model builder || root native-image inspection -> spec -> quality -> root
integration. Do not overlap the separate workload/image builders' files.
No package installation, downloads, Docker, cloud, secrets, GPU or Git push.

## Interfaces and required behavior

Extract the existing `DirectEvaluator._terminate_and_confirm` implementation to
a shared public function without changing its behavior; keep the method as a
delegating compatibility wrapper and keep all existing POSIX tests passing:

```python
def close_owned_process_group(process, process_group, *,
                              term_grace_seconds=5.0,
                              kill_grace_seconds=2.0):
    ...
```

It accepts only POSIX execution, ordinary nonnegative finite grace values no
greater than five/two seconds, and the owned group's positive PID. Existing
TERM/KILL, leader reaping, adopted-orphan reaping, group-absence confirmation
and deferred SIGINT semantics stay intact. Never return success on uncertainty.
Do not introduce a second unbounded cleanup implementation.

The model wrapper's constructor must not launch a process:

```python
class ModelProcess:
    def __init__(self, *, argv, cwd, env, log_root, port=8000): ...
    def start(self): ...
    def check_alive(self): ...
    def wait_ready(self, *, deadline): ...
    def close(self): ...
```

`argv` is a nonempty ordinary sequence of nonempty NUL-free strings, first
argument an absolute executable path; `cwd` is an existing ordinary directory,
`env` a copied string mapping and `log_root` a trusted ordinary local path.
Never accept shell text or derive argv/environment from workload JSON. Validate
port as an ordinary integer in 1..65535; production wiring keeps 8000, CPU tests
use an ephemeral loopback port. Refuse non-POSIX `start` before subprocess use.

`start` is single-use, `shell=False`, `start_new_session=True`, stdin DEVNULL,
exclusive UUID-named stdout/stderr files under log_root, no pipes or environment
dump. Close file descriptors even when spawn fails. Retain ownership of a
started process until successful `close`; never relaunch after failure.
`check_alive` raises `InfrastructureError` for absent/exited leader, including
exit zero. `close` is safe before start and idempotent after successful closure;
otherwise use the shared cleanup and raise on uncertainty. An already exited
leader does not make surviving descendants safe. Files close after group
closure, and the wrapper must remain safely closeable after a failed start or
readiness operation. Diagnostics contain fixed messages, not supplied argv/env.

`wait_ready` validates a finite absolute monotonic deadline, checks liveness
before each attempt and after a successful upgrade, and refuses expired time.
Use a fresh TCP socket to 127.0.0.1 and `GET / HTTP/1.1`, Host with configured
port, Upgrade websocket, Connection Upgrade, random base64 16-byte
Sec-WebSocket-Key, Sec-WebSocket-Version 13. Validate status 101, case-insensitive
Upgrade websocket, Connection's comma-separated Upgrade token, and exactly one
Sec-WebSocket-Accept matching SHA1(key+RFC6455 GUID), base64 encoded.
Bound headers to 16 KiB. Require the CRLF header terminator; reject duplicate
critical headers, wrong accept, HTTP 200, malformed/status-only responses and
oversized headers. Always close the probe socket. No inference or binary policy
messages are sent, and upgrade alone makes no CUDA/model-quality claim.

Connection refusal, partial/malformed upgrades and temporary socket errors may
retry only inside this one readiness deadline; dead model never retries.
Every connect/send/recv operation uses timeout <=min(1 second, current remaining
time). Recheck time before each blocking call and after header/liveness checks;
slow byte drips must not refresh the absolute deadline. Backoff is <=0.1 second
and remaining time. On expiration raise a fixed InfrastructureError; caller
owns subsequent close. Never rewrite the workload's absolute deadline.

## TDD tasks and atomic commits

- [ ] Add a failing import plus real POSIX lifetime fixture before extraction.
  Use the existing tests/test_job_process.py subreaper/owned-group teardown
  pattern; every fixture must clean only its own groups even on assertion failure.

```python
model = ModelProcess(argv=[sys.executable, str(fixture)], cwd=root,
                     env=dict(os.environ), log_root=root / 'logs', port=port)
model.start()
model.check_alive()
model.close()
model.close()
self.assertIsNotNone(model_process_exit_marker.read_text())
```

- [ ] Run focused suite and observe missing-module failure, then extract the
  existing cleanup primitive and implement lifetime ownership. Test real normal
  leader, early exit zero/nonzero, startup exception, refused repeated start,
  orphan child, TERM-ignoring child requiring KILL, cleanup uncertainty and SIGINT
  during cleanup. Do not certify process absence through mocks alone.
- [ ] Run existing process suite plus new lifetime cases before
  `refactor(jobs): share bounded owned-process cleanup`. Stage only the shared
  helper change and its related tests; do not commit a half-working model module.
- [ ] Add actual loopback HTTP fixtures for valid WebSocket upgrade, HTTP200,
  wrong/missing/duplicate accept, comma/case header handling, truncated/oversize
  headers, refused port, delayed and slow-drip responses, dead child during wait
  and deadline already passed. Socket server fixture threads have bounded joins
  and clean their own sockets. Observe RED before implementing readiness.

```python
model.wait_ready(deadline=time.monotonic() + 0.5)
model.check_alive()
# For a wrong accept or endless drip, assert InfrastructureError and elapsed
# within the absolute bound plus a small scheduling allowance, then close.
```

- [ ] Run new and existing suites on Windows (explicit POSIX skips, constructor
  guards still tested) and WSL (real process/socket cases required):

```powershell
$env:PYTHONPATH='src'
& C:/Windows/py.exe -3.11 -B -m unittest tests.test_job_model tests.test_job_process -v
```

```sh
PYTHONPATH=src python3 -B -m unittest tests.test_job_model tests.test_job_process -v
```

- [ ] Check Python3.8 grammar compatibility and `git diff --check`, then commit
  only owned files as `feat(jobs): bound model startup readiness and shutdown`.
- [ ] Independent spec review then quality review, including true deadline and
  process-absence evidence. Fix reproduced gaps and re-review exact SHA before
  root integration and handoff updates.

## Acceptance and next boundary

Acceptance here establishes real CPU process ownership and WebSocket readiness
only. It does not acquire/check pinned Hugging Face snapshots, build production
argv, install/render/infer GR00T, implement the final CLI or whole-workload
SIGTERM/export deadline, create a Job, or complete M5. Those remain in the
approved migration plan. Root self-review: scope, API names, deadline protocol,
file ownership, tests, review stages and no-spend gates match this increment.
