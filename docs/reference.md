# Faultline reference

The documentation for what Faultline does and what everything it shows means:
the diagnosis and its routes, the repeatability gate, how a reduction works, every stress-test
severity, every report column and abbreviation, the verdicts and stop reasons,
and how spending is capped. The control panel shows this page as
**Reference**. For step-by-step use of the interface, see the
[UI runbook](ui-runbook.md); for setup, the [quickstart](setup/diagnose.md).

## 1. What Faultline is for

Faultline finds **the smallest condition under which a robot policy fails**
and keeps it as a **regression test** that reruns on every new checkpoint.
The policy runs in simulation (LIBERO on MuJoCo). The evidence is reruns of
the policy, never a model's opinion.

### Where it applies

**Today:** GR00T N1.7 checkpoints on the LIBERO benchmark. That means four
suites, 40 tasks and one simulated robot arm (a Franka Panda in MuJoCo).

- **Benchmark starts are LIBERO's own.** Each LIBERO task ships 50 fixed
  starting layouts, so every team that evaluates on LIBERO tests the same
  situations. Other benchmarks number their situations differently (seeds,
  episode configs), and a real robot has no numbered starts.
- **From an episode number to a start.** In the standard LIBERO evaluation,
  episode *n* of a task (counted from 0) begins from start *n*. For example,
  allenai's vla-evaluation-harness calls `set_init_state(initial_states[episode_idx])`
  and records `episode_id` per episode. Tools differ, though:
  - OpenVLA's LIBERO script counts episodes from 1, and its video file names
    count across tasks;
  - Isaac-GR00T's own LIBERO evaluation does not use the fixed starts at all.

  Check how your tool numbers episodes. A start reproduces the same scene only
  with the same simulator versions.
- **A start file** is a start state for one of LIBERO's own tasks: the same
  objects and the same arm, in a layout outside the 50. It is not a way to
  bring a different robot, scene or simulator.
- **The method is not tied to LIBERO**: confirm by reruns, shrink the
  differences, find thresholds, keep a test. Another simulator needs an
  adapter, and none is built. The adapter must:
  - reset to an exact saved state;
  - describe that state as object and robot positions that can be shifted;
  - rerun the policy from it;
  - check success;
  - expose camera images (for the disturbance probes, the most portable
    part).
- **Real robots are out of scope.** They cannot be reset to an exact state,
  and repeated attempts at this scale would be too costly.

### The regression test

In software, a **regression** is something that used to work and breaks after
a change. A **regression test** is a small saved check, rerun after every
change, that catches it.

For a robot policy, every fine-tune or retrain is a change. Each Faultline
case pins one failing condition. The **Regression test** section of a case
page (`faultline replay` on the command line) reruns that condition on the
policy you choose and says whether it still fails:

- **The original policy** is the checkpoint the case was found with. The test
  confirms the failure still repeats.
- **A new checkpoint** is a Hugging Face id plus a revision (both are needed,
  so the result names exactly which policy ran). The test says whether the
  failure is gone.

Each result in the history names the checkpoint it tested. A failure that is
gone on a new checkpoint is **Fixed**. The same result on the original policy
is **Did not repeat** (amber), not "fixed": nothing changed, so the case may
be flaky. A fixed failure that comes back in a later checkpoint is what a
regression test catches.

`--expect fixed` or `--expect reproduces` turns the verdict into a pass/fail
exit code for a script or CI job. The command has no checkpoint flag: a new
checkpoint goes under `policy.checkpoint` in the replay spec.

A regression test is not a new diagnosis:

| | Regression test (replay) | New diagnosis |
| --- | --- | --- |
| Question | Is this known failure fixed, and does it stay fixed? | Where does this policy fail now? |
| What runs | The pinned condition, 5 attempts | A fresh check and search |
| Repeatable | Yes | No |

### What the regression test reruns

| Case | The test reruns | Verdict |
| --- | --- | --- |
| Layout reduction | The minimal scene and its passing reference, 5 attempts each | Still fails / no longer |
| Disturbance probe | Each failing family at its threshold severity on the start, with the undisturbed control, 5 attempts each | Still fails at s = *x* / no longer fails |
| Rewording probe | The failing wording, with the original wording as the control | The wording still fails / no longer fails |

The case page shows the verdict in words, by the policy tested:

