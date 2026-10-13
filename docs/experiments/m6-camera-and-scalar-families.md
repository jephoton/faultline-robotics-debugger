# M6: camera reliance and scalar image families (October 13, 2026)

Design: ADR 0026. Plan: `docs/superpowers/plans/2026-10-12-m6-camera-and-scalar-families.md`.
Image v11 `8af6806c24d0` (`sha256:23a3aae4…`). Two Serverless L40S Jobs, each
with one GR00T server batching up to 12 requests and 12 evaluator workers.

## Headline findings

- **Two cameras, two jobs (hypothesis).** With only the reduced agent-view
  mask (M4), GR00T grasps the soup and then times out carrying it. With the
  same mask **and the wrist image blacked out**, it fails 12/12 and **never
  grasps**: the gripper hovers near the soup for the whole episode (frames
  checked by hand). The same rectangle on the wrist image alone succeeds
  12/12. This suggests the wrist view drives the grasp and the agent view
  drives transport; not proven causally.
- **Blur is the policy's weak spot:** reliable failure from blur sigma 3.9 px
  (severity 0.4875) on both cameras.
- **Noise fails only when extreme:** reliable failure from noise sigma 95 of
  255 (severity 0.95).
- **Darkening and contrast:** no reliable failure anywhere in range, even at
  5% brightness or 10% contrast.

## Wrist-camera conditions (smoke Job)

| Condition | Runs | Successes | Policy failures | Not completed | Median duration (s) | Agent view mean / std ratio | Wrist mean / std ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Nominal control (no perturbation) | 6 | 6 | 0 | 0 | 26.8 | - | - |
| Reduced agent-view mask + wrist image black | 12 | 0 | 12 | 0 | 34.7 | 0.89 / 1.50 | 0.00 / 0.00 |
| Same rectangle on the wrist image only | 12 | 12 | 0 | 0 | 25.6 | 1.00 / 1.00 | 0.84 / 1.18 |

- All 6 nominal runs succeeded, so the unperturbed path is intact.
- Reduced agent-view mask with the wrist image blacked out failed in all 12 completed runs (both cameras were degraded in these runs).
- The same rectangle on the wrist image only succeeded in all 12 completed runs (this wrist rectangle alone did not cause failure here).
- These counts describe this rectangle and these two conditions on one task; they do not by themselves show which camera the policy relies on.

## Scalar families at one severity (smoke Job)

| Family | Severity | Physical value | Successes | Policy failures | Median duration (s) | Agent view mean / std ratio | Wrist mean / std ratio |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| Darkening | 0.6 | brightness x0.43 | 2 | 0 | 26.7 | 0.43 / 0.43 | 0.43 / 0.43 |
| Gaussian noise | 0.6 | noise sigma 60.0 of 255 | 2 | 0 | 19.7 | 1.00 / 1.67 | 1.00 / 1.21 |
| Gaussian blur | 0.6 | blur sigma 4.80 px | 0 | 2 | 38.3 | 1.00 / 0.82 | 1.00 / 0.93 |
| Contrast reduction | 0.6 | contrast x0.46 | 2 | 0 | 20.1 | 1.00 / 0.46 | 1.00 / 0.46 |

A single level per family only shows that each family reaches the policy and can be run; it does not locate a threshold.

## Camera-effect check (per-camera probe)

The benchmark records the mean and standard deviation of each camera's policy input before and after the perturbation (first observation and every 40th step to 280). A ratio of 1.00 / 1.00 means that camera was unchanged; the mean ratio shows brightness loss or occlusion, the std ratio shows lost contrast or added noise.

- Reduced agent-view mask + wrist image black: policy input changed on agent view and wrist.
- Gaussian blur at s = 0.6: policy input changed on agent view and wrist.
- Contrast reduction at s = 0.6: policy input changed on agent view and wrist.
- Darkening at s = 0.6: policy input changed on agent view and wrist.
- Gaussian noise at s = 0.6: policy input changed on agent view and wrist.
- Same rectangle on the wrist image only: policy input changed on wrist; unchanged on agent view.

38 valid episodes in 101 s of timed work (22.6 episodes/min on one 12-worker server).
Mean batch size 1.63 (largest 4); model busy share 68%.
Prefetch took 340.6 s (not part of the timed work).
Untimed warm-up: `warmup-nominal-01`, valid, 32.1 s.

## Threshold search per family (main Job)

