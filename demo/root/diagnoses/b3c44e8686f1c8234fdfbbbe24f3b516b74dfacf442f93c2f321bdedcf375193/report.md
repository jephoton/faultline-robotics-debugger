# Scenario reduction: put both the alphabet soup and the tomato sauce in the basket

## Summary

- Verdict: Reproduces. Applying the kept shifts to the passing reference makes the policy fail at least 4 of 5 attempts.
- Failing start: benchmark start 14.
- Reference: benchmark start 28, the nearest start that passed.
- Kept shift: alphabet_soup_1 position, 2.5 cm (87.5% of the full difference).
- Kept shift: cream_cheese_1 position, 1.1 cm (100% of the full difference).
- Kept shift: milk_1 position, 2.4 cm (100% of the full difference).
- Kept shift: orange_juice_1 position, 3.7 cm (100% of the full difference).
- Kept shift: robot joints, 6 joints, up to 2.3° (87.5% of the full difference).
- Status: Stopped at the candidate budget: entity-minimal (each kept entity is needed), sizes not fully shrunk.

Suite `libero_10`, task 0. Reference runs decide everything below; the model only proposes an order and a hypothesis.

## Screen

Outcomes per start: S success, F policy failure, I invalid scene. The first letter is the unperturbed screen attempt; failing starts were confirmed with more attempts (4 of 5 failures reproduce).

| task | start | outcomes | decision | max steps |
| --- | --- | --- | --- | --- |
| 0 | 10 | S | passed | 333 |
| 0 | 11 | F S S S | does_not_reproduce | 520 |
| 0 | 12 | S | passed | 253 |
| 0 | 13 | S | passed | 291 |
| 0 | 14 | F F F F F | reproduces | 520 |
| 0 | 15 | S | passed | 252 |
| 0 | 16 | S | passed | 255 |
| 0 | 17 | S | passed | 252 |
| 0 | 18 | S | passed | 297 |
| 0 | 19 | S | passed | 263 |
| 0 | 20 | S | passed | 272 |
| 0 | 21 | S | passed | 297 |
| 0 | 22 | S | passed | 278 |
| 0 | 23 | S | passed | 249 |
| 0 | 24 | S | passed | 393 |
| 0 | 25 | S | passed | 271 |
| 0 | 26 | F S S S | does_not_reproduce | 520 |
| 0 | 27 | S | passed | 265 |
| 0 | 28 | S | passed | 252 |
| 0 | 29 | S | passed | 301 |
| 0 | 30 | S | passed | 249 |
| 0 | 31 | S | passed | 265 |
| 0 | 32 | S | passed | 340 |
| 0 | 33 | S | passed | 267 |
| 0 | 34 | S | passed | 250 |
| 0 | 35 | S | passed | 238 |
| 0 | 36 | S | passed | 318 |
| 0 | 37 | F S S F | does_not_reproduce | 520 |
| 0 | 38 | F S F F F | reproduces | 520 |
| 0 | 39 | S | passed | 281 |
| 0 | 40 | S | passed | 281 |
| 0 | 41 | S | passed | 278 |
| 0 | 42 | S | passed | 265 |
| 0 | 43 | S | passed | 235 |
| 0 | 44 | S | passed | 300 |
| 0 | 45 | S | passed | 278 |
| 0 | 46 | S | passed | 245 |
| 0 | 47 | S | passed | 253 |
| 0 | 48 | S | passed | 324 |
| 0 | 49 | S | passed | 306 |

Instructions:

- task 0: put both the alphabet soup and the tomato sauce in the basket

Starts that failed at least 4 of 5 attempts: task 0 start 14, task 0 start 38

Attempts skipped by early decisions: 4; top-up episodes: 1.

## Result

- Stop reason: `budget_exhausted`
- Failing start: 14; reference (nearest passing start): 28; candidate references tried: 28 (passes)
- Entity-minimal: yes
- Checkpoint: `nvidia/gr00t17-lerobot-libero_10-640` at revision `5ee08ab09fac5c5ef2388a14c882ea825ac861db`

### Minimal cause

