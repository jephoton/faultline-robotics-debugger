# Multi-Job Diagnostic Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run several independent LIBERO Object task diagnoses through one bounded GPU evaluator queue and compare a sequential-job baseline with a shared adaptive portfolio locally, without claiming live speedup.

**Architecture:** Reuse `DiagnosticFlow` per job and the M3 durable `run_round` launcher once per global wave. A frozen portfolio manifest gives each task a unique identity and evidence directory. A pure planner gathers only ready requests, rotates fairly across jobs, and chooses one GPU's 1/2/4 worker count; the runner dispatches durable results back to the owning flow. No second GPU, new perturbation family, or viewer rewrite is included.

**Tech Stack:** Python 3.11 standard library, `unittest`, pinned GR00T/LIBERO evaluator, existing JSON evidence and exact-VM safety controls.

**Accepted direction:** [`2026-09-29-multi-job-diagnostics-design.md`](../specs/2026-09-29-multi-job-diagnostics-design.md), [`ADR 0009`](../../decisions/0009-portfolio-first-hpc.md). **Authority boundary:** local code and synthetic tests only. Task IDs, a live experiment, a numeric cloud cap, second family, cross-suite tasks, and public claims are separate gates. The former single-loop US$4 proposal is paused.

---

## Scope and file ownership

| File | Ownership |
| --- | --- |
| `scripts/run_failure_search.py` | Small explicit task/seed config parameters; retain old defaults. |
| `src/robot_debug/portfolio_manifest.py` | Frozen job identity, validation, hash, and JSON manifest. |
| `src/robot_debug/portfolio_policy.py` | Pure ready-work ordering, fairness, and admission against shared bounds. |
| `src/robot_debug/portfolio_runner.py` | Per-job flows, one global `run_round` per wave, durable summary; no Nebius API. |
| `scripts/run_diagnostic_portfolio.py` | CLI and injected evaluator boundary, separate fresh sequential/adaptive sessions. |
| `src/robot_debug/portfolio_report.py` | Cross-session comparability and claim guard. |
| `tests/test_portfolio_manifest.py`, `tests/test_portfolio_policy.py`, `tests/test_portfolio_runner.py`, `tests/test_portfolio_report.py`, `tests/test_failure_search_driver.py` | Red-first contract, adversarial, and integration tests. |
| `PROJECT_PLAN.md`, `docs/codex-handoff/STATE.md`, `docs/codex-handoff/RUNBOOK.md`, `FEEDBACK.md` | Update only for material verified results/provider interactions. |

Do not modify the historical M2/M4/M3 evidence, fixed M3 manifest, old single-job CLI, or viewer. M5's portfolio overview is a separate plan after this core produces a validated artifact contract.

## Task 1 — Prove task selection and freeze candidate identities (red checkpoint before live task choice)

- [ ] Read the pinned harness's LIBERO task-selection API and the current `_write_config` output. The existing writer fixes `suite: libero_object`, `seed: 7`, and `max_tasks: 1`; do not infer that changing `episode_indices` changes task ID. Record the exact supported config key and the task-index-to-instruction mapping in a short note under `docs/experiments/` without copying private artifacts. If task selection is unsupported by the pinned harness, stop dependent work and present the narrow adapter choices to Jethro.
- [ ] Write a failing `tests/test_portfolio_manifest.py` contract for exactly three *distinct* nonnegative task IDs, one frozen suite/checkpoint/family, unique safe job IDs, explicit seed, and stable hash independent of JSON key order. For example, `PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7, family="agentview_rect_occlusion")` must reject `(0, 0, 1)` and a suite other than `libero_object` in this plan.

```python
manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2),
                             seed=7, family="agentview_rect_occlusion")
assert tuple(job.task_id for job in manifest.jobs) == (0, 1, 2)
assert len({job.job_id for job in manifest.jobs}) == 3
with self.assertRaises(ValueError):
    PortfolioManifest(suite="libero_object", task_ids=(0, 0, 1),
                      seed=7, family="agentview_rect_occlusion")
```
- [ ] Run `C:\Windows\py.exe -3.11 -m unittest tests.test_portfolio_manifest -v`; expect failure from missing `portfolio_manifest` API, not a malformed test.
- [ ] Implement the immutable manifest and hash in `src/robot_debug/portfolio_manifest.py`; serialize with sorted JSON, reject bool/negative/duplicate task IDs and path-unsafe job IDs, and keep the exact selected task list in every session. Re-run the focused tests. Commit `feat(portfolio): freeze task job identities` with only source/test/note paths.
- [ ] Present the supported task catalog, current nominal evidence (only task 0 is proven), and two or three candidate tasks to Jethro. Jethro chooses the exact three task IDs before paid baseline screening or any task-specific product claim. A local synthetic fixture may use `(0, 1, 2)` strictly as fake IDs until then.

