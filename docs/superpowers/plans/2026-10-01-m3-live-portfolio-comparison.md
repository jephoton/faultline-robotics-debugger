# M3 Live Three-Task Portfolio Comparison Execution Plan

> **For agentic workers:** Use executing-plans for the root-owned live lifecycle. A smaller-model agent performs independent local evidence/claim review; it never mutates cloud resources. Steps use checkboxes for tracking.

**Goal:** Recover all available videos and traces from matched sequential-job and adaptive-portfolio find → confirm → reduce sessions, and report the measured comparison only when its validity gates pass.

**Architecture:** Recreate the successful snapshot-backed, single-H100 setup with one shared GR00T server, without changing the policy, task adapter, simulator, recording, diagnostic flow, or evidence schema. Run one fresh sequential session followed by one fresh adaptive session on that same allocation, bounded to two evaluators. Root alone owns spending, lifecycle, transfer, integration, and publication.

**Tech Stack:** Existing Python 3.11 portfolio CLI/reporter, pinned GR00T N1.7 LIBERO checkpoint, pinned simulator container, Nebius CLI, Windows Task Scheduler exact-VM watchdog, guest shutdown backup, JSON/JSONL and MP4 evidence.

## Authority and cost boundary

- Jethro requested autonomous execution through the full comparison and media recovery, minimal configuration changes, bug documentation, and Git push. The working code/documents through `b4b43c4` were pushed and remote main was read back at that exact commit.
- **Approved by Jethro:** US$8 total attributable to this attempt, one H100 start, maximum 90 minutes from start request through stop. Previous US$6 nominal-screen authority is exhausted.
- The October 1 console displays US$8.52, active account, no expiry displayed. This is a fresh balance observation, not reconciliation of all prior invoices. Recheck before mutation and account for identifiable pending charges; do not assume delayed posting means free compute.
- At US$4.50/hour, 90 minutes compute is US$6.75 pre-tax / US$7.3575 with assumed 9% tax. Bounding snapshot, clone disk, and original disk accrual attributable to the attempt to three hours each adds about US$0.191 with that tax assumption: approximately US$7.55 total, leaving about US$0.45 cap headroom. Refresh actual prices and taxes; stop before creation if the conservative bound no longer fits.
- Copy continuously, stop early when done, and delete only temporary VM/managed disk and snapshot immediately after verified stop and evidence recovery, no later than three hours from snapshot creation. This does not authorize deleting the original VM/disk or extending their existing retention. If evidence copy is blocked, recover compact evidence before the deadline and honor approved cleanup; report any lost media honestly.
- The total intended credit envelope remains US$75. No account switch, additional GPU, automatic restart, unbounded retry, or top-up is authorized.

## Frozen experimental contract

Use exactly the nominal screen's manifest: LIBERO Object task IDs 0/1/2, seed 7, reset index 0, `agentview_rect_occlusion`, checkpoint `nvidia/gr00t17-lerobot-libero_object-640`, revision `1499db357f6ca3762b56c2e8c00b530eb9a09444`. Preserve the eight ordered 25%-area grid cells, five confirmation replays, reduction sentinel, current parent gate, 12 candidate-attempt budget, and five fresh nominal controls. A task may validly finish without finding a failure; do not increase masks or change the family to manufacture one.

Both sessions receive identical limits: **111 physical attempts, 1800 seconds, US$2.25 warm compute allowance, US$4.50/hour** at the currently verified rate. The conservative per-task ceiling is 1 nominal + 8 search + 5 confirmation + 1 sentinel + 5 parent + 12 candidate + 5 control = 37; three tasks allow 111, two modes at most 222. Many paths stop earlier. CLI exit 1 alone is not an infrastructure failure: inspect terminal status/accounting, as the CLI requires every task certified even when valid no-failure results exist.

Sequential runs whole jobs one at a time. Adaptive uses `--max-workers 2`, the accepted round-robin ready-job policy, and the existing selector. Its historical L40S timing table is an explicitly labeled admission heuristic, **not H100 calibration or an optimal GPU allocator**. Observe actual concurrency, outcomes, and elapsed time on H100; do not rewrite the table during the pair. The screen only proved one-worker nominal compatibility; two-worker behavior is part of this experiment, and an invalid/uncertain round aborts further execution.