Moving alphabet_soup_1 by 2.5 cm (of the original 2.9 cm), moving cream_cheese_1 by 1.1 cm (of the original 1.1 cm), moving milk_1 by 2.4 cm (of the original 2.4 cm), moving orange_juice_1 by 3.7 cm (of the original 3.7 cm) and moving 6 joints of robot 88% of the way to their failing values are enough to make the policy fail from the passing start 28 (at least 4 of 5 attempts); sizes not fully shrunk; the reduction stopped early, so this is the smallest cause found so far.

Final selection: alphabet_soup_1 (position 0.875); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.875). This is a local minimum found by reruns, not proof of the globally smallest cause.

| entity | part | fraction t | lower bound tested | resolution | invalid midpoints |
| --- | --- | --- | --- | --- | --- |
| alphabet_soup_1 | position | 0.875 | 0.75 | 0.125 | - |
| robot | joints | 0.875 | 0.75 | 0.125 | - |
| orange_juice_1 | position | 1.0 | 0.875 | 0.125 | - |

## Differences between the failing start and the reference

| entity | position (cm) | rotation (deg) | joints | score |
| --- | --- | --- | --- | --- |
| robot | - | - | robot0_joint1 -1.47 deg, robot0_joint2 +2.13 deg, robot0_joint4 +2.64 deg, robot0_joint5 +2.53 deg, robot0_joint6 +1.16 deg, robot0_joint7 +0.585 deg | 1.1 |
| alphabet_soup_1 | 2.9 | - | - | 2.9 |
| cream_cheese_1 | 1.1 | - | - | 1.1 |
| tomato_sauce_1 | 0.7 | - | - | 0.7 |
| orange_juice_1 | 3.7 | - | - | 3.7 |
| milk_1 | 2.4 | - | - | 2.4 |

Score is centimetres plus degrees / 10, summed over the changed parts.

## Hypothesis

- Order source: `model`
- Model: nvidia/Nemotron-3-Ultra-550b-a55b (tier ultra)
- Ranking: alphabet_soup_1, tomato_sauce_1, robot, orange_juice_1, milk_1, cream_cheese_1
- Verdict (top-ranked entity against the surviving entities): **not available**

The alphabet soup moved 2.89 cm, the largest object shift, likely placing it outside the policy's learned grasp envelope or into collision with the basket (also shifted 2.16 cm). The tomato sauce moved 0.7 cm, which may be enough to miss a tight grasp tolerance. I predict that reverting only the alphabet soup to its reference pose will restore success, while reverting only the tomato sauce will not.

## Hypothesis vs result

- Hypothesis text: The alphabet soup moved 2.89 cm, the largest object shift, likely placing it outside the policy's learned grasp envelope or into collision with the basket (also shifted 2.16 cm). The tomato sauce moved 0.7 cm, which may be enough to miss a tight grasp tolerance. I predict that reverting only the alphabet soup to its reference pose will restore success, while reverting only the tomato sauce will not.
- Ranking: alphabet_soup_1, tomato_sauce_1, robot, orange_juice_1, milk_1, cream_cheese_1
- Scope: entity-minimal, sizes only partly shrunk (stop reason `budget_exhausted`)
- Measured label for the top-ranked entity (alphabet_soup_1): **necessary_not_sufficient**
- This was recomputed from the candidates in this summary; no new runs were made.

| rank | entity | in final selection | necessary | sufficient | label |
| --- | --- | --- | --- | --- | --- |
| 1 | alphabet_soup_1 | yes | yes | no | necessary_not_sufficient |
| 2 | tomato_sauce_1 | no | no | no | not_in_final |
| 3 | robot | yes | yes | no | necessary_not_sufficient |

Necessary: the final selection without that entity did not reproduce the failure. Sufficient: changing only that entity reproduced it. Both are read from reruns already in the candidate list, relative to this final selection.

### Evidence

- alphabet_soup_1, sufficient: no. Candidate #2 (probe) changed only alphabet_soup_1 (position 1): S S, did not reproduce.
- alphabet_soup_1, necessary: yes. Candidate #12 (ddmin) kept cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1): S S S S, did not reproduce (same entities and parts as the final selection without alphabet_soup_1, other sizes).
- tomato_sauce_1, sufficient: no. Candidate #3 (probe) changed only tomato_sauce_1 (position 1): S S, did not reproduce.
- tomato_sauce_1, necessary: no. Not in the final selection; candidate #32 without it still reproduced: S F F F F.
- robot, sufficient: no. Candidate #4 (probe) changed only robot (joints 1): S S, did not reproduce.
- robot, necessary: yes. Candidate #19 (ddmin) kept alphabet_soup_1 (position 1); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1): S S S, did not reproduce (same entities and parts as the final selection without robot, other sizes).

