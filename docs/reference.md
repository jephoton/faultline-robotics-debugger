# Faultline reference

The documentation for what Faultline does and what everything it shows means:
the two modes, the repeatability gate, how a reduction works, every stress-test
severity, every report column and abbreviation, the verdicts and stop reasons,
and how spending is capped. The control panel shows this page as
**Reference**. For step-by-step use of the interface, see the
[UI runbook](ui-runbook.md); for setup, the [quickstart](setup/diagnose.md).

## 1. What Faultline is for

Faultline turns a robot-policy failure into the **smallest confirmed
trigger** and keeps it as a **regression test** that reruns on every new
checkpoint. The policy runs in simulation (LIBERO on MuJoCo); the evidence is
reruns of the policy, never a model's opinion.

### Regression tests

In software, a **regression** is something that used to work and breaks after
a change; a **regression test** is a small saved check, rerun after every
change, that catches it. For a robot policy every fine-tune or retrain is a
change. Each Faultline case pins one failure: `faultline replay` reruns its
minimal scene and passing reference on any checkpoint and says whether the
failure still reproduces (`--expect fixed` or `--expect reproduces` turns that
into a pass/fail exit code for a script or CI job).

### Two kinds of diagnosis

Both modes produce cases for the same suite. They differ in what you start
from and what question is asked.

| | **Find why a start fails** | **Stress-test a passing start / Test rewordings** |
| --- | --- | --- |
| You start from | A start where the policy **fails**: a benchmark start you know, a range to search, or your own start-state file | A start where the policy **passes** |
| Question | "Which of the differences between this failing layout and a passing one make it fail?" | "What change to what the policy sees or is told makes it fail, and how much is needed?" |
| What is varied | Real scene differences between two layouts: object positions and rotations, the arm's starting joints | Disturbances added on purpose: image effects, camera position, lighting, or the wording of the instruction |
| Reference | Found automatically: the nearest benchmark start that passes 5 of 5 | The start itself, run undisturbed (the control) |
| Result | The minimal set of differences needed (a scenario case with videos and replay inputs) | The smallest severity that fails per family, or the smallest word change, or "no failure in the tested range" |
| Replay | Yes (minimal scene and reference) | Not yet |

Use **Find why a start fails** when you already have a failure (from your own
evaluation, or a start you suspect) and want its trigger. Use the stress test
or rewordings when the policy works and
you want to find what breaks it.

### Fault codes

Each case gets a display code such as `FL-S-AFB5`: `FL`, a letter for the
kind (`S` scenario reduction, `A` stress test/audit, `L` language/rewordings,
`M` the September occlusion case), and the first hex digits of the case id.
The full case id is always shown as well.

## 2. Glossary

| Term | Meaning |
| --- | --- |
| **Policy** | The robot model under test: NVIDIA GR00T N1.7, one checkpoint per LIBERO suite. |
| **Suite, task** | LIBERO's four suites (Object, Spatial, Goal, 10), ten tasks each, each with an instruction such as "put both the alphabet soup and the tomato sauce in the basket". |
| **Benchmark start** | One of the 50 fixed starting layouts LIBERO provides per task (where each object and the arm begin). |
| **Episode / attempt** | One run of the policy from a start until success or the step limit. |
| **Failing start** | The start being diagnosed by *Find why a start fails*: a benchmark start or an imported state file. |
| **Reference** | In *Find why a start fails*, a benchmark start of the same task that passes 5 of 5: the nearest such start. |
| **Control** | In a stress test or rewording test, the start run with no disturbance; it must pass for any disturbance to be judged. |
| **Entity** | One object in the scene, or the robot. |
| **Difference** | What differs for one entity between the failing start and the reference: position, rotation, or joints (the robot's arm joints, or an object's hinge/slide such as a drawer). |
| **Part** | One kind of difference of one entity (position, rotation or joints). |
| **Hybrid** | The reference with some differences applied. `hybrid 28` is start 28 with the listed shifts. |
| **Selection** | The differences a hybrid applies, each with its share. |
| **Share** | How far a difference is applied, from 0 (the reference) to 1 (100%, the failing value). `robot (joints 0.75)` moves the arm 75% of the way. |
| **Candidate / rerun** | One scene (failing start, reference or hybrid) judged by the gate. |
| **Minimal trigger / minimal cause** | The smallest set of differences found that still fails. The cause in the sense of *what* triggers the failure, not *why* the network fails. |
| **Entity-minimal** | Removing any one entity from the set makes the failure go away. |
| **Severity (`s`)** | The strength of a stress-test disturbance, from 0 (none) to 1 (strongest tested); see section 5. |
| **Threshold** | The smallest severity at which a family fails reproducibly. |
| **Meaning check** | A rule that drops a rewording if it loses an object or target word of the instruction. |