The 90-minute cap accommodates two 30-minute launch windows, two five-minute active-evaluator timeout tails, up to 15 minutes startup/readiness, and five minutes transfer/stop reserve. Runner seconds bound new launches, not the lifetime of already active work. Set the workstation stop-request deadline within 87 minutes of the sole start request to leave three minutes for stop confirmation; the remaining-time gate below may require readiness sooner than the 15-minute ceiling. It is not a guarantee that all flows finish: perturbation durations are unmeasured on H100, and an evaluator may take up to its existing 300-second timeout. If startup takes more than 15 minutes or either planned mode cannot fit its complete 30-minute launch allowance plus five-minute active-evaluator tail plus the other mode and five-minute reserve, stop with setup evidence instead of quietly giving the modes unequal limits. Do not shorten limits mid-pair or extend the guard.

## Task 1 — Local readiness and independent review (green)

**Read:** `scripts/run_diagnostic_portfolio.py`, `src/robot_debug/portfolio_runner.py`, `src/robot_debug/portfolio_report.py`, `docs/experiments/m3-three-task-screen.md`.

- [x] Verify prior three-task screen evidence and unchanged code; focused CLI/runner/reporter suites passed 34 tests. Full Windows suite previously passed 349, four skips.
- [x] Push approved main and verify remote commit identity.
- [ ] Run fresh full tests before freezing the transfer bundle:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
C:/Windows/py.exe -3.11 -m unittest discover -s tests -q
git diff --check
```

- [ ] Smaller-model reviewer independently checks the frozen paired commands, ceiling, complete/no-failure versus partial interpretation, and speedup gates. Root resolves discrepancies against source before spending.
- [ ] Commit this plan and update `PROJECT_PLAN.md` / `docs/codex-handoff/STATE.md`; conventional boundary `docs(m3): scope live portfolio comparison`. No runner/viewer refactor.

## Task 2 — Guarded recreation of the proven setup (amber after cap approval)

**Files:** fresh ignored control directory under `artifacts/m3-control/`; reuse existing snapshot/create requests, model launch, catalog/GPU checks, and watchdog from the successful screen, updating only session/resource identities and deadlines.

- [ ] Obtain and record explicit US$8/90-minute/one-start/temporary-cleanup approval; refresh active project, balance/expiry, quota/capacity, live compute/storage price, source VM stopped, disk ready and owned, and absence of prior temporary resources.
- [ ] Create snapshot and one explicitly stopped H100 clone from the exact original disk. Record all new identities privately; never overwrite previous evidence. Refresh direct WSL egress and create only the narrow temporary SSH rule for that source.
- [ ] Arm the OS-owned watchdog against the exact new clone before start, durably verify armed state, and use a fixed deadline conservatively within 87 minutes of the sole start request, reserving three minutes for confirmed stop. Guest shutdown is backup only.
- [ ] Apply the successful screen's SSH readiness gate: five minutes after serial boot completion or ten minutes after start request, whichever is earlier. On failure, collect serial evidence and stop; no replacement or second start.
- [ ] Verify actual CUDA compute, pinned simulator catalog, cached checkpoint-resolution revision, checkpoint-ID server loading log, and model readiness. Use the working cached model interpreter and simulator Conda environment, not generic host/system Python. Keep the same model command/offline settings. Do not repair Fabric Manager solely because it logs the previously observed warning; an actual CUDA/inference blocker requires stop and review.

## Task 3 — Execute the matched pair (amber; root sole external owner)

**Files:** immutable manifest, privately reviewed source bundle and guest orchestration under a unique ignored session; two fresh results roots, runner logs/PIDs, resource timeline.

- [ ] Freeze reviewed main SHA and upstream commit `35f1200eb15608aa898f727a3722f7eef889c6cd`; verify guest identities and unchanged container digest from the successful screen. Set `SESSION` to the fresh guest directory recorded in the private control manifest. Use the existing evaluator interpreter and model server.
- [ ] Confirm at least 4500 seconds (two 1800-second launch windows, two 300-second active-evaluator tails, and five-minute copy/stop reserve) remain before the fixed guard; record `date -u` and watchdog deadline. If fresh hourly rate differs from 4.50, rewrite both planned dollar limits consistently from the same 1800-second rate and recheck the total cap **before** running either mode.
- [ ] Run the exact same immutable limits in separate new roots:

```bash
PROJECT="$SESSION/source"
UPSTREAM=/home/robot/vla-evaluation-harness
PY=/home/robot/.venvs/vla-eval/bin/python
export PATH=/home/robot/.venvs/vla-eval/bin:$PATH
export PYTHONPATH="$PROJECT/src"
"$PY" "$PROJECT/scripts/run_diagnostic_portfolio.py" \
  --manifest "$SESSION/manifest.json" --mode sequential-jobs \
  --results-root "$SESSION/sequential" --upstream-root "$UPSTREAM" \
  --project-root "$PROJECT" --episodes 111 --seconds 1800 \
  --estimated-usd 2.25 --hourly-rate 4.50