## Task 2 — Add explicit task selection without regressing old runs (green after API proof)

- [ ] Add a failing config-writer test in `tests/test_failure_search_driver.py` for a new explicit `task_id` argument and current unchanged default. Assert the generated YAML selects the requested task using the *verified pinned-harness key*, keeps `suite: libero_object`, `episodes_per_task: 1`, image recording, and separate output paths. Add a negative-ID rejection fixture.

```python
search._write_config(config_path=config, output_dir=output, project_root=project,
                     stage_name="task-1-nominal", episode_indices=(0,),
                     task_id=1, seed=7)
rendered = config.read_text(encoding="utf-8")
assert "suite: libero_object" in rendered
assert "episodes_per_task: 1" in rendered
assert "record_video: true" in rendered
# Assert the pinned harness's actual task-selector key, discovered in Task 1,
# selects task 1; max_tasks: 2 alone is NOT such a selector.
```
- [ ] Run `C:\Windows\py.exe -3.11 -m unittest tests.test_failure_search_driver -v`; expect only the new task-selection assertions to fail.
- [ ] Extend `scripts/run_failure_search.py::_write_config` with `task_id: int = 0` and `seed: int = 7`, validated as nonnegative integers. Emit the verified task-selection key while preserving byte-equivalent behavior for default calls where practical. Pass task/seed from the portfolio runner; do not change existing M2/M4 commands. Run writer and existing driver tests plus `git diff --check`. Commit `feat(libero): select frozen task per diagnostic job`.

## Task 3 — Pure shared-queue policy (amber; user checkpoint on priority/fairness)

**Decision before dependent implementation:** recommend work-conserving round-robin across eligible jobs, at most one search candidate per job per wave, and no more than four active evaluator processes on the existing one GPU. This is adaptive to *ready work and phase*, not an optimal or learned failure-probability scheduler. Compare it with whole-job-at-a-time execution. Jethro confirms or changes this scheduling rule before implementing Task 3; record the accepted rule in `docs/decisions/`.

- [ ] Write failing `tests/test_portfolio_policy.py` cases with ready queues `{"task-0": ("search-01", "search-02"), "task-1": ("confirm-01",), "task-2": ("nominal-01",)}`. Assert stable rotated first choices, no duplicate request, a four-slot maximum, no starvation of a continuously ready job across three waves, and zero work when shared episode/wall/dollar admission fails. A paused/invalid job must never be selected.

```python
ready = {"task-0": ("search-01", "search-02"),
         "task-1": ("confirm-01",), "task-2": ("nominal-01",)}
wave = choose_wave(ready, cursor=0, slots=4,
                   bounds=PortfolioBounds(episode_slots=4,
                                          seconds_left=180, dollars_left=0.1))
assert len(wave.requests) <= 4
assert {item.job_id for item in wave.requests} == set(ready)
assert len({(item.job_id, item.case_id) for item in wave.requests}) == len(wave.requests)
```
- [ ] Run the focused policy tests; verify a missing API failure. Implement immutable `PortfolioChoice(job_id, case_id, reason)` and `choose_wave(ready_by_job, cursor, slots, bounds)` in `src/robot_debug/portfolio_policy.py`. Make cursor and bounds explicit inputs/outputs; never inspect mutable global state. Re-run tests. Commit `feat(hpc): choose fair bounded portfolio waves`.
- [ ] Use existing `choose_workers` for 1/2/4 concurrency after `choose_wave` fixes the ready set. Record the measured timing source and selection reason; full VM rate is charged once per elapsed hour, not once per worker.

## Task 4 — Durable portfolio runner and CLI (amber; one execution owner)

- [ ] Write failing `tests/test_portfolio_runner.py` with an injected fake evaluator and three fake tasks. Assert job-prefixed case IDs/output directories, one global `run_round` call per wave, a shared maximum of four active evaluators, stable result routing despite out-of-order completion, each job's independent flow/ledger, and no output collision. Use distinct fixture outcomes so a task-0 failure cannot advance task-1 confirmation.

