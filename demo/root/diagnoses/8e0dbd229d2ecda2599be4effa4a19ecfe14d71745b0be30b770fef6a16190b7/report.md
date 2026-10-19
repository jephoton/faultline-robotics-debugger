# Scenario reduction: put both the alphabet soup and the tomato sauce in the basket

## Summary

- Verdict: Reproduces. Applying the kept shifts to the passing reference makes the policy fail at least 4 of 5 attempts.
- Failing start: benchmark start 14.
- Reference: benchmark start 4, the nearest start that passed.
- Kept shift: basket_1 position, 2.1 cm (93.8% of the full difference).
- Kept shift: milk_1 position, 2.2 cm (87.5% of the full difference).
- Kept shift: orange_juice_1 position, 0.8 cm (100% of the full difference).
- Kept shift: robot joints, 5 joints, up to 2.1° (93.8% of the full difference).
- Status: Stopped at the candidate budget: entity-minimal (each kept entity is needed), sizes not fully shrunk.

Suite `libero_10`, task 0. Reference runs decide everything below; the model only proposes an order and a hypothesis.

## Screen

Outcomes per start: S success, F policy failure, I invalid scene. The first letter is the unperturbed screen attempt; failing starts were confirmed with more attempts (4 of 5 failures reproduce).

| task | start | outcomes | decision | max steps |
| --- | --- | --- | --- | --- |
| 0 | 0 | S | passed | 251 |
| 0 | 1 | S | passed | 339 |
| 0 | 2 | F F F S F | reproduces | 520 |
| 0 | 3 | S | passed | 291 |
| 0 | 4 | S | passed | 275 |
| 0 | 5 | S | passed | 308 |
| 0 | 6 | S | passed | 273 |
| 0 | 7 | S | passed | 257 |
| 0 | 8 | S | passed | 294 |
| 0 | 9 | S | passed | 224 |
| 0 | 10 | S | passed | 297 |
| 0 | 11 | S | passed | 282 |
| 0 | 12 | S | passed | 249 |
| 0 | 13 | F S S S | does_not_reproduce | 520 |
| 0 | 14 | F F F F F | reproduces | 520 |
| 0 | 15 | S | passed | 257 |
| 0 | 16 | S | passed | 274 |
| 0 | 17 | S | passed | 241 |
| 0 | 18 | F S F F S | does_not_reproduce | 520 |
| 0 | 19 | S | passed | 279 |

Instructions:

- task 0: put both the alphabet soup and the tomato sauce in the basket

Starts that failed at least 4 of 5 attempts: task 0 start 2, task 0 start 14

Attempts skipped by early decisions: 2; top-up episodes: 1.

## Result

- Stop reason: `budget_exhausted`
- Failing start: 14; reference (nearest passing start): 4; candidate references tried: 4 (passes)
- Entity-minimal: yes
- Checkpoint: `nvidia/gr00t17-lerobot-libero_10-640` at revision `5ee08ab09fac5c5ef2388a14c882ea825ac861db`

### Minimal cause

Moving basket_1 by 2.1 cm (of the original 2.2 cm), moving milk_1 by 2.2 cm (of the original 2.6 cm), moving orange_juice_1 by 0.8 cm (of the original 0.8 cm) and moving 5 joints of robot 94% of the way to their failing values are enough to make the policy fail from the passing start 4 (at least 4 of 5 attempts); sizes not fully shrunk; the reduction stopped early, so this is the smallest cause found so far.

Final selection: basket_1 (position 0.9375); milk_1 (position 0.875); orange_juice_1 (position 1); robot (joints 0.9375). This is a local minimum found by reruns, not proof of the globally smallest cause.

| entity | part | kept size | largest size that passed | precision | invalid sizes |
| --- | --- | --- | --- | --- | --- |
| basket_1 | position | 93.8% | 87.5% | 6.25 points (1/16) | - |
| milk_1 | position | 87.5% | 75% | 12.5 points (1/8) | - |
| orange_juice_1 | position | 100% | not shrunk | - | - |
| robot | joints | 93.8% | 87.5% | 6.25 points (1/16) | - |

