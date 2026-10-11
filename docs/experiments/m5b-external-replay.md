# M5B: external-start reduction and certified-case re-run

October 10–11, 2026. One Nebius Serverless Job (`faultline-m5b-20261010`,
image `cc23a893ea25` → `sha256:2c7245ff…`, 1× L40S), approved by Jethro with a
US$2 cap. Plan: `docs/superpowers/plans/2026-10-10-m5b-external-replay.md`.

## What ran

1. **Certified M4 re-run:** the certified reduced rectangle
   `(0.625, 0, 0.375, 0.375)` once from the benchmark start (task 0, init 0,
   seed 7), in a fresh session.
2. **External-start reduction:** the unchanged M4 reducer
   (`run_failure_reduction`) with every stage starting from the accepted
   external LIBERO demo state (ADR 0016: `libero_object` alphabet-soup file,
   `demo_0`, state 0) via the reviewed restore kernel. Fresh GR00T actions; the
   demonstration's recorded actions and video are not used.

## Results

| Stage | Start | Mask | Outcome | Steps |
| --- | --- | --- | --- | --- |
| certified-m4 | benchmark init 0 | `(0.625,0,.375,.375)` | **policy_failure** | 280 |
| nominal-sentinel | external demo_0 | none | success | 141 |
| parent attempt 1 | external demo_0 | `(0.5,0,.5,.5)` | success | 157 |
| parent attempt 2 | external demo_0 | `(0.5,0,.5,.5)` | policy_failure | 280 |
| parent attempt 3 | external demo_0 | `(0.5,0,.5,.5)` | success | 154 |

The reducer's gate rejected the parent (`success, policy_failure, success`) and
stopped with `parent_not_reproducible`; no reduction was attempted.

Restore evidence: every external-start episode recorded a pre-settle state hash
equal to the dataset (`5d4cd690…`) and the same post-settle hash
`935fee19b2c7…`. Local CPU probes gave `e029f8dc…` consistently on the
workstation; the difference is attributed provisionally to host floating-point
differences in MuJoCo, since each host is internally deterministic.

Recovery: 48 exported files downloaded with the read-only key to ignored
`artifacts/serverless-m5b-20261010/recovered/`; all manifest hashes and sizes
match; all five MP4s decode (frames = steps + 1). Timeline (UTC): submitted
15:48:58, container 15:53:36, prefetch 394 s, certified 16:00:27–16:01:10,
reduction 16:01:10–16:02:38, export of 48 files done 16:02:41; ≈14 minutes from
submission (≈US$0.40 estimated compute).

## Interpretation (one episode per condition; not a robustness claim)

- **The saved M4 case reproduced** in a fresh Serverless session from its
  recorded recipe. This exercises the M4 replay recipe (M5's "another session
  reproduces a saved case").
- **The external pipeline works end to end:** an outside scenario's exact
  starting state entered Faultline and the unchanged find/confirm/reduce loop
  ran from it with verified restore hashes.
- **The M4 failure did not transfer to the external start:** from the
  demonstration's starting arrangement, the 25 % parent mask failed only 1 of 3
  times, below the reducer's reproducibility gate. The occlusion sensitivity
  found in M4 appears specific to the benchmark start state for this task.
  Finding a reproducible failure from the external start would need the
  `search` mode (or a different mask family) first.

## Limitations

Single task, single external demo/state, one seed; three parent attempts; the
external dataset's licence conflict is unresolved, so the candidate and
recordings stay private. `tests/test_external_reset.py` mocks fail only under
Python 3.8 in the image (pass on 3.11).

## Follow-up: position grid from the external start (October 11)

Jethro chose to look for a reproducible failure from the external start before
reducing. The search driver sweeps 20 benchmark start states, so the
single-start **position grid** was used instead, chained into the reducer only
if it confirms a failure (`m5b-grid` mode, `bd1a59e`/`afb8eaa`; reducer now
accepts any parent rectangle). Job `faultline-m5b-grid-20261011`, image
`afb8eaa5d3d9` → `sha256:57c02730…`, ~15 minutes, 89 files exported and
verified; all ten external restores matched the dataset hash.

| Stage (external demo_0 start) | 0.5×0.5 mask at | Outcome | Steps |
| --- | --- | --- | --- |
| nominal-sentinel | none | success | 136 |
| grid | bottom-left (0, 0.5) | success | 130 |
| grid | bottom-right (0.5, 0.5) | success | 118 |
| grid | top-left (0, 0) | success | 140 |
| grid | **top-right (0.5, 0)** | policy_failure | 280 |
| replays 1–5 | top-right (0.5, 0) | success, success, failure, failure, success | 157/160/280/280/271 |

The grid's reproducibility rule rejected the top-right failure
(`policy_failure_not_reproducible`), so no reduction ran.

**Combined reading.** From the external start, the top-right 25 % mask failed
4 of 9 episodes across both Jobs (1/3 in the M5B reducer gate, 1 grid + 2/5
replays), while the other three quadrants succeeded. From the benchmark start
the same rectangle failed 4/4 in M4. The policy's sensitivity sits in the same
image region from both starts, but from the external start it is
intermittent (about 44 %, small sample) rather than reliable, so it does not
meet the 4-of-5 reproducibility bar that reduction requires. This is evidence
of a start-state-dependent failure rate, not a robustness or causal claim.

## Follow-up: demo_1 external start (October 11, ADR 0021)

Job `faultline-m5b-demo1-20261011` (`m5b-grid`, image `9413ad4ea434` →
`sha256:71527bef…`), ~14 minutes, 81 files verified, all videos decode; all nine
restores matched demo_1's pinned hash (post-settle `a884ead3…` on Nebius versus
`6420e5e0…` in the workstation CPU probe, the same host-dependent pattern as
demo_0).

| Stage (external demo_1 start) | 0.5×0.5 mask at | Outcome | Steps |
| --- | --- | --- | --- |
| nominal-sentinel | none | success | 173 |
| grid | bottom-left (0, 0.5) | success | 138 |
| grid | bottom-right (0.5, 0.5) | success | 137 |
| grid | top-left (0, 0) | policy_failure | 280 |
| replays 1–5 | top-left (0, 0) | all success | 137–145 |

The top-left failure did not recur (0/5), so the grid stopped with
`policy_failure_not_reproducible` and no reduction ran. Because the grid stops
at its first apparent failure, the top-right position — the region implicated
from the benchmark start and from demo_0 — was **not tested** from demo_1.