| Verdict | On a new checkpoint | On the original policy |
| --- | --- | --- |
| Still fails | **Still fails** (red) | **Still fails** (red) |
| No longer | **Fixed** (green) | **Did not repeat** (amber) |
| Anything else | **Inconclusive** (amber) | **Inconclusive** (amber) |

A replay from before checkpoints were recorded is shown as the original
policy, marked "checkpoint not recorded".

A test whose control does not pass, or whose Job does not finish, is
inconclusive, never a pass. A stress-test replay that stops after some of its
Jobs (a spend cap, a cloud error) keeps the verdicts of the Jobs that ran in
`replay-result.json` but has no verdict of its own, and `--expect` reports it
as inconclusive (exit 5).

The cost estimate is for the case being tested: a layout case plans one
Job, a stress-test case one Job per probe group that holds a failing family,
and a wording case one rewording-screen Job. The test's default spend
cap and hour limit (under **Limits**) are taken from that plan.

### One diagnosis, routed on the untouched result

There is one **New diagnosis**. You give it a task and a start, and it
promises: *find the smallest condition under which the policy fails here.*

1. **Check.** The start is run untouched (with confirmation attempts).
2. **If it fails reliably:** find the smallest *layout* change that triggers
   it. The differences between this start and the nearest passing benchmark
   start are reduced to the ones the failure needs (section 4).
3. **If it passes:** probe it with the disturbances and rewordings you chose.
   Each probe reports the smallest severity, or the smallest word change, that
   breaks it (section 5). If the probe's own control shows the start is
   unreliable untouched, the start is reported as **flaky** and nothing is
   blamed on a disturbance: the stress-test case is stopped, any threshold from
   another group is marked unconfirmed, and it has no replay. Each case is
   judged on its own control, so a failing rewording control leaves a passing
   stress test valid.
4. **Every failing condition becomes a replayable case.** The run's
   **findings** list them; "no failing condition in these ranges" is a valid
   finding too.

| What you send | Route | What comes back |
| --- | --- | --- |
| A start that fails untouched | **layout** | "Fails from this layout; smallest trigger: these shifts" |
| A start that passes | **probes** | "Passes untouched; breaks under blur from s = 0.50", or nothing breaks it |
| A start that fails sometimes (some attempts, but not 4 of 5) | **flaky** | "Unreliable even untouched"; no probe is run or blamed |
| A start that passes, with no probes chosen | **passes** | "Passes untouched" |

Two other ways in only look for a failure to reduce, without probing:
**Find a failing start for me** and **A failure from my own scene (file)** (section 4).

Defaults:
- The four image families **blur, noise, darken and contrast** (the only ones
  where the policy has failed before), no rewordings, and a **US$2.50** cap
  over **1.5 hours**.
- Typically about **US$1.25 and 45 minutes** when the start passes, and about
  **US$1.10 and 40 minutes** when it fails (measured runs on LIBERO-Object;
  GPU waits add time). The Review stretches the testing part of the check and
  of each probe for a suite with longer episodes, so LIBERO-10 shows more.
- The other six families and rewordings are one tick away. More families mean
  more probe Jobs, about half an hour each.

### Related research and next steps (optional)

With **Find related research** ticked and a Tavily key in `.env`, each new
case gets **Suggested next steps** in its Nemotron box:
- Tavily finds public sources about similar failures;
- Nemotron 3 Ultra receives the case's measured facts and those sources, and
  writes two to four steps a team could try. Each step cites a source or a
  rerun; citations are checked against the list, and invalid output is
  dropped.

They are suggestions, not evidence: they cannot say why this policy failed.
Only the cited sources are listed under them.

The tickbox starts ticked only when the machine has a Tavily key. Ticking it
without a key never stops a diagnosis: the Review shows a note and the run
skips the research.

### Fault codes

Each case gets a display code such as `FL-A-D582`: `FL`, a letter for the
kind, and the first hex digits of the case id. The full case id is always
shown as well. The letters are:
- `S`: a layout (scenario) reduction;
- `A`: a disturbance probe (audit);
- `L`: a rewording (language) probe;
- `M`: an occlusion case, from an earlier experiment mode. These are not made
  by the New diagnosis.

## 2. Glossary