# Preserve exit/log/summary. Continue only after validating no invalid,
# uncertain, or unowned evaluator/container work; exit 1 may be a valid partial.
"$PY" "$PROJECT/scripts/run_diagnostic_portfolio.py" \
  --manifest "$SESSION/manifest.json" --mode adaptive-portfolio --max-workers 2 \
  --results-root "$SESSION/adaptive" --upstream-root "$UPSTREAM" \
  --project-root "$PROJECT" --episodes 111 --seconds 1800 \
  --estimated-usd 2.25 --hourly-rate 4.50
```

- [ ] Run the commands through the existing durable guest orchestration pattern; capture status explicitly rather than letting shell `set -e` lose evidence on exit 1. Never overlap the two modes. No unsafe resume or retry into an existing results root.
- [ ] Root observes logs/ledger progress, container ownership, GPU state, and watchdog liveness; copy completed wave aggregates/ledgers/traces/videos incrementally. Do not keep a running allocation idle awaiting user interpretation. On invalid/uncertain work or loss of ownership, stop further launches, collect evidence, then stop the exact VM.
- [ ] Preserve raw videos/traces for **every launched valid episode**, not just successes or selected failures. Maintain job/mode/case identity to prevent identical task-local filenames overwriting one another.

## Task 4 — Recover evidence, stop, and report (green within approved cleanup)

**Files:** new ignored artifact tree and media ZIP; `docs/experiments/m3-portfolio-comparison.md`, `docs/dev-log.md`, `FEEDBACK.md`, `PROJECT_PLAN.md`, `docs/codex-handoff/STATE.md`.

- [ ] Copy summaries, wave ledgers/configs/launch identities, aggregates, traces, MP4s, and relevant diagnostic logs. Validate task/reset identity and outcome against each aggregate, trace terminal record, and nonempty MP4; reconcile physical/valid/invalid/uncertain counts independently. Preserve guest paths in raw evidence and remap read-only locally.
- [ ] Stop exact clone early after copy and independently verify STOPPED. Only then retire guard/remove ingress and delete only temporary VM/managed disk/snapshot. Read lists back: original stopped VM/ready managed disk only, no snapshots, standing egress only. Record cleanup and timing privately.
- [ ] Generate the existing `compare_portfolios` report locally from both original summaries. Require identical manifest and numeric limits, terminal `all_jobs_terminal` in both, live/accounting validity, no invalid/uncertain/partial status, and identical durable outcomes, decisions, and terminal statuses before accepting a warm speedup. Drift means report it, not rerun selectively.
- [ ] Report no-failure tasks honestly, with null failure/reduction timestamps. Complete no-failure flows can still compare workload elapsed time, but do not call that failure-diagnosis yield. A certified reducer output is bounded, not globally minimal. One pair with fixed mode order is exploratory evidence, not a repeated statistical benchmark.
- [ ] Smaller-model reviewer independently audits all media/counts and claim gates on local artifacts; root synthesizes results and bug causes. Record unchanged hardware/config plus any narrowly scoped recovery, separating project/operator bugs from provider behavior. Track warm estimates, whole allocation envelope, storage and tax separately; never relabel estimates as posted billing.
- [ ] Bundle media/trace files in per-mode/job/case directories, excluding private control/server logs. Keep large artifacts ignored. Current viewer task-local filename compatibility and M5 overview are separate work, not grounds to change the experiment.
- [ ] Run fresh proportionate checks and `git diff --check`, commit explicit related docs (`docs(m3): record live portfolio comparison`) and push under Jethro's publication request. Verify remote SHA and return media links, valid counts, comparison limits, cleanup, and a simple bug explanation.

## Dependency/concurrency and learning checkpoints

Root: plan, preflight, sole cloud execution, Git integration/publication, final synthesis. Smaller-model reviewer: read-only command/evidence/claim audits, no file writes or cloud mutation. Review can proceed alongside root's local/read-only preparation and again after recovered evidence; no overlapping ownership. Routine fixes stay bounded and test-first in a separate worktree only if a reproduced defect blocks the approved workflow; user requested minimal changes.

Local readiness + explicit cap → guarded single start/readiness → sequential mode → ownership validation → adaptive mode → media recovery/stop/cleanup → independent audit → result interpretation. Architecture, new tasks/families, driver migrations, altered failure rules, extra starts and increased spending remain red. Approval of the pair allows green/amber execution without repeated questions; the final checkpoint explains what changed, measured benefit or lack of benefit, and remaining uncertainty.
