# M3 Evaluator Containment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop an M3 evaluator and its Docker-client descendants on timeout/interruption, preserve truthful partial evidence, and keep any live run behind a separate VM watchdog and spending approval.

**Architecture:** Keep the fixed manifest, scheduler, and reporter. Make the default evaluator launcher own a new POSIX session/process group and pass its PID-derived container name through bounded cleanup. Treat process and Docker observations as local evidence, not a proof about outstanding Docker-daemon requests; a timeout/interruption always ends the mode.

**Tech Stack:** Python 3.11-compatible standard library (`subprocess`, `os`, `signal`, `threading`, `unittest`), pinned AllenAI harness `35f1200e`, Windows Python 3.11 for fake-runner tests, WSL Python 3.12 for real process/signal tests. No Nebius or real Docker in this plan.

---

## Scope, ownership, and review gates

**Accepted design:** `docs/superpowers/specs/2026-09-28-m3-evaluator-containment-design.md`. **Current branch:** `codex/m3-parallel-replay` in the existing managed worktree. **Baseline:** 172 tests pass with Windows Python 3.11. Do not create another worktree. Main checkout and viewer are separate; do not disturb them.

| Unit | Owner | Paths | Boundary |
| --- | --- | --- | --- |
| Process lifecycle and regression tests | smaller implementation agent | `scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py`, optionally a focused `tests/test_m3_posix_lifecycle.py` | Local only; no cloud, no real Docker |
| Independent safety/spec review | reviewer agent | read-only | Challenge late descendants, group reuse, Docker uncertainty, and direct interrupts |
| Integration, documentation, and Git | coordinator | `docs/experiments/m3-parallel.md`, `docs/codex-handoff/STATE.md`, `RUNBOOK.md`, `docs/decisions/` only if the accepted decision changes | Review, full suite, commit/merge decisions |

Implementation and review are sequential because the review requires the completed patch; documentation may proceed independently after the lifecycle contract settles. The coordinator alone integrates Git or operates Nebius. Green: tests, local code, docs. Amber: exact cleanup timing/observation semantics, reported at the checkpoint. Red: any change to cloud topology, spending cap, failure definition, or M3 workload—stop and ask Jethro. The existing design approval does not authorize a billable run.

## Task 1: Freeze the process-lifecycle regression

**Files:** Modify `tests/test_parallel_eval_driver.py`; create `tests/test_m3_posix_lifecycle.py` only if keeping real-OS tests separate makes the driver suite clearer.

- [ ] **Step 1: Add a real POSIX late-descendant test.** Skip unless `os.name == 'posix'`. A tiny parent script must spawn a child in the inherited group; the child sleeps ~0.5 seconds, then writes a marker. The parent exits on SIGTERM without reaping it. Invoke the real `_run_evaluator_safely` with a short timeout and fake `docker_runner` returning an empty `docker ps -a`; after cleanup and the child's delay, assert the marker does not exist. Use `sys.executable`, `tempfile.TemporaryDirectory`, `subprocess.Popen`, and `unittest.skipUnless`. In `finally`, kill the exact spawned group if needed so a failing test leaves no survivor. Do not call real Docker.
- [ ] **Step 2: Prove red on POSIX before fixing.** The existing managed worktree has no WSL `.venv`; WSL's `python3` is 3.12.3, and its current M3 driver suite passes 28 tests. From the repo root in WSL run `PYTHONPATH=src python3 -m unittest tests.test_m3_posix_lifecycle -v`; the old helper should report cleanup while the late marker appears. Do not replace this with a weaker fake-process test.
- [ ] **Step 3: Tighten fake contracts.** In `tests/test_parallel_eval_driver.py`, adjust fake process factories to accept `start_new_session=True`; assert the production launch requests it on POSIX. Add a fake group-signaling seam or mock `os.killpg` to verify TERM then KILL when the group remains, no group signal for an already-absent group, exact `vla-eval-{pid}` Docker removal, and inspection failure as uncertain. Keep existing stop-gate and no-third-launch tests.
- [ ] **Step 4: Commit only tests.** Run focused tests and `git diff --check`; stage the two test files only; commit `test(hpc): reproduce evaluator descendant escape`. The POSIX test is expected to fail until Task 2; state that explicitly in the commit message/body or checkpoint, not as a green result.

## Task 2: Own and stop the evaluator process group

**Files:** Modify `scripts/run_parallel_eval.py` near `_run_evaluator_safely` and its local cleanup helpers; modify focused tests if the injection seam requires it.