```python
summary = run_portfolio(manifest=fake_manifest, mode="adaptive-portfolio",
                        results_root=fresh_root, evaluator=fake_evaluator,
                        limits=PortfolioLimits(episodes=100, seconds=600,
                                               estimated_usd=10, hourly_rate=1))
assert len(summary["jobs"]) == 3
assert summary["max_observed_evaluators"] <= 4
assert summary["jobs"]["task-1"]["flow"]["selected_search_id"] is None
```
- [ ] Add interruption, evaluator-timeout, invalid-evidence, task-baseline-failure, and exhausted-budget cases. Assert no certification from missing results, a partial portfolio summary, no unsafe automatic resume, and durable physical attempts from ledger launch intent rather than only completed results. The existing POSIX SIGTERM child-containment test must still pass.
- [ ] Run red tests, then implement `src/robot_debug/portfolio_runner.py` around per-job `DiagnosticFlow` instances. For each wave: gather `pending()` from eligible jobs; ask the pure policy for ready requests; build `RoundRequest` with globally unique `job--case` IDs; write configs with frozen task/seed; run one shared `run_round`; persist its ledger and results; route only terminal-valid outcomes to the owning controller; atomically write each job and portfolio summary. Match the current `DiagnosticFlow.apply_round` contract: confirmation needs exactly five valid outcomes and reduction gates may need a second wave. If a job's logical gate spans waves, buffer only its own ordered results until the full gate input exists.
- [ ] Add `scripts/run_diagnostic_portfolio.py` with required manifest path, fresh ignored results root, `--mode sequential-jobs|adaptive-portfolio`, episode/wall/estimated-dollar bounds, and `--dry-run`. Reject existing session directories. Production evaluator wiring must reuse `_run_evaluator_safely` and M3's exact launch sidecars; do not create a second subprocess implementation. Run focused tests and all existing diagnostic/parallel driver tests. Commit `feat(portfolio): orchestrate isolated jobs on one GPU`.

## Task 5 — Comparison report and claim guard (green)

- [ ] Write failing `tests/test_portfolio_report.py` for matched modes, task-order drift, config/family/seed/model mismatch, missing per-job evidence, infrastructure-invalid jobs, and synthetic timing. Require `comparable=false` for a contract mismatch and `speedup=null` for fake runs or outcome drift. Count successful reports, no-failure jobs, and budget-exhausted jobs separately.

```python
report = compare_portfolios(sequential_summary, adaptive_summary)
assert report["same_manifest"] is True
assert report["speedup"] is None  # Both summaries are synthetic.
assert report["billed_cost_usd"] is None
assert sum(report["job_status_counts"].values()) == 3
```
- [ ] Implement `src/robot_debug/portfolio_report.py::compare_portfolios(sequential, adaptive)` to validate frozen manifest hashes and durable job summaries, then report time to first reproducible/reduced report, count of valid reduced reports, task coverage, physical/valid attempts, per-job statuses, speculative work, and warm elapsed estimates. Full VM allocation and posted billed cost remain `null` without lifecycle/billing records; no per-job dollars should be presented as an invoice. Run focused tests and commit `feat(portfolio): compare budget-matched diagnostic queues`.

## Task 6 — Local acceptance, handoff, and later cloud gate (green/red separated)

- [ ] Run `C:\Windows\py.exe -3.11 -m unittest discover -s tests -v`, the focused WSL POSIX lifecycle/driver tests, `git diff --check`, and two fresh fake CLI sessions with the same manifest and budgets. Inspect JSON by hand: all three jobs retain distinct evidence; sequential and portfolio modes obey the same total physical-attempt/wall/dollar ceilings; differing decisions or task outcomes suppress a speedup claim. Synthetic speedup is never a product claim.
- [ ] Update `docs/codex-handoff/STATE.md`, `RUNBOOK.md`, and the M3/M5/M6 rows of `PROJECT_PLAN.md` with verified commands and limitations. Do not add provider praise to `FEEDBACK.md` without a new provider interaction. Commit `docs(portfolio): record local multi-job readiness` and integrate only after independent evidence/safety review.
- [ ] Separately propose task-baseline screening and a live sequential-versus-portfolio experiment to Jethro, with exact task IDs, nominal validity gate, current balance/price/quota/capacity, one exact VM, watchdog, disk retention, numeric cap/deadline, and honest comparison metrics. **No VM start or extra GPU is authorized by this plan.** If exact-shape regular capacity still shows zero, defer without changing to preemptible or a different shape silently.

## Dependency, agent, and review map

Task 1's harness/API proof precedes Task 2 and task-specific live work. Task 3's scheduler rule is a user checkpoint. After those gates, Task 2 config integration and Task 3 pure policy are independent: give separate smaller-model agents exclusive source/test files, with the strong-model coordinator owning API reconciliation. Task 4 depends on both and has one builder because the shared ledger, evaluator containment, and result routing are tightly coupled. Task 5 can begin against frozen fixture summaries while Task 4 is built, with exclusive report/test ownership. The coordinator owns integration, independent safety review, Git publication, and all Nebius lifecycle actions. Review after Tasks 2–3 and again after Tasks 4–5. Green steps proceed autonomously; bounded runner structure is amber and explained at review; task IDs, scheduling rule, cloud cap, new family/suite, and outcome claims are red.

## Completion boundary

This plan ends with a locally working, fail-closed multi-job artifact contract and a fake sequential/adaptive comparison. It does not prove the GR00T checkpoint can complete the two additional tasks, that the cloud scheduler improves useful reports per dollar, or that other suites/families work. Those need separately approved live experiments. M5's portfolio viewer consumes this contract in its own design/implementation plan.
