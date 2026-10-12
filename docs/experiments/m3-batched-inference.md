# M3: batched GR00T inference (October 12, 2026)

Design: ADR 0025. Plan: `docs/superpowers/plans/2026-10-12-m3-batched-inference.md`.
Image v10 `789a0faaae66` (`sha256:e4c6266c…`). One Serverless L40S Job per
row below (gpu-l40s-a, 1gpu-16vcpu-64gb). Workload per phase: the certified
case, 12 nominal + 12 reduced-mask episodes, against a freshly started
GR00T server; one untimed warm-up episode before the first phase.

## Result

**Batching works at 12 evaluator workers: +18.7% and +18.0% throughput in two
runs, with parity passed. It gives no gain at 8 workers.** Specific to GR00T
N1.7, LIBERO-Object task 0, this harness and one L40S.

| Run | Workers | Batching | Episodes/min | vs 4 workers | Model busy | Mean batch | Wait p50 / p95 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| measure | 4 | off | 9.18 | 1.00× | 35% | 1.00 | 0 / 47 ms |
| measure | 8 | off | 14.67 | 1.60× | 63% | 1.00 | 44 / 260 ms |
| measure | 8 | on | 14.57 | 1.59× | 57% | 1.19 | 29 / 190 ms |
| measure | 12 | off | 16.29 | 1.77× | 78% | 1.00 | 796 / 1214 ms |
| measure | 12 | on | 19.22 | 2.09× | 61% | 1.74 | 83 / 247 ms |
| rerun (batched first) | 12 | on | 19.40 | — | 64% | 1.60 | 100 / 221 ms |
| rerun | 12 | off | 16.34 | — | 78% | 1.00 | 770 / 1283 ms |

"Model busy" is time inside model calls (including CPU pre/post-processing)
over the phase's wall time. Waits are from a request's arrival to the start
of its inference call.

## Interpretation

- **Amdahl's law.** From 4 to 8 workers throughput rose 1.60× (80%
  efficiency); from 8 to 12 only 1.11×. At 12 workers the single model server
  is busy 78% of the time and requests wait about 0.8 s: the bottleneck has
  moved from simulation (CPU) to inference (GPU queue).
- **Why batching helps only at 12.** At 8 workers requests rarely overlap
  (44 ms median wait), so batches stay at about one item. At 12 the queue
  forms batches of 1.6–1.7 on average (up to 4); one batched call takes a
  little longer (about 231–242 ms vs 194–197 ms) but serves more episodes, so
  waits fall about 8–10× and throughput rises about 18%.
- **Replication.** The two 12-worker comparisons agree within about 1%
  (16.29 vs 16.34 unbatched, 19.22 vs 19.40 batched) despite reversed phase
  order.

## Correctness

- Smoke Job parity: batched vs single-observation actions, compared before
  gripper rounding, max abs difference 0.0149 (limit 0.05); no gripper flips
  after rounding.
- Outcomes: every nominal episode succeeded (6.8–7.3 s) in every phase.
  Reduced-mask episodes timed out at the 280-step cap (14.05 s) in every
  phase except one: `mask-10` in the first run's batched 12-worker phase
  succeeded late at 11.0 s. The pre-set rule labelled that run
  `outcome_drift`; the replication rule (ADR 0025, fixed before the rerun)
  required a rerun with no masked success in its batched phase, which held
  (12/12 failures). Across all runs: 1 late success in 38 batched masked
  episodes, 0 in 36 unbatched; not statistically distinguishable, and
  consistent with a stochastic timeout near the cap.

## Spend (estimates at US$1.7468/h, not yet reconciled with billing)

| Job | Wall time | Estimate |
| --- | ---: | ---: |
| Smoke (parity + 4 workers) | 12.2 min | US$0.36 |
| Measurement (5 phases) | 22.4 min | US$0.65 |
| Rerun 1 (failed: 690 s deadline left the download 90 s) | ~7.5 min | US$0.22 |
| Rerun 2 (12-worker pair) | 14.9 min | US$0.43 |
| **Total** | | **≈ US$1.66** of the US$1.85 cap |

Rerun 1 was a coordinator planning error: the runtime reserves 600 s after
the model download. `prepare_serverless_job.py` now rejects batch deadlines
under 1000 s.

## Evidence

Downloaded to ignored `artifacts/serverless-m3-{smoke,measure,rerun2}-20261012/evidence/`
(batch summaries, server timing logs, parity JSON, configs, MP4s and traces).
Read-only download identities were revoked after download.