| Term | Meaning |
| --- | --- |
| **Policy** | The robot model under test: NVIDIA GR00T N1.7, one checkpoint per LIBERO suite. |
| **Suite, task** | LIBERO's four suites (Object, Spatial, Goal, 10), ten tasks each, each with an instruction such as "put both the alphabet soup and the tomato sauce in the basket". |
| **Benchmark start** | One of the 50 fixed starting layouts LIBERO provides per task (where each object and the arm begin). |
| **Episode / attempt** | One run of the policy from a start until success or the step limit. |
| **Policy failure** | The task was not completed within the suite's step limit (LIBERO's standard limits: 220 steps for Spatial, 280 for Object, 300 for Goal, 520 for LIBERO-10; at 20 steps a second, 14 s for Object). It includes a policy that is too slow, not only one that does the wrong thing: under full-strength noise on `FL-A-D582`, the arm still grasps the can but runs out of time. |
| **Failing start** | A start that fails untouched (layout route): a benchmark start or an imported state file. |
| **Reference** | On the layout route, a benchmark start of the same task that passes 5 of 5: the nearest such start. |
| **Control** | On the probes route, the start run with no disturbance; it must pass for any disturbance to be judged. |
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

## 4. The layout route: how a scenario reduction works

### Three ways in

| Option | When to use it | What happens first |
| --- | --- | --- |
| **Check a start I name** (`diagnose.start`) | The usual choice. Most often a failure from your own LIBERO evaluation: in the standard LIBERO evaluation, episode *n* of a task (counted from 0) begins from benchmark start *n* (see Where it applies). Also any start you want to stress-test | The check: if it fails 4 of 5, the layout route; if it passes, the probes route (section 1). |
| **Find a failing start for me** (`diagnose.screen`) | You have no failure yet and want Faultline to find one in a range of starts | Each start in the range (for example `10-49`) gets one attempt. A start that fails gets the **confirmation attempts** (default 4). It counts as failing reliably at 4 failures, so the default is the usual 4 of 5; more confirmation attempts make the gate more lenient (4 failures out of up to 9). The start with the most failures that meets the gate is diagnosed. Layout route only: no probing. |
| **A failure from my own scene (file)** (`diagnose.import`) | Your failure came from a layout that is not one of the 50 benchmark starts: your own randomised scene, or a state saved from your evaluation | The JSON start-state file is checked against the task's scene, then confirmed like a benchmark start. The case names it by a fingerprint of the file, not a start number. Any saved case's `minimal-candidate.json` is an example. Layout route only. |

Older specs with `mode: scenario` and `scenario.start` / `screen` / `import` still work from the CLI; after the failing start is confirmed, all of them continue the same way.

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

### Worked example: `FL-S-8E0D`

LIBERO-10 task 0, benchmark start 14, with reference start 4. This is the
report's Candidates table across the reduction Job and its continuation. The
failing start and the reference differ in five entities: the soup, basket,
milk and orange juice positions, and the arm's joints.

| Rows | Phase | What happened |
| --- | --- | --- |
| 0–1 | gate | The failing start failed 4 of 5; start 4 passed 5 of 5. |
| 2–6 | probe | Each of the five alone: all passed. No single culprit. |
| 7–14 | ddmin | Groups of the five and their complements: none reproduced. |
| 15 | ddmin | The four without the soup: 4 of 4 failures. The new set. |
| 16–18 | ddmin | Each of three removed in turn: all passed. Without the arm (row 10) it also passed. Entity-minimal. |
| 19–25 | shrink | The arm: 50%, 25%, 75%, 62.5%, 87.5% and 81.25% did not reproduce; 93.75% did. |
| 26–32 | shrink | The basket: 93.75% kept. |
| 33–37 | shrink | The milk: 87.5% kept. |

The candidate budget ended before the orange juice was shrunk, so it stays at
100%.

**A limit, visible in rows 30–31.** The basket at 81.25% also reproduced
(4 of 5), but the case keeps 93.75%. Size shrinking halves the interval
step by step and assumes that if a smaller shift does not fail, no smaller
one does. At 87.5% the basket failed only 2 of 4, so the search moved
upward. A stochastic policy near the 4-of-5 line can break that assumption.
Every kept size is verified to reproduce, but it is not always the smallest
that does.

## 5. The probes route: disturbances and rewordings

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

A check that finds the start flaky ends the run. A probe control that fails
skips the probes still to come.

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
**Stopped**, **Failed**, **Interrupted**. Once the check is read, the run page
also shows the **route**: layout, probes, flaky or passes (section 1).

