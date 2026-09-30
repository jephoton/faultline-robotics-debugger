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

- [x] Read the pinned harness's LIBERO task-selection API and the current `_write_config` output. The original writer fixed `suite: libero_object`, `seed: 7`, and `max_tasks: 1`; changing `episode_indices` does not change task ID. [`m3-task-selection-contract.md`](../../experiments/m3-task-selection-contract.md) records the pinned harness's prefix-only behavior and the approved local exact-ID adapter. The local LIBERO runtime needed to enumerate task instructions is unavailable, so no catalog has been invented.
- [x] Write a failing `tests/test_portfolio_manifest.py` contract for exactly three *distinct* nonnegative task IDs, one frozen suite/checkpoint/family, unique safe job IDs, explicit seed, and stable hash independent of JSON key order. For example, `PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2), seed=7, family="agentview_rect_occlusion")` must reject `(0, 0, 1)` and a suite other than `libero_object` in this plan.

```python
manifest = PortfolioManifest(suite="libero_object", task_ids=(0, 1, 2),
                             seed=7, family="agentview_rect_occlusion")
assert tuple(job.task_id for job in manifest.jobs) == (0, 1, 2)
assert len({job.job_id for job in manifest.jobs}) == 3
with self.assertRaises(ValueError):
    PortfolioManifest(suite="libero_object", task_ids=(0, 0, 1),
                      seed=7, family="agentview_rect_occlusion")
```
- [x] Run `C:\Windows\py.exe -3.11 -m unittest tests.test_portfolio_manifest -v`; it initially failed because the `portfolio_manifest` API did not exist.
- [x] Implement the immutable manifest and hash in `src/robot_debug/portfolio_manifest.py`; serialize with sorted JSON, reject bool/negative/duplicate task IDs and path-unsafe job IDs, and keep the exact selected task list in every session. Focused tests pass and commit `feat(portfolio): freeze task job identities` (`9704e5a`) contains only source/test/note paths.
- [x] Presented the supported task catalog and nominal evidence (only task 0 is proven). Jethro approved `(0, 1, 2)` on September 30 as candidates for a bounded nominal compatibility screen; see [`m3-task-selection-contract.md`](../../experiments/m3-task-selection-contract.md). Pinned-source inspection provisionally maps IDs 1/2 to cream cheese/salad dressing basket tasks. The actual image and GR00T outcomes remain unchecked, and paid screening still requires a separate numeric cap. No task-specific success claim follows from the candidate choice.

## Task 2 — Add explicit task selection without regressing old runs (green after API proof)

- [x] Add failing fake-upstream adapter and config-writer tests for exact `task_id`, unchanged default, original upstream ID preservation, and invalid-ID rejection. The local adapter consumes `params.task_id`; it is not an upstream constructor key.

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
- [x] Ran focused tests red first, then extended `DiagnosticLIBEROBenchmark.get_tasks()` and `scripts/run_failure_search.py::_write_config` with validated exact task and seed. Existing M2/M4 calls retain their defaults. Focused tests and the full Windows Python 3.11 suite pass (309 tests, 4 skips); `git diff --check` passes. Commits: `a9cc776 feat(libero): select exact diagnostic task` and `f0d7c34 feat(runner): write exact task selection in configs`. Passing task/seed from the future portfolio runner remains Task 4.

## Task 3 — Pure shared-queue policy (amber; user checkpoint on priority/fairness)

**Accepted rule:** Jethro approved work-conserving round-robin across eligible jobs, at most one ready episode per job per wave, rotating the first job, and no more than four active evaluator processes on the existing one GPU. This is adaptive to *ready work and phase*, not an optimal or learned failure-probability scheduler. Compare it with whole-job-at-a-time execution. The rationale is recorded in [`ADR 0009`](../../decisions/0009-portfolio-first-hpc.md).

- [x] Wrote red-first `tests/test_portfolio_policy.py` cases for stable rotated first choices, no duplicate request, a four-slot maximum, no starvation under fixed or changing readiness, zero work when shared episode/wall/dollar admission fails, and paused/non-ready exclusion. Every wave must retain the full frozen manifest job-key set; malformed input fails closed. Independent spec and quality reviews passed after the changing-readiness fairness fix.

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
- [x] Implemented immutable `PortfolioBounds`, `PortfolioChoice`, and `PortfolioWave`, with pure `choose_wave(ready_by_job, cursor, slots, bounds)` and explicit cursor/bounds. Focused tests passed 6/6; full Windows Python 3.11 suite passed 315 tests (4 skips). Commits `397bbaa feat(hpc): choose fair bounded portfolio waves` and `313577b fix(hpc): prevent dynamic-readiness starvation`.
- [x] The Task 4 runner calls existing `choose_workers` after `choose_wave` fixes the ready set, records the choice, and applies one shared VM hourly-rate bound. With only three jobs and one ready episode per job, the first portfolio can select at most two workers; a four-worker wave is not manufactured.