## 3. The repeatability gate

The policy is not deterministic: the same scene can pass once and fail the
next time. Every judgement therefore uses repeated attempts.

- **Failure gate** (failing starts, hybrids, disturbance levels): the scene
  **reproduces** when at least **4 of 5** attempts are policy failures.
- **Pass gate** (references, controls): the scene **passes** only if **5 of 5**
  attempts succeed.
- **Decided early.** A failure gate stops at 4 failures (reproduces) or 2
  successes (can no longer reach 4 of 5). It holds the fifth attempt back and
  runs it only when the first four give exactly three failures. A pass gate
  stops at its first failure. This saves GPU time.
- **skipped** (a report column): attempts not run because the answer was
  already certain.
- **late** (a report column): attempts already running when the answer was
  decided. They are shown but never change the decision; a late `F` after
  `S S` shows the scene sometimes fails anyway.
- **Invalid scene** (`I`): objects started interpenetrating. Never counted as
  a policy failure.

## 4. Find why a start fails: how a scenario reduction works

### Three ways to name the failing start

| Option | When to use it | What happens first |
| --- | --- | --- |
| **A benchmark start I know fails** (`scenario.start`) | Your evaluation already showed a failure on, say, start 14 of a task (LIBERO evaluations run the benchmark starts by number) | The start is confirmed: it must fail 4 of 5. |
| **Search a range of starts** (`scenario.screen`) | You suspect the task has weak starts but do not know which | Each start in the range (for example `10-49`) gets one attempt. A start that fails gets the **confirmation attempts** (default 4). It counts as failing reliably at 4 failures, so the default is the usual 4 of 5; more confirmation attempts make the gate more lenient (4 failures out of up to 9). The start with the most failures that meets the gate is diagnosed. |
| **A start file of my own** (`scenario.import`) | Your failure came from a layout that is not a benchmark start: your own randomised scene, or a state saved from your evaluation | The JSON start-state file is checked against the task's scene, then confirmed like a benchmark start. The case names it by a fingerprint of the file, not a start number. Any saved case's `minimal-candidate.json` is an example. |

After the failing start is confirmed, all three continue the same way.

### The flow

Each step either stops the run or passes to the next.

