# M3 adaptive-loop live comparison — proposed, not authorized

**Status:** Paused/superseded as the *next* M3 experiment by the portfolio-first design accepted September 29. Retained as a historical single-loop proposal; no VM start is authorized by this document.

## Question

Does scheduling the complete find → confirm → reduce loop with bounded 1/2/4 evaluator workers on one L40S VM reduce time to the same certified counterexample compared with one worker? The earlier 3.715× result measured only a fixed, equal-work batch, not this dependent diagnostic loop.

## Frozen comparison contract

- Use the existing stopped, exact-ID Nebius L40S Intel VM in the existing eu-north1 project: one GPU, 16 vCPUs, 64 GiB RAM. Do not provision another VM or GPU.
- Run a fresh `sequential` session first and a fresh `adaptive` session second, with the same pinned GR00T/LIBERO model and evaluator image, seed, task, prior position-grid order, centered-square family, rectangle deltas, five-replay confirmation, M4 gate, and fresh nominal controls. The scheduling policy is the only intended change.
- Give each session its own immutable directory under one ignored results root. Use the same `--episode-limit 100`, `--hourly-rate-usd 1.7468`, and a session launch cutoff derived from the independent VM stop deadline. Do not reuse an interrupted session for a speed comparison.
- Stop between modes if evaluator ownership, model health, evidence, or cloud control state is uncertain. Inspect and copy compact JSON/traces first, media second. Stop/poll the exact VM before declaring completion.
- Report both full-session outcomes, warm diagnostic time, first apparent/reproducible/reduced failure times, attempts including speculation, outcome drift, and confidence. A speedup claim requires the same certified result with valid evidence and no outcome drift. Keep estimated warm compute, full allocation, and posted billed cost distinct.

## Read-only preflight observed 29 September 2026

- The exact VM is `STOPPED`; its 200 GiB Network SSD boot disk remains billable. No public IP is assigned while stopped.
- The console balance is **US$10.42** on the intended account; no promo expiry was shown for the card-funded balance. Refresh immediately before any start.
- Console list prices in eu-north1 are US$1.35/GPU-hour, US$0.012/vCPU-hour, and US$0.0032/GiB RAM-hour for L40S Intel: **US$1.7468/VM-hour before tax** for this shape. Network SSD is US$0.000097222/GiB-hour, or **US$0.0194444/hour** for 200 GiB. Discounts, tax, and actual billing may differ. At an assumed 9% tax, a 90-minute VM-on window plus 24 hours of disk is about **US$3.37**. This is an estimate, not a posted charge.
- The capacity dashboard, accurate as of 29 September 2026 14:19 UTC, showed **0 regular VMs and low chance of launch** for the exact L40S Intel 1-GPU/16-vCPU/64-GiB shape. It also showed 1 preemptible VM but a low chance; do not silently change to preemptible. Restart may fail. The dashboard describes launch capacity, not a guarantee about this stopped instance. Recheck immediately before start; if it remains zero, defer without repeated paid starts or changing shape.

## Proposed hard boundary

Recommend **US$4 maximum incremental spend and 90 minutes maximum VM-on time** for this pair of sessions, including a 24-hour disk-retention allowance, with an exact-VM workstation watchdog armed and observed alive before start and a guest shutdown timer as backup. Do not launch a new episode after the controller's earlier deadline; reserve time for a 300-second evaluator timeout, evidence copy, and stop verification. If the first mode consumes enough time that the second cannot fit safely, stop and report a partial experiment rather than exceed the cap. Stop early on completion. Review disk retention within 24 hours; storage continues billing after compute stops.

Set each CLI `--launch-cutoff-seconds` from the *remaining* shared 90-minute VM window, leaving at least eight minutes before the watchdog deadline (five for the evaluator timeout and three for containment/stop). The CLI currently reserves only 20 seconds internally and does not itself guarantee this outer margin. Do not give each mode a fresh 90-minute clock.

The controller's warm cost estimate is advisory, not a spending enforcement mechanism. The independent exact-VM stop/poll guard is the cost boundary; workstation sleep, lost network, or expired CLI authentication require console fallback. Validate the CLI session, VM shape/state, remaining balance, capacity, and watchdog process immediately before the paid start. A failed start or uncertain stop is a stop-and-diagnose event, not permission to retry autonomously.

## Gates

1. Jethro approves or changes the specific cap and deadline. The design and local implementation approval did not approve this run.
2. Execution owner rechecks account, balance, exact price, quota/capacity, VM/disk state, model cache, CLI auth, and backup/primary stop guards. If the exact shape cannot restart, stop and present alternatives.
3. Run both modes only within the approved boundary; verify evidence and stop state, remove temporary SSH ingress, then reconcile billing and update `FEEDBACK.md` with provider-specific observations.