Colours:
- **Red**: a failure (with a cross).
- **Green**: a pass, including "No failure found" (with a tick).
- **Amber**: anything that needs attention: stopped, flaky, waiting for a GPU.
- Colour is never the only signal: an icon and a word go with it.

| Stop reason | Meaning |
| --- | --- |
| `budget_exhausted` | Stopped at the candidate budget; the result is the smallest found so far. |
| `nominal_controls_failed` | The undisturbed start did not pass reliably, so no disturbance can be judged. |
| `no_reproducible_failure` | Nothing failed 4 of 5: a finished negative result. |
| `check_incomplete` | The check ended before it decided the start (or the scene was invalid), so it is not known whether the start passes. Resume checks again. |
| `layout_skipped` | The start fails untouched while layout diagnosis was off ("probe only"): nothing to probe and no layout Job. |
| `no_reference` / `reference_not_passing` | No nearby benchmark start passed reliably. |
| `failing_not_reproducible` / `no_faithful_failure` | The failing start (or imported start, or full hybrid) did not fail reliably. |
| `import_invalid`, `import_mismatch` | The imported file was not valid, or does not match the task's scene. |
| `original_mismatch` | The original wording did not match the task. |
| `capacity_unavailable` | No GPU after six submissions. |
| `spend_cap`, `max_hours` | The next Job could exceed the spend cap; the hour limit was reached. The run page offers a larger cap or hour limit before **Resume** (raise only, never lower). |
| `download_failed` | The Job finished and is paid for, but its results could not be downloaded. Resume downloads them again (keeping files already complete) and does not run the Job again. |
| `stopped_by_user` | Stopped from the control panel or `faultline stop`. |
| `backend_error`, `auth_expired` | A cloud call failed (resume to re-attach); the Nebius sign-in expired. |
| `process_ended` | The run's process ended unexpectedly; Resume re-attaches. |
| `control_not_passing` | The original wording did not pass both control attempts, so a failing rewording cannot be attributed to the wording. |
| `paraphrase_failed`, `llm_required` | Nemotron could not write the rewordings (resume to retry), or they need Nemotron and it is off. |
| `original_unknown` | The task's own wording is not known, so its rewordings cannot be probed. |

## 8. Spending and the cap

Before each Job, the run reserves its **worst case**:
- The provider timeout: the Job's deadline plus ten minutes, rounded up to a
  whole minute.
- A four-minute start allowance.
- Both at the hourly rate in the spec.

A Job is refused if that reservation would exceed the cap. When it finishes,
the reservation is replaced by the measured container time.
- Only the first Job of a plan must fit the cap to start. A later Job that
  does not fit stops the run (`spend_cap`). On the run page, **Raise the limit
  before you resume** takes a larger cap or hour limit, then **Resume**
  continues. A limit can be raised, never lowered, and never below what is
  spent.
- The cap covers Nebius Serverless Jobs only, not Token Factory calls or
  storage.
- Costs are estimates from measured time until reconciled against the bill.

**Worst case and typical figures on Review.** The worst case is the check
plus the larger of the two branches, because only one branch runs. Beside it,
each branch shows a **typical** cost and time, modelled on measured runs. For
example: the check, about 16 minutes and US$0.43; four disturbance families,
about 29 minutes and US$0.82; a layout reduction, about 25 minutes and
US$0.68. These are estimates. GPU waits, longer tasks and finding a failure
(the narrowing steps) add time.

A default cap of US$2.50 can sit below the worst case (US$3.09) and still
cover the typical runs. The review then shows "The first Job fits, but not
all of them" and names the first Job of each branch that would be refused if
the Jobs before it cost their worst case. With the defaults on LIBERO-Object,
those are `reduce` and `probe-image-1`. A typical check (about US$0.43)
leaves room for either, so in practice the cap is reached only by a slow
check, a layout continuation or extra probe Jobs. Raise the cap if you want
those to run uninterrupted.

## 9. What results do and do not show

- They show, by reruns, what makes this policy (one checkpoint) fail this task
  from these starts, or that it did not fail within the tested range.
- A minimal trigger is a local minimum: another combination might also fail.
- They do not explain why the network fails. The videos and Nemotron's
  labelled reading are where that question starts.
- Image families approximate camera effects; scene families change only the
  camera pose and lights; one family at a time.