## Task 4 — Durable portfolio runner and CLI (amber; one execution owner)

- [x] Wrote red-first `tests/test_portfolio_runner.py` with injected fake evaluator and three fake tasks. It covers job-prefixed case IDs/output directories, one global `run_round` per wave, a shared evaluator bound, stable routing, each job's independent flow/ledger, and no output collision.

```python
summary = run_portfolio(manifest=fake_manifest, mode="adaptive-portfolio",
                        results_root=fresh_root, evaluator=fake_evaluator,
                        limits=PortfolioLimits(episodes=100, seconds=600,
                                               estimated_usd=10, hourly_rate=1))
assert len(summary["jobs"]) == 3
assert summary["max_observed_evaluators"] <= 4
assert summary["jobs"]["task-1"]["flow"]["selected_search_id"] is None
```
- [x] Added interruption, evaluator-timeout, invalid-evidence, task-baseline-failure, and exhausted-budget cases. Partial summaries do not certify, and ledger-derived physical attempts distinguish launches from valid results. The focused POSIX lifecycle/driver tests pass (66).
- [x] Implemented `src/robot_debug/portfolio_runner.py` around per-job `DiagnosticFlow` instances, globally unique requests, one shared `run_round` per wave, atomic summaries, validated launch accounting, and per-job ordered gate buffering.
- [x] Added `scripts/run_diagnostic_portfolio.py` with the required manifest, fresh results root, both modes, bounds, and synthetic dry run. It reuses `_run_evaluator_safely` and the existing sidecars, rejects existing sessions, and validates exact task/episode plus nonempty aggregate, trace, and MP4 evidence. Focused tests pass.

## Task 5 — Comparison report and claim guard (green)

- [x] Wrote red-first `tests/test_portfolio_report.py` for matched modes, manifest drift, malformed accounting, missing evidence, invalid jobs, synthetic timing, and paired tampering of flow/status/timestamps. Contract mismatches and unsupported timing suppress speedup.

```python
report = compare_portfolios(sequential_summary, adaptive_summary)
assert report["same_manifest"] is True
assert report["speedup"] is None  # Both summaries are synthetic.
assert report["billed_cost_usd"] is None
assert sum(report["job_status_counts"].values()) == 3
```
- [x] Implemented `compare_portfolios` with manifest and job-flow replay validation, outcome/decision drift, wave-ledger launch reconciliation, status/phase-timing checks, and a complete-live-session gate for warm speedup. Full VM allocation and posted billed cost remain `null`. An independent claim-safety review approved the final guard.

## Task 6 — Local acceptance, handoff, and later cloud gate (green/red separated)

- [x] With `PYTHONPATH=src`, Windows Python 3.11 full discovery passed 344 tests (four POSIX-only skips); focused WSL POSIX lifecycle/driver passed 66; `git diff --check` passed. A paired fresh fake-CLI test used the same manifest/bounds for both modes, confirmed three separate jobs and physical-attempt ceiling, and found no synthetic speedup claim.
- [x] Updated `docs/codex-handoff/STATE.md`, `RUNBOOK.md`, and the M3/M5/M6 roadmap text with verified commands and limitations. No provider feedback was invented. Independent report claim-safety review approved; integration follows final branch checks.
- [ ] Separately propose task-baseline screening and a live sequential-versus-portfolio experiment to Jethro, with exact task IDs, nominal validity gate, current balance/price/quota/capacity, one exact VM, watchdog, disk retention, numeric cap/deadline, and honest comparison metrics. **No VM start or extra GPU is authorized by this plan.** If exact-shape regular capacity still shows zero, defer without changing to preemptible or a different shape silently.

## Dependency, agent, and review map

Task 1's harness/API proof precedes Task 2 and task-specific live work. Task 3's scheduler rule is a user checkpoint. After those gates, Task 2 config integration and Task 3 pure policy are independent: give separate smaller-model agents exclusive source/test files, with the strong-model coordinator owning API reconciliation. Task 4 depends on both and has one builder because the shared ledger, evaluator containment, and result routing are tightly coupled. Task 5 can begin against frozen fixture summaries while Task 4 is built, with exclusive report/test ownership. The coordinator owns integration, independent safety review, Git publication, and all Nebius lifecycle actions. Review after Tasks 2–3 and again after Tasks 4–5. Green steps proceed autonomously; bounded runner structure is amber and explained at review; task IDs, scheduling rule, cloud cap, new family/suite, and outcome claims are red.

## Completion boundary

This plan ends with a locally working, fail-closed multi-job artifact contract and a fake sequential/adaptive comparison. It does not prove the GR00T checkpoint can complete the two additional tasks, that the cloud scheduler improves useful reports per dollar, or that other suites/families work. Those need separately approved live experiments. M5's portfolio viewer consumes this contract in its own design/implementation plan.