### What the ranking got right and missed

- Right: the top-ranked entity (alphabet_soup_1) is needed. The final selection without it did not reproduce the failure.
- Missed: alphabet_soup_1 alone does not reproduce the failure, so it is necessary but not sufficient.
- 2 of the top 3 ranked entities are in the final selection (5 entities survive).
- Also in the final selection but not in the top 3: cream_cheese_1, milk_1, orange_juice_1.

The hypothesis text is free prose; this section compares only the ranking with the measurements and does not interpret the prose.

## Candidates

Every rerun, in order. Phases: `gate` (the failing start must fail 4 of 5, the reference pass 5 of 5), `probe` (one difference alone), `ddmin` (smaller and smaller groups of differences), `shrink` (smaller shares of each kept difference). A selection's number is its share: `robot (joints 0.75)` applies 75% of the arm's offset to the reference. Outcomes: S success, F policy failure, I invalid scene. `skipped`: attempts not run because the answer was already certain; `late`: attempts already running when it was decided, shown but not counted. See docs/how-reduction-works.md.

| # | phase | role | selection | outcomes | decision | gate met | skipped | late |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | gate | failing | - | F F F F | reproduces | True | 1 | - |
| 1 | gate | reference 28 | - | S S S S S | passes | True | 0 | - |
| 2 | probe | hybrid 28 | alphabet_soup_1 (position 1) | S S | does_not_reproduce | False | 1 | S S |
| 3 | probe | hybrid 28 | tomato_sauce_1 (position 1) | S S | does_not_reproduce | False | 1 | S S |
| 4 | probe | hybrid 28 | robot (joints 1) | S S | does_not_reproduce | False | 1 | S S |
| 5 | probe | hybrid 28 | orange_juice_1 (position 1) | S S S S | does_not_reproduce | False | 1 | - |
| 6 | probe | hybrid 28 | milk_1 (position 1) | S S | does_not_reproduce | False | 1 | S S |
| 7 | probe | hybrid 28 | cream_cheese_1 (position 1) | S S S | does_not_reproduce | False | 1 | S |
| 8 | ddmin | hybrid 28 | alphabet_soup_1 (position 1); robot (joints 1); tomato_sauce_1 (position 1) | S S | does_not_reproduce | False | 1 | S S |
| 9 | ddmin | hybrid 28 | cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1) | S S S S | does_not_reproduce | False | 1 | - |
| 10 | ddmin | hybrid 28 | alphabet_soup_1 (position 1); tomato_sauce_1 (position 1) | S S | does_not_reproduce | False | 1 | S S |
| 11 | ddmin | hybrid 28 | orange_juice_1 (position 1); robot (joints 1) | S S S S | does_not_reproduce | False | 1 | - |
| 12 | ddmin | hybrid 28 | cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | S S S S | does_not_reproduce | False | 1 | - |
| 13 | ddmin | hybrid 28 | alphabet_soup_1 (position 1); cream_cheese_1 (position 1); milk_1 (position 1); tomato_sauce_1 (position 1) | S S | does_not_reproduce | False | 1 | S S |
| 14 | ddmin | hybrid 28 | alphabet_soup_1 (position 1); cream_cheese_1 (position 1); orange_juice_1 (position 1); robot (joints 1); tomato_sauce_1 (position 1) | S S | does_not_reproduce | False | 1 | S S |
| 15 | ddmin | hybrid 28 | alphabet_soup_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1); tomato_sauce_1 (position 1) | S S | does_not_reproduce | False | 1 | F F |
| 16 | ddmin | hybrid 28 | cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1); tomato_sauce_1 (position 1) | S S S S | does_not_reproduce | False | 1 | - |
| 17 | ddmin | hybrid 28 | alphabet_soup_1 (position 1); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | F F F F | reproduces | True | 1 | - |
| 18 | ddmin | hybrid 28 | alphabet_soup_1 (position 1); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); tomato_sauce_1 (position 1) | S S S S | does_not_reproduce | False | 1 | - |
| 19 | ddmin | hybrid 28 | alphabet_soup_1 (position 1); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1) | S S S | does_not_reproduce | False | 1 | S |
| 20 | ddmin | hybrid 28 | alphabet_soup_1 (position 1); cream_cheese_1 (position 1); milk_1 (position 1); robot (joints 1) | S S | does_not_reproduce | False | 1 | S S |
| 21 | ddmin | hybrid 28 | alphabet_soup_1 (position 1); cream_cheese_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | S S S F | does_not_reproduce | False | 1 | - |
| 22 | ddmin | hybrid 28 | alphabet_soup_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | S F F F S | does_not_reproduce | False | 0 | - |
| 23 | shrink | hybrid 28 | alphabet_soup_1 (position 0.5); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | S S | does_not_reproduce | False | 1 | S S |
| 24 | shrink | hybrid 28 | alphabet_soup_1 (position 0.25); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | S S | does_not_reproduce | False | 1 | S S |
| 25 | shrink | hybrid 28 | alphabet_soup_1 (position 0.75); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | S S | does_not_reproduce | False | 1 | F F |
| 26 | shrink | hybrid 28 | alphabet_soup_1 (position 0.625); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | S S | does_not_reproduce | False | 1 | F F |
| 27 | shrink | hybrid 28 | alphabet_soup_1 (position 0.875); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | S F F F F | reproduces | True | 0 | - |
| 28 | shrink | hybrid 28 | alphabet_soup_1 (position 0.875); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.5) | S F F F S | does_not_reproduce | False | 0 | - |
| 29 | shrink | hybrid 28 | alphabet_soup_1 (position 0.875); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.25) | S S S S | does_not_reproduce | False | 1 | - |
| 30 | shrink | hybrid 28 | alphabet_soup_1 (position 0.875); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.75) | S S | does_not_reproduce | False | 1 | F S |
| 31 | shrink | hybrid 28 | alphabet_soup_1 (position 0.875); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.625) | S S | does_not_reproduce | False | 1 | F F |
| 32 | shrink | hybrid 28 | alphabet_soup_1 (position 0.875); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.875) | S F F F F | reproduces | True | 0 | - |
| 33 | shrink | hybrid 28 | alphabet_soup_1 (position 0.875); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 0.5); robot (joints 0.875) | S S | does_not_reproduce | False | 1 | S S |
| 34 | shrink | hybrid 28 | alphabet_soup_1 (position 0.875); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 0.25); robot (joints 0.875) | S S S | does_not_reproduce | False | 1 | S |
| 35 | shrink | hybrid 28 | alphabet_soup_1 (position 0.875); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 0.75); robot (joints 0.875) | S S S | does_not_reproduce | False | 1 | S |
| 36 | shrink | hybrid 28 | alphabet_soup_1 (position 0.875); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 0.625); robot (joints 0.875) | S S | does_not_reproduce | False | 1 | S S |
| 37 | shrink | hybrid 28 | alphabet_soup_1 (position 0.875); cream_cheese_1 (position 1); milk_1 (position 1); orange_juice_1 (position 0.875); robot (joints 0.875) | S S | does_not_reproduce | False | 1 | S S |

Invalid scenes (never counted as failures): none

## Effort

- Candidates tested: 36; attempts run: 157 (gate attempts 9, hybrid attempts 148); attempts skipped by early decisions: 33
- Job seconds: 1566.809; server start-up seconds: 14.649
- Estimated compute cost at the given rate (an estimate, not billing): $0.76

## Videos

| role | case id | outcome | video (relative to the Job's scenario folder) |
| --- | --- | --- | --- |
| minimal | hyb-e73bc47b449c186a-a02 | policy_failure | runs/hyb-e73bc47b449c186a-a02/episodes/scn-hyb-e73bc47b449c186a-a02/task0000_ep0000_fail.mp4 |
| original | fail-1bd80389d1842fef-a02 | policy_failure | runs/fail-1bd80389d1842fef-a02/episodes/scn-fail-1bd80389d1842fef-a02/task0000_ep0000_fail.mp4 |
| reference | ref28-d079c26b3e1034e2-a03 | success | runs/ref28-d079c26b3e1034e2-a03/episodes/scn-ref28-d079c26b3e1034e2-a03/task0000_ep0000_success.mp4 |