Sizes are shares of the full difference between the two starts. Kept size: verified to make the policy fail (at least 4 of 5 attempts). Largest size that passed: the largest smaller size tried that did not fail that often, over every reduction Job. Precision: the gap between the two. Invalid sizes were interpenetrating scenes and say nothing about the policy.

## Differences between the failing start and the reference

| entity | position (cm) | rotation (deg) | joints | score |
| --- | --- | --- | --- | --- |
| robot | - | - | robot0_joint1 -1.42 deg, robot0_joint2 +0.968 deg, robot0_joint4 +2.24 deg, robot0_joint5 -1.25 deg, robot0_joint7 +1.51 deg | 0.7 |
| alphabet_soup_1 | 1.7 | - | - | 1.7 |
| orange_juice_1 | 0.8 | - | - | 0.8 |
| milk_1 | 2.6 | - | - | 2.6 |
| basket_1 | 2.2 | - | - | 2.2 |

Score is centimetres plus degrees / 10, summed over the changed parts.

## Hypothesis

- Order source: `model`
- Model: nvidia/Nemotron-3-Ultra-550b-a55b (tier ultra)
- Ranking: robot, alphabet_soup_1, basket_1, milk_1, orange_juice_1
- Verdict (top-ranked entity against the surviving entities): **not available**

The robot's joint offsets (up to 2.2 deg) likely shift the end-effector several centimeters, misaligning grasps for both target objects. The alphabet soup moved 1.73 cm and tomato sauce 1.05 cm, so the combined pose error may push them outside the grasp tolerance. The basket moved 2.23 cm, which could also cause placement failures. I predict the simulator will show that reverting the robot joints to the reference values restores success even with the object shifts.

## Hypothesis vs result

- Hypothesis text: The robot's joint offsets (up to 2.2 deg) likely shift the end-effector several centimeters, misaligning grasps for both target objects. The alphabet soup moved 1.73 cm and tomato sauce 1.05 cm, so the combined pose error may push them outside the grasp tolerance. The basket moved 2.23 cm, which could also cause placement failures. I predict the simulator will show that reverting the robot joints to the reference values restores success even with the object shifts.
- Ranking: robot, alphabet_soup_1, basket_1, milk_1, orange_juice_1
- Scope: entity-minimal, sizes only partly shrunk (stop reason `budget_exhausted`)
- Measured label for the top-ranked entity (robot): **necessary_not_sufficient**

| rank | entity | in final selection | necessary | sufficient | label |
| --- | --- | --- | --- | --- | --- |
| 1 | robot | yes | yes | no | necessary_not_sufficient |
| 2 | alphabet_soup_1 | no | no | no | not_in_final |
| 3 | basket_1 | yes | yes | no | necessary_not_sufficient |

Necessary: the final selection without that entity did not reproduce the failure. Sufficient: changing only that entity reproduced it. Both are read from reruns already in the candidate list, relative to this final selection.

### Evidence

- robot, sufficient: no. Candidate #2 (probe) changed only robot (joints 1): S S S, did not reproduce.
- robot, necessary: yes. Candidate #10 (ddmin) kept basket_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1): S S S, did not reproduce (same entities and parts as the final selection without robot, other sizes).
- alphabet_soup_1, sufficient: no. Candidate #3 (probe) changed only alphabet_soup_1 (position 1): S S, did not reproduce.
- alphabet_soup_1, necessary: no. Not in the final selection; candidate #37 without it still reproduced: F F F F.
- basket_1, sufficient: no. Candidate #4 (probe) changed only basket_1 (position 1): S S S, did not reproduce.
- basket_1, necessary: yes. Candidate #16 (ddmin) kept milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1): S S, did not reproduce (same entities and parts as the final selection without basket_1, other sizes).

### What the ranking got right and missed