Rule: sweep s in 0.2, 0.4, 0.6, 0.8, 1 in increasing order; a level is a reproducible failure at 4 of 5 policy failures among 5 attempts; then bisect 4 times between the last non-reproducing level and the first reproducing one. Nominal controls: 5 of 5 succeeded.

| Family | Smallest reproducibly failing severity | Physical value | Last non-reproducing level | Levels tried | Episodes | Stop reason | Agent view mean / std ratio at threshold | Wrist mean / std ratio at threshold |
| --- | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: |
| Darkening | none up to 1 | - | 1 | 5 | 25 | no reproducible failure up to s = 1 | - | - |
| Gaussian noise | 0.95 | noise sigma 95.0 of 255 | 0.9375 | 9 | 45 | threshold found | 0.99 / 2.06 | 0.99 / 1.36 |
| Gaussian blur | 0.4875 | blur sigma 3.90 px | 0.475 | 7 | 35 | threshold found | 1.00 / 0.84 | 1.00 / 0.93 |
| Contrast reduction | none up to 1 | - | 1 | 5 | 25 | no reproducible failure up to s = 1 | - | - |

| Family | Levels in the order tried (severity: failures/attempts) |
| --- | --- |
| Darkening | 0.2: 0/5; 0.4: 0/5; 0.6: 0/5; 0.8: 0/5; 1: 0/5 |
| Gaussian noise | 0.2: 0/5; 0.4: 0/5; 0.6: 0/5; 0.8: 2/5; 1: 4/5; 0.9: 2/5; 0.95: 5/5; 0.925: 3/5; 0.9375: 1/5 |
| Gaussian blur | 0.2: 0/5; 0.4: 0/5; 0.6: 5/5; 0.5: 4/5; 0.45: 3/5; 0.475: 1/5; 0.4875: 4/5 |
| Contrast reduction | 0.2: 0/5; 0.4: 0/5; 0.6: 0/5; 0.8: 0/5; 1: 0/5 |

- Darkening: no level up to s = 1 reached 4 of 5 failures, so the policy is robust to this family in the tested range (not a claim beyond it).
- Gaussian noise: reliably fails (4 of 5 attempts failing) from s = 0.95 (noise sigma 95.0 of 255); s = 0.9375 did not reproduce, so the boundary under this rule lies in (0.9375, 0.95].
- Gaussian blur: reliably fails (4 of 5 attempts failing) from s = 0.4875 (blur sigma 3.90 px); s = 0.475 did not reproduce, so the boundary under this rule lies in (0.475, 0.4875].
- Contrast reduction: no level up to s = 1 reached 4 of 5 failures, so the policy is robust to this family in the tested range (not a claim beyond it).

The camera columns are the median perturbed/unperturbed ratios of the policy input's mean and standard deviation over the threshold level's attempts (1.00 / 1.00 would mean unchanged).

135 valid episodes in 378 s of timed work (21.4 episodes/min on one 12-worker server).
Mean batch size 1.44 (largest 5); model busy share 73%.
Prefetch took 337.0 s (not part of the timed work).
Untimed warm-up: `warmup-nominal-control-01`, valid, 31.4 s.

## Reading the threshold searches

Failure rates rise through a stochastic band rather than flipping at one
point: blur went 3/5 at 0.45, 1/5 at 0.475 and 4/5 at 0.4875. With five
attempts per level, a threshold locates a band, not a precise value; that is
why ADR 0026 calls thresholds budget-local. Every attempt at a level sees the
same perturbation (noise is seeded without the attempt index), so the
variation comes from GR00T's sampled actions.

Noise episodes record about 3 MB of video each (versus about 70 KB) because
noise does not compress; well within export limits.

## LIBERO-Plus assessment (deferred)

LIBERO-Plus replaces the LIBERO package rather than extending it, needs an
extra asset archive, provides predefined task variants that a reducer cannot
shrink, and states no licence. It was deferred in favour of image-space
families that the existing loop can search and reduce.

## Spend (estimates at US$1.7468/h, not yet reconciled with billing)

| Job | Wall time | Estimate |
| --- | ---: | ---: |
| Smoke (wrist conditions + one level per family) | 13.6 min | US$0.40 |
| Threshold (four families concurrently) | 20.4 min | US$0.59 |
| **Total** | | **≈ US$0.99** of the US$3.00 cap |

## Evidence

Downloaded to ignored `artifacts/serverless-m6-{smoke,threshold}-20261013/evidence/`
(summaries, configs, per-camera probe sidecars, timing logs, MP4s, traces).
Read-only download identities were revoked after download.
