# M7 mode 1: screening for a natural failure and reducing its scenario

October 13, 2026. GR00T N1.7 with the LIBERO-10 checkpoint
`nvidia/gr00t17-lerobot-libero_10-640` (revision `5ee08ab…`), one L40S per
Nebius Serverless Job, images v12 (`31738b844cdf`) and v13 (`80326ce…`, raised
reduction candidate cap). Design: ADR 0028 and ADR 0029; plan:
`docs/superpowers/plans/2026-10-13-m7-mode1-scenario-reduction.md`. Spend cap
US$4.00 (Jethro, October 13).

## Local verification before any paid run

- Real LIBERO-10 on CPU inside the image (no network): layout export (task 0:
  state length 123 = 1 + 65 + 57; robot plus 8 free objects), exact restores,
  valid hybrid starts, an overlapped pair flagged at 1.89 cm penetration, and an
  invalid scene ending after one step through the runner's async path.
- Calibration over the 100 screen starts found one real defect: an absolute
  object-versus-table threshold rejected untouched scenes because `ketchup_1`
  rests 14.6 mm inside `living_room_table`'s collision geometry in every start
  of tasks 0, 1 and 7. Static contacts are now recorded but never decide
  validity (`31738b8`). Replayed and upstream resets agree to about 4e-14.

## Runs

| Run | Result | Container | Estimate |
| --- | --- | ---: | ---: |
| Smoke (task 0) | all 8 checks pass; 3 successes, 2 failures, 1 invalid scene ended at step 1 | 9.2 min | US$0.37 |
| Screen, attempt 1 | no L40S capacity after ~27 min (`NotEnoughResources`) | - | 0 |
| Screen, 10 tasks x 10 starts | complete; one reproducible failure (task 0, start 2) | 17.8 min | US$0.62 |
| Reduce start 2, attempts 1–3 | no capacity (twice) and a bucket-policy quota | - | 0 |
| Reduce start 2, attempt 4 | failing gate S F F F S: `failing_not_reproducible` | 9.0 min | US$0.36 |
| Screen, task 0 starts 10–49 | complete; start 14 F F F F F, start 38 F S F F F | 14.0 min | US$0.51 |
| Reduce start 14 vs start 28 | 9 -> 6 entities, then `budget_exhausted` (30 candidates) | 19.9 min | US$0.68 |
| Follow-up from the 6-entity scene | entity-minimal 5 entities, partial shrink, `budget_exhausted` (36) | 27.3 min | US$0.90 |
| **Total** | | | **≈ US$3.44** |

Estimates use container time plus about 3.5 minutes of image pull and start
at US$1.7468/h; capacity failures never started a container. Reconcile with
billing.

## Screen (LIBERO-10, unperturbed)

Outcomes per start (S success, F policy failure; one attempt, then up to four
confirmations on a failure, early-decided):

| Task | Starts 0–9 |
| --- | --- |
| 0 put both the alphabet soup and the tomato sauce in the basket | FSS, FFFSS, **FFFFF**, S x7 |
| 1, 2, 3, 5, 7 | all S |
| 4 | S x8, FSS, S |
| 6 | S x6, FSS, FSSF, S, S |
| 8 | S x5, FSFS, S, FSFFS, S, S |
| 9 | S x5, FSFFS, FSS, S, S, FSS |

89 of 100 starts passed first time; 10 of the 11 first failures were flaky.
Early-decided gates (ADR 0029) skipped 13 confirmation attempts. Task 0 starts
10–49: only 14 (FFFFF) and 38 (FSFFF) met the gate; 11, 26 and 37 were flaky.

## Start 2 was not reproducible on a second Job

The reduce Job's own gate saw S F F F S for start 2 (start 7 passed 5 of 5).
Across both Jobs start 2 failed 8 of 10: a failure in the stochastic band near
80%, which passes a 4-of-5 gate only about 74% of the time. Jethro chose to
screen task 0 deeper rather than loosen the gate.

## Reduction of task 0, start 14 against start 28

Differences (positions only; LIBERO starts do not rotate objects): orange
juice 3.7 cm, alphabet soup 2.9, milk 2.4, basket 2.2, butter 1.5, ketchup
1.2, cream cheese 1.1, tomato sauce 0.7, robot joints about 1 degree.

- Gates: start 14 F F F F, start 28 S S S S S.
- No single difference reproduces the failure (all nine singleton probes
  passed).
