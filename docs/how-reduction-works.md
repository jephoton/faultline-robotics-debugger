# How a scenario reduction works

This is the technical explanation of Mode 1: how Faultline gets from "this
start fails" to "these shifts are what make it fail", what every rerun is for,
and how to read the report's **Candidates** table. The code is
`src/robot_debug/scenario_reduce.py` (the search, run inside the GPU Job),
`src/robot_debug/decided_gate.py` (the 4-of-5 rule) and
`src/robot_debug/orchestrator.py` (the runs around it). Design:
[ADR 0028](decisions/0028-m7-scenario-reduction-design.md) and
[ADR 0029](decisions/0029-m3-latency-startup-and-early-decided-gates.md). For using the interface, see the
[UI runbook](ui-runbook.md).

## Words used below

| Word | Meaning |
| --- | --- |
| **Benchmark start** | One of the 50 fixed starting layouts LIBERO provides for each task (where each object and the arm begin). |
| **Failing start** | The start being diagnosed: a benchmark start, or a state file you import. |
| **Reference** | A benchmark start of the same task on which the policy passes 5 of 5: the control. Faultline uses the passing start whose layout is closest to the failing one. |
| **Difference** | One thing that differs between the failing start and the reference, per **entity**: an object (its position, rotation, or its own hinge/slide joints such as a drawer) or the robot (its arm joints). |
| **Hybrid** | The reference with some differences applied. "hybrid 28" in the report is start 28 with the listed shifts. |
| **Selection / share** | Which differences a hybrid applies and how far: `robot (joints 0.75)` moves the arm 75% of the way from its reference pose to its failing pose. Share 100% (`1`) is the full difference. |
| **Rerun / candidate** | One scene (failing start, reference or hybrid) run several times under the gate below. |

## The gate: when does a scene "fail"?

Every scene is run up to **5 attempts**, because the policy is not
deterministic: the same scene can pass once and fail the next time.

- **Failure gate** (failing start and hybrids): the scene **reproduces** when
  at least **4 of 5** attempts are policy failures.
- **Pass gate** (references): the scene **passes** only if **5 of 5** attempts
  succeed.

Attempts are decided as early as the answer is certain, to save GPU time
(ADR 0029):
- A failure gate stops at 4 failures (reproduces) or at 2 successes (it can no
  longer reach 4 of 5: does not reproduce).
- It holds the fifth attempt back and runs it only when the first four give
  exactly three failures, the one case where it still matters.
- A pass gate stops at its first failure.

That is what two report columns record:

- **skipped:** attempts never run because the answer was already certain. A
  `1` next to `F F F F` means the fifth attempt was not needed.
- **late:** attempts that were already running when the answer was decided.
  They finish and are shown, but never change the decision. They are worth
  reading: a late `F` after `S S` shows the scene sometimes fails anyway.

A scene where objects start interpenetrating is marked `invalid_scene` and
never counts as a policy failure.

## The flow, step by step

### Before the GPU Job

