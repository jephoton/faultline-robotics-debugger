# ADR 0025: M3 batched-inference experiment

**Status:** Accepted by Jethro on October 12, 2026. Timebox 3 working days
(ADR 0023); failure to meet the bar below moves M3 to the portfolio fallback.

## Problem

Faultline's search and reduction run many simulator episodes against one shared
GR00T server. The September 29 M3 run reached 3.715× throughput with four
evaluator workers even though the server runs one inference at a time behind a
lock, so at four workers the GPU was not the bottleneck: simulator stepping on
the CPU was. Batching can only help once enough workers queue on that lock.

## Evidence (pinned code)

- `vla_eval/model_servers/predict.py` (harness `35f1200`) already queues
  requests from concurrent sessions and calls `predict_batch()` when
  `max_batch_size > 1`.
- `vla_eval/model_servers/lerobot.py` implements only single-observation
  `predict()`.
- LeRobot GR00T N1.7 (`30da8e6`) natively accepts a batch dimension and draws
  independent flow-matching noise per item; `reset()` only clears the
  `select_action` queue, which the chunk path does not use.
- Risk: the GR00T processor keeps a per-instance raw-state cache used for
  relative-action decoding, so a batch must be preprocessed as one batch, not
  per item and then concatenated.
- GR00T samples actions, so batched and unbatched runs cannot match exactly;
  equivalence is judged by outcomes and a seeded parity check.

## Decisions

1. **Measure first, then batch.** One measurement Job runs the equal-work
   manifest unbatched at 4, 8 and 12 evaluator workers with server-side timing
   (lock wait, inference time, batch size), then batched at 8 and 12 workers.
   Rejected: a single 8-worker comparison (would not explain the result) and
   skipping batching.
2. **Our own adapter subclass.** A Faultline server extending upstream
   `LeRobotModelServer` adds instrumentation and `predict_batch()` that
   preprocesses the whole batch together, makes one GPU call and splits results
   per session. Upstream files stay unmodified. Rejected: patching upstream.
3. **Success bar.** Batching "works" only if (a) a seeded parity check shows
   each batch item matches its single-observation output within bf16
   tolerance, (b) outcomes on the fixed manifest match the known results (all
   nominal succeed, all reduced-mask attempts fail) with no drift, and (c)
   batched throughput is at least **15%** higher than unbatched at the same
   worker count. Otherwise: "no measurable gain" and M3 moves to the portfolio
   fallback.
4. **Spend cap: US$1.50** of the US$3.68 AI Cloud balance for all M3 batching
   GPU work (a smoke Job and a measurement Job), leaving about US$2.18 for M6
   and M7.

## Claim boundary

Any result is specific to GR00T N1.7 on LIBERO-Object task 0 with this harness
and one L40S. It is a throughput measurement for replay workloads, not a claim
about search speed, other policies or general batching benefit. Keep the
September 29 3.715× worker result separate.