- Right: the top-ranked entity (robot) is needed. The final selection without it did not reproduce the failure.
- Missed: robot alone does not reproduce the failure, so it is necessary but not sufficient.
- 2 of the top 3 ranked entities are in the final selection (4 entities survive).
- Also in the final selection but not in the top 3: milk_1, orange_juice_1.

The hypothesis text is free prose; this section compares only the ranking with the measurements and does not interpret the prose.

## Candidates

Every rerun, in order. Phases: `gate` (the failing start must fail 4 of 5, the reference pass 5 of 5), `probe` (one difference alone), `ddmin` (smaller and smaller groups of differences), `shrink` (smaller shares of each kept difference). A selection's number is its share: `robot (joints 0.75)` applies 75% of the arm's offset to the reference. Outcomes: S success, F policy failure, I invalid scene. `skipped`: attempts not run because the answer was already certain; `late`: attempts already running when it was decided, shown but not counted. See the Reference page (docs/reference.md).

| # | phase | role | selection | outcomes | decision | gate met | skipped | late |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | gate | failing | - | S F F F F | reproduces | True | 0 | - |
| 1 | gate | reference 4 | - | S S S S S | passes | True | 0 | - |
| 2 | probe | hybrid 4 | robot (joints 1) | S S S | does_not_reproduce | False | 1 | S |
| 3 | probe | hybrid 4 | alphabet_soup_1 (position 1) | S S | does_not_reproduce | False | 1 | S S |
| 4 | probe | hybrid 4 | basket_1 (position 1) | S S S | does_not_reproduce | False | 1 | S |
| 5 | probe | hybrid 4 | milk_1 (position 1) | S S | does_not_reproduce | False | 1 | S S |
| 6 | probe | hybrid 4 | orange_juice_1 (position 1) | S S S | does_not_reproduce | False | 1 | S |
| 7 | ddmin | hybrid 4 | alphabet_soup_1 (position 1); basket_1 (position 1); robot (joints 1) | S S | does_not_reproduce | False | 1 | F S |
| 8 | ddmin | hybrid 4 | milk_1 (position 1); orange_juice_1 (position 1) | S S S | does_not_reproduce | False | 1 | F |
| 9 | ddmin | hybrid 4 | alphabet_soup_1 (position 1); robot (joints 1) | S S | does_not_reproduce | False | 1 | S S |
| 10 | ddmin | hybrid 4 | basket_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1) | S S S | does_not_reproduce | False | 1 | S |
| 11 | ddmin | hybrid 4 | alphabet_soup_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | S S | does_not_reproduce | False | 1 | S S |
| 12 | ddmin | hybrid 4 | alphabet_soup_1 (position 1); basket_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | S S | does_not_reproduce | False | 1 | S S |
| 13 | ddmin | hybrid 4 | alphabet_soup_1 (position 1); basket_1 (position 1); milk_1 (position 1); robot (joints 1) | S S | does_not_reproduce | False | 1 | F F |
| 14 | ddmin | hybrid 4 | alphabet_soup_1 (position 1); basket_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1) | S S S S | does_not_reproduce | False | 1 | - |
| 15 | ddmin | hybrid 4 | basket_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | F F F F | reproduces | True | 1 | - |
| 16 | ddmin | hybrid 4 | milk_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | S S | does_not_reproduce | False | 1 | S S |
| 17 | ddmin | hybrid 4 | basket_1 (position 1); orange_juice_1 (position 1); robot (joints 1) | S S S | does_not_reproduce | False | 1 | S |
| 18 | ddmin | hybrid 4 | basket_1 (position 1); milk_1 (position 1); robot (joints 1) | S S | does_not_reproduce | False | 1 | S S |
| 19 | shrink | hybrid 4 | basket_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.5) | S S | does_not_reproduce | False | 1 | S S |
| 20 | shrink | hybrid 4 | basket_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.25) | S S | does_not_reproduce | False | 1 | S S |
| 21 | shrink | hybrid 4 | basket_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.75) | S S | does_not_reproduce | False | 1 | F F |
| 22 | shrink | hybrid 4 | basket_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.625) | S S | does_not_reproduce | False | 1 | F S |
| 23 | shrink | hybrid 4 | basket_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.875) | S S F F | does_not_reproduce | False | 1 | - |
| 24 | shrink | hybrid 4 | basket_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.8125) | S F F F S | does_not_reproduce | False | 0 | - |
| 25 | shrink | hybrid 4 | basket_1 (position 1); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.9375) | F F F F | reproduces | True | 1 | - |
| 26 | shrink | hybrid 4 | basket_1 (position 0.5); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.9375) | S S | does_not_reproduce | False | 1 | S S |
| 27 | shrink | hybrid 4 | basket_1 (position 0.25); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.9375) | S S | does_not_reproduce | False | 1 | S S |
| 28 | shrink | hybrid 4 | basket_1 (position 0.75); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.9375) | S F F F S | does_not_reproduce | False | 0 | - |
| 29 | shrink | hybrid 4 | basket_1 (position 0.625); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.9375) | S S S F | does_not_reproduce | False | 1 | - |
| 30 | shrink | hybrid 4 | basket_1 (position 0.875); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.9375) | S F S F | does_not_reproduce | False | 1 | - |
| 31 | shrink | hybrid 4 | basket_1 (position 0.8125); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.9375) | S F F F F | reproduces | True | 0 | - |
| 32 | shrink | hybrid 4 | basket_1 (position 0.9375); milk_1 (position 1); orange_juice_1 (position 1); robot (joints 0.9375) | F F F F | reproduces | True | 1 | - |
| 33 | shrink | hybrid 4 | basket_1 (position 0.9375); milk_1 (position 0.5); orange_juice_1 (position 1); robot (joints 0.9375) | S S | does_not_reproduce | False | 1 | S S |
| 34 | shrink | hybrid 4 | basket_1 (position 0.9375); milk_1 (position 0.25); orange_juice_1 (position 1); robot (joints 0.9375) | S S | does_not_reproduce | False | 1 | S S |
| 35 | shrink | hybrid 4 | basket_1 (position 0.9375); milk_1 (position 0.75); orange_juice_1 (position 1); robot (joints 0.9375) | S S | does_not_reproduce | False | 1 | F F |
| 36 | shrink | hybrid 4 | basket_1 (position 0.9375); milk_1 (position 0.625); orange_juice_1 (position 1); robot (joints 0.9375) | S S S | does_not_reproduce | False | 1 | F |
| 37 | shrink | hybrid 4 | basket_1 (position 0.9375); milk_1 (position 0.875); orange_juice_1 (position 1); robot (joints 0.9375) | F F F F | reproduces | True | 1 | - |

Invalid scenes (never counted as failures): none

## Effort

- Candidates tested: 36; attempts run: 157 (gate attempts 10, hybrid attempts 147); attempts skipped by early decisions: 33
- Job seconds: 1702.208; server start-up seconds: 14.551
- Estimated compute cost at the given rate (an estimate, not billing): $0.83

## Videos

| role | case id | outcome | video (relative to the Job's scenario folder) |
| --- | --- | --- | --- |
| minimal | hyb-40afa3b101ed02a5-a02 | policy_failure | runs/hyb-40afa3b101ed02a5-a02/episodes/scn-hyb-40afa3b101ed02a5-a02/task0000_ep0000_fail.mp4 |
| original | fail-254b5e65d0d336bc-a02 | policy_failure | runs/fail-254b5e65d0d336bc-a02/episodes/scn-fail-254b5e65d0d336bc-a02/task0000_ep0000_fail.mp4 |
| reference | ref04-376f48b75f50d4e1-a01 | success | runs/ref04-376f48b75f50d4e1-a01/episodes/scn-ref04-376f48b75f50d4e1-a01/task0000_ep0000_success.mp4 |