1. **Screen** (one Job). The failing start and a pool of nearby benchmark
   starts (by default 0–19, or the spec's `scenario.pool`) are run. Passing
   starts become candidate references, ordered by closeness: centimetres of
   object movement plus degrees of rotation and joint angle divided by ten,
   summed (the report's **score**).
2. **Plan.** The differences against each reference are listed. Nemotron 3
   Ultra (or a fixed order, without Nemotron) ranks which entities to try
   first. The ranking sets the order only.
3. **Gates.**
   - The failing start must reproduce, or the run stops
     (`failing_not_reproducible`).
   - The nearest reference must pass 5 of 5; if not, the next nearest is
     tried, up to three (`reference_not_passing`).
   - The **full hybrid** (every difference applied) must reproduce. If not,
     the measured differences do not explain the failure, and the run stops
     instead of reducing something meaningless.
4. **Probe.** Each entity alone, in the ranked order. If one alone
   reproduces, it is the cause on its own; step 5 is skipped.
5. **Delta debugging (`ddmin`).** From all differences, try smaller groups
   (halves, then the complement of each group, then smaller pieces). Any
   smaller group that still reproduces becomes the new set. It ends when
   removing any single entity makes it pass: **entity-minimal**. This is a
   local minimum, not proof that no other combination exists.
6. **Split.** Each surviving object is tried with only its position change
   and only its rotation change; a part that is not needed is dropped.
7. **Shrink.** Each surviving part is bisected from 100% towards 0 for four
   steps (resolution 1/16 of the difference): 50%, then 25% or 75%, and so on.
   With spare GPU workers two points are tried at once.
8. **Continuations.** If a Job hits its candidate budget before the set is
   entity-minimal, a new Job continues from the smallest set that reproduced
   (up to three). Continuations stop at entity-minimal, even when sizes are
   not yet shrunk, which is why a case can show every share at 100%.
9. **Measure the guess.** For the entities Nemotron ranked first, existing
   reruns answer: *necessary* (removing it from the final set makes the
   failure go away) and *sufficient* (it reproduces alone).
10. **Write up.** Report, case (with replay inputs), videos, Nemotron's
    labelled reading of the verified result, library entry.

Every candidate is cached by the exact scene it builds; the same hybrid never
runs twice.

### Worked example: `FL-S-AFB5`

LIBERO-10 task 0, an imported failing start (benchmark start 14), reference
28; the report's Candidates table from the continuation Job.

| Rows | Phase | What happened |
| --- | --- | --- |
| 0–1 | gate | The failing start failed 4 of 4 (fifth skipped); start 28 passed 5 of 5. |
| 2–7 | probe | Each of the six entities alone: all passed. No single culprit. |
| 8–17 | ddmin | Groups of the six and their complements: none reproduced. |
| 18 | ddmin | The five without the tomato sauce: 4 of 4 failures. The new set. |
| 19–22 | ddmin | Each of the five removed in turn: all passed. Entity-minimal. |
| 23–25 | shrink | The arm offset at 50% and 25% did not reproduce; at 75% it did. |

The budget ended there. The recorded case keeps the arm at 100%: a defect
fixed on October 18 discarded the verified 75%; new runs record it.

## 5. Stress tests and rewordings

### How an audit searches

1. **Control.** The chosen start, undisturbed, 5 attempts. If it does not pass
   reliably, nothing can be judged and the audit stops
   (`nominal_controls_failed`). The audit does not look for another start: the
   start is the question you asked.
2. **Sweep.** For each family, severities 0.2, 0.4, 0.6, 0.8 and 1.0 in that
   order, 5 attempts each. A level fails reproducibly at 4 of 5.
3. **Bisect.** At the first failing level, four steps between the last passing
   level and it narrow the threshold to 0.0125.
4. **Result per family.** "Fails from s = x", "No failure up to s = 1.00"
   (searched to the top, nothing reproduced), "Not tested" (the run stopped
   before this family) or "Incomplete" (stopped during it).

A level such as **1/5** means one of five attempts failed: not reproducible,
but worth noting. One family is tested at a time; combinations are not.

### Image families

These alter the **pictures the policy receives** from both cameras (agent view
and wrist, 256×256 pixels by default). The simulator and what an observer sees
are unchanged. They approximate camera and sensor effects; they do not
simulate them.

| Family | What changes | Formula | s = 0.2 | 0.4 | 0.6 | 0.8 | 1.0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Blur** (`blur`) | Out-of-focus lens | Gaussian sigma `8 s` px | 1.6 px | 3.2 px | 4.8 px | 6.4 px | 8 px |
| **Noise** (`noise`) | Grainy sensor in low light | Gaussian noise sigma `100 s` (of 0–255) | 20 | 40 | 60 | 80 | 100 |
| **Darken** (`darken`) | Underexposure | brightness × `(1 − 0.95 s)` | ×0.81 | ×0.62 | ×0.43 | ×0.24 | ×0.05 |
| **Contrast** (`contrast`) | Washed-out image | contrast × `(1 − 0.9 s)` | ×0.82 | ×0.64 | ×0.46 | ×0.28 | ×0.10 |
| **JPEG compression** (`jpeg`) | Low-bandwidth video link | JPEG quality `95 − 90 s` | 77 | 59 | 41 | 23 | 5 |
| **Colour cast** (`colour_cast`) | White-balance error (warm tint) | red × `(1 + 0.6 s)`, blue × `(1 − 0.6 s)` | R ×1.12, B ×0.88 | ×1.24, ×0.76 | ×1.36, ×0.64 | ×1.48, ×0.52 | ×1.60, ×0.40 |
| **Motion blur** (`motion_blur`) | Moving or shaking camera | horizontal kernel `1 + 30 s` px | 7 px | 13 px | 19 px | 25 px | 31 px |
| **Dead pixels** (`dead_pixels`) | Damaged sensor | fraction `0.2 s` of pixels stuck black or white | 4% | 8% | 12% | 16% | 20% |

Noise and dead pixels are random but repeatable: the pattern is a fixed
function of the episode, step, camera, family and severity, so every attempt
at a level sees the same frames and a replay reproduces them.

### Scene families

These change the **simulated scene** once, when the episode starts.

| Family | What changes | Formula | s = 0.2 | 0.4 | 0.6 | 0.8 | 1.0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Camera viewpoint** (`viewpoint`) | The agent-view camera moves sideways and turns back towards the table (wrist camera unchanged) | shift `0.10 s` m, turn `10 s`° | 2 cm, 2° | 4 cm, 4° | 6 cm, 6° | 8 cm, 8° | 10 cm, 10° |
| **Scene lighting** (`lighting`) | Every light dims | light × `(1 − 0.9 s)` | ×0.82 | ×0.64 | ×0.46 | ×0.28 | ×0.10 |

Calibration renders: `docs/experiments/assets/scene-family-calibration.png`
(lighting at s = 1: mean brightness 139 → 16, dark but visible).

### Rewordings

There is no severity. Nemotron 3 Super writes rewordings of the instruction;
the meaning check drops any that lose an object or target word; the original
wording is the control (2 attempts) and each rewording gets one screening
attempt. A rewording that fails is confirmed with the 4-of-5 gate and then
reduced by word edits to the smallest change that still fails.

### The September occlusion case

A grey rectangle over part of the agent-view image, described by position and
size as fractions of the image (not a severity), reduced by trimming edges.

## 6. Reading a report

Every report opens with a **Summary** (verdict, inputs, result, stop status),
then the evidence.

### Abbreviations used in reports

| Abbreviation | Meaning |
| --- | --- |
| `S`, `F`, `I` | Attempt outcomes: success, policy failure, invalid scene. |
| `s = 0.4` | Severity 0.4. |
| `1/5` | One of five attempts failed. |
| `hybrid 28`, `reference 28` | Start 28 with shifts applied; start 28 itself. |
| `fail-…`, `ref28-…`, `hyb-…` and `-a01` | Video case ids: failing start, reference 28, hybrid; `a01` is attempt 1. |
| `orig`, `p01` | The original wording; rewording 1. |
| `ddmin` | Delta debugging (section 4). |
| `robot0_joint1` | The robot's first arm joint (LIBERO's naming). |
| `alphabet_soup_1` | The simulator's name for an object (first alphabet soup). |

### Scenario report

| Section / column | Meaning |
| --- | --- |
| **Screen**: `task`, `start`, `outcomes`, `decision`, `max steps` | Each screened start: its attempts, whether it failed reliably or passed, and the longest episode in steps. |
| **Result / Minimal cause** | The verdict, failing start and reference, and the kept differences in a sentence and as a final selection. |
| **Differences**: `entity`, `position (cm)`, `rotation (deg)`, `joints`, `score` | Every difference between the failing start and the reference; `score` = cm + degrees / 10, summed. |
| **Hypothesis** | Nemotron's ranking and free-text hypothesis (or the fixed order). |
| **Hypothesis vs result**: `rank`, `entity`, `in final selection`, `necessary`, `sufficient`, `label` | Whether each top-ranked entity survived, was needed, and was enough alone, with the reruns that show it under **Evidence**. |
| **Candidates**: `#`, `phase`, `role`, `selection`, `outcomes`, `decision`, `gate met`, `skipped`, `late` | Every rerun (section 4): its number, step of the flow, scene, attempts, decision, whether the gate rule was met, and skipped and late attempts (section 3). |
| **Effort** | Candidates tested, attempts run and skipped, Job seconds, an estimated compute cost. |
| **Videos**: `role`, `case id`, `outcome`, `video` | Which recorded episode is the original, minimal and reference clip. |

Hypothesis labels:

| Label | Meaning |
| --- | --- |
| `necessary_not_sufficient` | Needed in the final set, but not enough alone. |
| `sufficient_not_necessary` | Enough alone, but the final set does not need it. |
| `confirmed` | Needed and enough alone, and the only entity left. |
| `not_in_final` | Not part of the final set. |
| `inconclusive` | The reruns do not settle it. |

### Stress-test report

| Column | Meaning |
| --- | --- |
| `Family` | The disturbance family (section 5). |
| `Smallest reproducibly failing severity` | The threshold, or "none up to 1". |
| `Physical value` | The threshold in physical units (for example blur 3.2 px). |
| `Last non-reproducing level` | The highest severity below the threshold that did not fail reliably. |
| `Levels tried`, `Episodes` | How many severities and episodes the family used. |
| `Stop reason` | Why the family's search ended. |
| `Agent view mean / std ratio at threshold`, `Wrist …` | How much the disturbance changed the camera images' brightness (mean) and contrast (standard deviation), as perturbed / undisturbed (1.00 / 1.00 = unchanged). |
| `Levels in the order tried` | Each severity tried with failures / attempts. |

### Rewording report

| Column | Meaning |
| --- | --- |
| `label` | `orig` (the original) or `p01`… |
| `kind` | `original` or `paraphrase`. |
| `outcomes`, `decision` | Its attempts; `control`, `passed`, or a failure confirmed by the gate. |
| `word edits` | How many words differ from the original. |
| `meaning check` | `kept` or `dropped` (lost an object or target word). |
| `instruction` | The wording itself. |

## 7. Verdicts, run statuses and stop reasons

| Case verdict | Meaning |
| --- | --- |
| **Failure repeats** | The failure met the 4-of-5 gate. |
| **No failure found** | Nothing met the gate in the tested range. Bounded evidence, not proof of robustness. |
| **Stopped** | The diagnosis ended before its question was answered; see the stop reason. |
| **Incomplete** | The run did not finish its work. |
| **Run failed** | A local or provider error; not a policy failure. |

Run statuses on the run page: **Submitting a Job**, **Waiting for a GPU**,
**Running**, **Downloading results**, **Stopping**, **Completed**,
**Stopped**, **Failed**, **Interrupted**.

| Stop reason | Meaning |
| --- | --- |
| `budget_exhausted` | Stopped at the candidate budget; the result is the smallest found so far. |
| `nominal_controls_failed` | The undisturbed start did not pass reliably, so no disturbance can be judged. |
| `no_reproducible_failure` | Nothing failed 4 of 5: a finished negative result. |
| `no_reference` / `reference_not_passing` | No nearby benchmark start passed reliably. |
| `failing_not_reproducible` / `no_faithful_failure` | The failing start (or imported start, or full hybrid) did not fail reliably. |
| `import_invalid`, `import_mismatch` | The imported file was not valid, or does not match the task's scene. |
| `original_mismatch` | The original wording did not match the task. |
| `capacity_unavailable` | No GPU after six submissions. |
| `spend_cap`, `max_hours` | The next Job could exceed the spend cap; the hour limit was reached. |
| `stopped_by_user` | Stopped from the control panel or `faultline stop`. |
| `backend_error`, `auth_expired` | A cloud call failed (resume to re-attach); the Nebius sign-in expired. |
| `process_ended` | The run's process ended unexpectedly; Resume re-attaches. |

## 8. Spending and the cap

Before each Job, the run reserves its **worst case**:
- The provider timeout: the Job's deadline plus ten minutes, rounded up to a
  whole minute.
- A four-minute start allowance.
- Both at the hourly rate in the spec.

A Job is refused if that reservation would exceed the cap. When it finishes,
the reservation is replaced by the measured container time.
- Only the first Job of a plan must fit the cap to start; a later Job that
  does not fit stops the run, which can be resumed after raising the cap.
- The cap covers Nebius Serverless Jobs only, not Token Factory calls or
  storage.
- Costs are estimates from measured time until reconciled against the bill.

## 9. What results do and do not show

- They show, by reruns, what makes this policy (one checkpoint) fail this task
  from these starts, or that it did not fail within the tested range.
- A minimal trigger is a local minimum: another combination might also fail.
- They do not explain why the network fails. The videos and Nemotron's
  labelled reading are where that question starts.
- Image families approximate camera effects; scene families change only the
  camera pose and lights; one family at a time.