- Delta debugging: 9 -> 6 entities in the first Job; the follow-up, started
  from that 6-entity scene, reached an **entity-minimal set of 5**: alphabet
  soup, orange juice, milk, cream cheese and the robot joint offset. Removing
  any one of them made the task pass. Basket, butter, ketchup and tomato
  sauce are not needed.
- Shrinking (3 bisection steps, resolution 1/8): soup 0.875 of its shift,
  robot 0.875, orange juice 1.0 (no shrink); milk and cream cheese were not
  reached before the 36-candidate budget. Shrinking any part by 12–25 % made
  the failure disappear.

**Reading.** The failure is a conjunction: five small shifts together, three
of them distractors. Shrinking reached three of the five (soup and robot at
least 87.5% of their shift, orange juice 100%); the milk and cream cheese were
not shrunk because the candidate budget ran out, so their needed size is
unknown. It is a narrow, arrangement-specific failure rather than one
misplaced object. Early-decided
gates skipped 31 and 33 attempts in the two reduction Jobs.

**Predictions.** Jethro predicted a distractor (three of the five causes are
distractors). Nemotron 3 Ultra ranked the alphabet soup first and predicted
that reverting only the soup restores success (correct: the scene without the
soup passed S S S S) and that reverting only the tomato sauce does not
(correct: the scene without the sauce failed F F F F). The soup is necessary
but not sufficient (the soup alone passed). Nemotron's text also called the
soup's shift the largest; the orange juice's was larger. For start 2 Nemotron
had ranked the tomato sauce first; that start was not reducible.

## Explanation model comparison

The measured hypothesis check gives the soup `necessary_not_sufficient` (the
scene without it passed S S S S; the soup alone passed S S). One explanation
call per model on the same packet, scored against five known facts (soup not
sufficient; soup necessary; sauce not needed and the model right about it;
five shifts needed together; no reruns of tested sizes):

| Model | Facts right | Format check | Notes |
| --- | --- | --- | --- |
| Nemotron 3 Nano | 2 of 5 clean | passed | called an applied entity "reverted"; repeated tested reruns |
| Nemotron 3 Super | 3 of 5 | rejected | said the correct sauce prediction was wrong |
| Nemotron 3 Ultra | 4 of 5, then 5 of 5 with the shrink history added | passed | one repeat before the shrink history was in the packet |

Two input fixes mattered as much as the model: a plain sentence per rerun
(Nano's first answer read "S S" for the soup alone as "reverting the soup did
not help") and the list of shrink sizes already tested. Jethro chose Ultra
for scenario explanations. The stored Ultra explanation states the
necessary-but-not-sufficient result, the five-way conjunction and the shrink
limits, and proposes untested next runs (shrink cream cheese, find the
critical robot joints).

## Limits

- One task, one failing start, one reference, one checkpoint and seed.
- Several "not needed" verdicts were decided after two successes in a scene
  whose failure rate is around 80 %, so some could be false negatives; the
  reported 5-entity scene itself failed 4 of 4.
- Sizes are only partly shrunk; the result is a local minimum, not the
  globally smallest cause.
- Differences are measured before the 10 settling steps; one object settles
  by up to 4.8 cm in the benchmark starts themselves.

## Operational lessons

- L40S capacity was scarce on October 13: four of nine submissions found no
  machine; an automatic resubmitter (reusing one bucket) worked around it.
- The tenant hit the bucket access-policy quota (`iam.storageaccesspolicy.count`)
  at 10 buckets; old M3/M6 buckets still hold objects and need emptying.
- The 30-candidate default was too small for a conjunction failure; the
  validator's upper bound was raised to 60 (`80326ce`). That bound is not a
  usable budget on LIBERO-10: the reduce Job's deadline is capped at 3000 s,
  which fits at most 36 candidates (37 or more are refused at planning time),
  so the follow-up run stopped at 36.

## Evidence

Ignored `artifacts/serverless-m7-*-20261013*/evidence/` (summaries, configs,
sidecars, traces, MP4s) and the plans with Nemotron replies in
`artifacts/serverless-m7-reduce{,2,3}-20261013/`. Download identities were
revoked after the runs.

## Regression replay with `faultline replay` (October 15)

The first live run of the new `faultline` tooling (ADR 0031) replayed this
case: the minimal 5-shift scene failed F S F F F (`reproduces`) and passing
start 28 succeeded 5 of 5, so the verdict is `still_reproduces`. One L40S Job,
597 s of workload, about US$0.41 against a US$1.20 cap (worst-case
reservation US$1.08). Two earlier attempts stopped before creating a Job
(US$0): a WSL path bug in the backend, fixed in `718fbf2`, which also proved
the clean-up path (access key and empty bucket deleted).