- [ ] **Step 1: Make production support explicit.** The default launcher must require POSIX (`os.name == 'posix'`) and call `process_factory(argv, cwd=cwd, start_new_session=True)`. Injected `command_runner` stays platform-neutral. Do not silently use parent-only `terminate()` on Windows. Record the evaluator PID and exact expected `vla-eval-{pid}` name in the attempt result or durable summary; never derive a broad container pattern.
- [ ] **Step 2: Implement bounded group shutdown.** Under the existing stop/launch gate, set `stop_event` before signaling. For a still-owned group, send `SIGTERM` with `os.killpg(process.pid, signal.SIGTERM)`, wait at most 20 seconds for graceful exit and group quiescence, send `SIGKILL` if it survives, and allow at most 5 further seconds for parent reap/group observation. Treat `ProcessLookupError` as absent; other signal or observation errors remain uncertain. Do not send a group signal after confirming the group is absent, and never substitute a system-wide process scan. Factor small helpers if needed to keep `_run_evaluator_safely` comprehensible.
- [ ] **Step 3: Keep Docker cleanup exact and observational.** After the group is quiescent or timed out, run bounded `docker ps -a --format '{{.Names}}'`, exact `docker rm -f vla-eval-{pid}` if present or inspection is uncertain, and inspect again. Mark cleanup locally observed only when parent is reaped, group is absent, and exact container is absent; otherwise retain a concrete `cleanup_error`. Do not state that two absent-container polls rule out an outstanding Docker-daemon request. Timeout/interruption still stops the mode even if observations pass.
- [ ] **Step 4: Verify and commit.** Run the focused Windows fake tests and WSL POSIX late-descendant test. Expected: all new tests green; `git diff --check` clean. Stage `scripts/run_parallel_eval.py` and related tests; commit `fix(hpc): contain evaluator process groups`.

## Task 3: Make interruption records and shutdown claims truthful

**Files:** Modify `scripts/run_parallel_eval.py`, `tests/test_parallel_eval_driver.py`.

- [ ] **Step 1: Add red interruption tests.** Inject a `KeyboardInterrupt` immediately after a real `executor.submit` returns but before `active[future]` assignment; assert the launched case remains in `in_flight_ids` or has a terminal record, and the mode is non-comparable. Inject an interruption during session setup before the first summary write; assert a durable interrupted/partial summary exists if a session directory was created. Add a real-OS CLI test that sends SIGTERM to a separate local runner process while a fake evaluator child is active; handler invocation alone is insufficient.
- [ ] **Step 2: Close the submission and setup gaps.** Register submitted futures atomically with in-flight identity, or conservatively retain an uncertain ID whenever an asynchronous exception can occur between submission and registration. Enclose session creation/initial save in interruption finalization, without converting a never-launched case into a completed result. Preserve every ambiguous launched attempt as `in_flight`, not valid.
- [ ] **Step 3: Correct boundedness language.** A `ThreadPoolExecutor.shutdown(wait=False)` does not force worker-thread exit. If all owned processes finish within the cleanup deadline, join executor threads; if they do not, write `interrupted_cleanup_risk` and make the CLI's incomplete state explicit. Do not claim a 90-second process-exit guarantee. Keep the independent VM watchdog as the billable-cost boundary.
- [ ] **Step 4: Verify and commit.** Run focused Windows tests, WSL real-signal tests, full Windows `unittest discover -s tests -q`, and `git diff --check`; stage only runner/tests; commit `fix(hpc): preserve interrupted replay ownership`.

## Task 4: Independent review, handoff, and pilot gate

**Files:** Modify `docs/experiments/m3-parallel.md`, `docs/codex-handoff/STATE.md`, `docs/codex-handoff/RUNBOOK.md`; update `FEEDBACK.md` only if a new firsthand tool observation exists, not for local-only speculation.

- [ ] **Step 1: Request read-only review after Task 3.** Give reviewer the accepted containment spec, pinned upstream `_exec_docker` link, exact diff, 172-test baseline, new POSIX reproduction, and acceptance criteria: no late child, no broad Docker cleanup, no silent retries, interrupted evidence non-comparable, no cloud call. Reconcile every Important finding before declaring local implementation ready; escalate architecture conflicts to Jethro.
- [ ] **Step 2: Re-run independent checks.** Windows: `$env:PYTHONPATH='src'; & C:\Windows\py.exe -3.11 -m unittest discover -s tests -q`. POSIX: `PYTHONPATH=src python3 -m unittest tests.test_m3_posix_lifecycle -v` inside WSL. Run `git diff --check`, inspect `git status --short`, and verify no secret or large artifact is staged. Report actual counts and any skipped platform tests.
- [ ] **Step 3: Update durable handoff.** Describe what is implemented, the observed containment test, the Docker-daemon residual uncertainty, and the rule to abort/stop VM after any ambiguous timeout. Correct the previous `cleanup_confirmed` interpretation and note that the independent watchdog is still required. Commit docs only as `docs(hpc): record M3 containment limits`.
- [ ] **Step 4: Present learning checkpoint.** Explain process group versus Docker daemon in plain language; show the test evidence and remaining risks. Do not start Nebius. The next red gate is a fresh Nebius preflight, external exact-VM stop watchdog, live full-resource/storage price and credit verification, calculated run-specific cap, and Jethro's explicit approval before a two-episode pilot.

## Completion boundary

Local completion requires green fake and real-POSIX tests, independent review without unresolved Important containment findings, and truthful partial records. This is **not** M3 completion: the accepted M3 benchmark still needs a separately approved 2-episode live pilot and equal 1/2/4-worker comparison. Neither local testing nor this plan authorizes provisioning or spending.