1. **Screen** (one Job). Runs the failing start and a pool of nearby benchmark
   starts (by default starts 0–19, or the spec's `scenario.pool`). The failing
   start must fail; passing starts become candidate references, ordered by
   how close their layout is (centimetres of object movement plus degrees of
   rotation and joint angle divided by ten, summed).
2. **Plan.** Lists the differences against each candidate reference.
   Nemotron 3 Ultra (or a fixed order without Nemotron) ranks which entities to
   try first. The ranking only sets the order; it never decides anything.

### Inside the reduction Job

3. **Gates.** The failing start must reproduce, or the run stops with
   `failing_not_reproducible`. The nearest reference must pass 5 of 5; if it
   does not, the next nearest is tried, up to three, then `reference_not_passing`.
   Then the **full hybrid**, the reference with every difference applied, must
   reproduce. If it does not, the differences between the two layouts are not
   enough to explain the failure (for example, something not captured as a
   difference matters), and the run stops with `failing_not_reproducible`.
4. **Ranked probe.** Each entity alone, in the ranked order. If one alone
   reproduces, it is the cause on its own: the delta-debugging step is skipped
   and the run goes straight to splitting and shrinking.
5. **Delta debugging (`ddmin`).** Starting from all differences applied, it
   tries smaller groups: first halves, then the complement of each group
   (everything except that group), then smaller pieces. Whenever a smaller
   group still reproduces, that becomes the new set. It ends when removing any
   single entity makes the failure go away: the set is **entity-minimal** (a
   local minimum, not proof that no other combination exists).
6. **Split.** Each surviving object is tried with only its position change
   and only its rotation change; if one part alone is enough, the other is
   dropped. Joints stay one part.
7. **Shrink.** Each surviving part is bisected from 100% towards 0: try 50%;
   if it still reproduces keep 50% and try 25%, otherwise try 75%, and so on,
   for four steps (resolution 1/16 of the original difference). With spare
   GPU workers, two points are tried at once ("speculative" bisection).

Every candidate is cached by the exact scene it builds, so the same hybrid is
never run twice. The Job stops at its candidate budget (`budget_exhausted`)
or deadline.

### After the Job

8. **Continue if needed.** If a Job stops at its budget before the set is
   entity-minimal, the run starts a **continuation** Job from the smallest
   set that reproduced, up to three continuations. Continuations stop once the
   set is entity-minimal, even when sizes are not yet shrunk; that is why a
   case can be entity-minimal with every share at 100%.
9. **Measure the guess.** For the entities Nemotron ranked first, the reruns
   already run answer two questions without new GPU time:
   - **necessary:** does removing it from the final set make the failure go
     away?
   - **sufficient:** does it reproduce alone?

   "Necessary but not sufficient" means it is part of the cause but not all of
   it.
10. **Write up.** The report, the case (with the replay inputs: the minimal
    scene and the reference), the videos, Nemotron's reading of the verified
    result, and the library entry.

## Worked example: `FL-S-AFB5`

LIBERO-10 task 0, an imported failing start (benchmark start 14), reference
28. The rows are the report's **Candidates** table from the continuation Job.

| Rows | Phase | What happened |
| --- | --- | --- |
| 0–1 | gate | The failing start failed 4 of 4 (fifth skipped); start 28 passed 5 of 5. |
| 2–7 | probe | Each of the six entities alone (robot, soup, tomato sauce, orange juice, milk, cream cheese): all passed. No single culprit. |
| 8–17 | ddmin | Groups of the six and their complements: none reproduced. |
| 18 | ddmin | The five without the tomato sauce: 4 of 4 failures. The new set. |
| 19–22 | ddmin | Each of the five removed in turn: all passed. Entity-minimal. |
| 23–25 | shrink | The arm offset at 50% and 25% (both not reproducing), then 75%: reproduces. |

The budget ended there. The recorded case keeps the arm at 100%: a defect
fixed on October 18 kept the verified 75% from being recorded. New runs
record it. The tomato sauce, which Nemotron ranked third, is the one entity
the failure does not need.

## Reading the Candidates table

| Column | Meaning |
| --- | --- |
| `#` | Rerun number, in the order they were decided. |
| `phase` | `gate`, `probe`, `ddmin` or `shrink` (steps 3–7 above). |
| `role` | `failing`, `reference N`, or `hybrid N` (reference N with the selection applied). |
| `selection` | The differences applied and their share, for example `robot (joints 0.75)`. |
| `outcomes` | Each attempt that counted: `S` success, `F` policy failure, `I` invalid scene. |
| `decision` | `reproduces` (4 of 5 failures), `passes` (reference, 5 of 5), `does_not_reproduce`, or `invalid_scene`. |
| `gate met` | Whether the rule for that role was met. |
| `skipped` | Attempts not run because the answer was already certain. |
| `late` | Attempts already running when the answer was decided; shown, not counted. |

## What this does and does not show

- It shows which differences between two specific layouts are needed for this
  policy (one checkpoint) to fail this task, by direct reruns.
- It is a local minimum: another combination of differences might also cause
  a failure.
- It does not explain why the policy fails (for example, a perception or
  grasping problem). The videos, and Nemotron's labelled interpretation, are
  where that question starts.
