# Faultline reference

Use this page to interpret measured evidence, not to set up a run. For operation,
see [the quickstart](setup/diagnose.md); for exact clicks and demo scenarios,
the [UI runbook](ui-runbook.md); for system boundaries, [architecture](architecture.md).

## 1. What Faultline is for

Faultline finds a robot-policy failure, checks that it repeats, reduces its
triggering condition, and saves a case to test again after a policy change.
It searches a bounded space, not every possible failure mode.

The implemented environment is **NVIDIA GR00T N1.7 on LIBERO/MuJoCo**: four
suites, ten tasks each, one simulated Franka Panda arm. A **suite** groups
tasks; a **task** has a scene, instruction and success check; a **start** is
one initial layout. Disturbance families are separate: blur can be tested
across different tasks and suites.

LIBERO provides 50 fixed benchmark starts per task. A task-local, zero-based
episode number maps to its start only if the evaluator uses that ordering.
Other tools can number videos across tasks or randomize resets. Check the
producing evaluator and simulator versions before importing an episode number.
A start-state file supports another layout of an existing LIBERO task,
**not** a new robot, arbitrary video or different simulator.

There is one diagnosis workflow:

| Untouched start | What happens next |
| --- | --- |
| Fails reliably | Find a passing reference and reduce layout differences. |
| Passes | Try the selected disturbances and rewordings. |
| Fails sometimes but misses the failure gate | Stop as flaky; do not blame a disturbance. |
| Passes, with no probes selected | Record the pass; do not invent a failure. |

Range screening and imported failing-state inputs take the layout route only.
The sidebar has one **Cases** list, not separate product modes. Display
codes such as `FL-S-8E0D` identify cases: `S` layout, `A` disturbance, `L`
wording, `M` historical occlusion. They are not severity or coverage ratings.

## 2. Glossary

| Term | Meaning |
| --- | --- |
| Policy / checkpoint | The model under test and its pinned version. Suite-specific checkpoints are not interchangeable by assumption. |
| Episode / attempt | One policy rollout from a start until success or the step limit. |
| Policy failure | The task was not completed by the step limit, including running out of time. |
| Reference | A benchmark start of the same task that passes the reference gate. |
| Control | The undisturbed scene or original instruction, needed before attributing a result to a probe. |
| Entity / part | An object or robot; a part is its position, rotation or joint difference. |
| Hybrid / selection | A reference with selected differences applied. `hybrid 28` means changes applied to reference start 28. |
| Share | Fraction of a reference-to-failing difference: 0 is reference, 1 is the failing value. |
| Candidate / rerun | One condition evaluated with repeated attempts. |
| Minimal trigger / minimal cause | The smallest triggering condition found. “Cause” describes a trigger, not why the network fails. |
| Entity-minimal | Removing any single retained entity stops reproduction. Not a global minimum. |
| Severity / threshold | Strength within one family / smallest tested reproducibly failing level found. |
| Meaning check | A check for retained object/target words, not semantic equivalence. |

Step limits are Spatial 220, Object 280, Goal 300 and LIBERO-10 520. An arm
making progress in a video can still fail the task. `S`, `F`, `I` mean
success, policy failure and invalid scene. `1/5` means one failure in five
attempts, **not** a repeatable failure.

## 3. Repeatability and controls

| Gate | Required result | Early decision |
| --- | --- | --- |
| Failure | At least 4 failures out of 5 attempts | Stop at 4 failures or 2 successes. |
| Passing reference/control | Every required attempt succeeds | Stop on the first failure. |
| Original wording control | Both screening attempts succeed | Failed control blocks attribution to wording. |

The standard failure gate holds the fifth attempt back unless the first four
give exactly three failures. `skipped` counts attempts unnecessary to decide;
`late` counts already-running attempts arriving after the decision. Late
outcomes remain visible but do not reverse it. Invalid scenes are not policy
failures.

Four of five is an operational rule, not a formal guarantee or calibrated
probability estimate. A partly completed run may retain a finished case from
another group; that does not validate its incomplete group. If a probe's own
control fails, its disturbance cannot be established as the trigger.

## 4. Layout reduction

1. **Screen references.** Run the failing start and nearby benchmark starts
   (default pool 0–19). Rank passing references by the sum of movement in
   centimetres and rotation/joint angles in degrees divided by ten.
2. **Check reconstruction.** The failing start must reproduce, the reference
   must pass, and applying every difference to the reference must reproduce.
   Otherwise stop instead of reducing an unexplained difference.
3. **Probe alone.** Try individual entities, in Nemotron's proposed order
   or a fixed order. The simulator, not the ranking, decides the result.
4. **Reduce the set.** Delta debugging (`ddmin`) tries groups and complements.
   Keep smaller sets only when they reproduce. Check single removals to
   establish entity-minimality.
5. **Split and shrink.** Try retained position/rotation parts separately,
   then bisect shares toward the reference (default four steps, resolution
   1/16). Spare evaluator capacity can test speculative points together.
6. **Save.** Retain the verified trigger, reference, candidate history and
   replay inputs. Budgets can stop before sizes finish shrinking; continuation
   Jobs are bounded. Candidate caching avoids repeated work within a search,
   not every future replay.

Range screening gives each start one attempt, then confirms failed ones.
The default four confirmation attempts gives the usual 4-of-5 gate; changing
that count changes the screening evidence. Inspect actual attempt counts.

### Example and limit: FL-S-8E0D

LIBERO-10 task 0/start 14 was compared with passing start 4. None of five
entity shifts alone reproduced. Four shifts, excluding the soup, reproduced;
removing any retained entity did not. The group is entity-minimal, while
sizes remained partly reduced at the candidate budget.

The basket at **81.25%** also reproduced, but the saved size is **93.75%**.
An intermediate 87.5% candidate missed the gate, moving bisection upward.
Stochastic outcomes can violate the assumed monotonic relation between size
and failure. A verified kept size is not necessarily the smallest failing
size among recorded candidates, let alone globally. See the
[row-by-row walkthrough](ui-runbook.md) for the complete example.

## 5. Disturbance severity and rewordings

Each probe group checks an undisturbed control. The default sweep tries
`s = 0.2, 0.4, 0.6, 0.8, 1.0`; the first reproducing level starts four
bisection steps between it and the last non-reproducing level, giving
**0.0125** severity resolution. Families run separately, not in combinations.

“No failure up to s = 1.00” means the range was searched without meeting
the gate. **Not tested** means never searched; **Incomplete** means stopped
partway. Neither is evidence of robustness.

### Image families

These change images sent to the policy, from both agent and wrist cameras
(normally 256×256). The observer's unperturbed video may not show the altered
policy input. They approximate sensor effects, not full physical sensor
simulation. Severity is not comparable across families.

| Family | Transformation at severity s | At s = 1 |
| --- | --- | --- |
| Blur (`blur`) | Gaussian sigma `8s` px | 8 px |
| Noise (`noise`) | Gaussian sigma `100s`, on 0–255 | 100 |
| Darken (`darken`) | Brightness × `(1 − 0.95s)` | ×0.05 |
| Contrast (`contrast`) | Contrast × `(1 − 0.9s)` | ×0.10 |
| JPEG (`jpeg`) | Quality `95 − 90s` | Quality 5 |
| Colour cast (`colour_cast`) | Red × `(1 + 0.6s)`, blue × `(1 − 0.6s)` | Red ×1.60, blue ×0.40 |
| Motion blur (`motion_blur`) | Horizontal kernel `1 + 30s` px | 31 px |
| Dead pixels (`dead_pixels`) | Fraction `0.2s` stuck black/white | 20% |

Noise/dead-pixel randomness is seeded from episode, step, camera, family and
severity. Perturbation generation is repeatable; policy rollouts need not be.

### Scene families

These change the simulator at episode start:

| Family | Transformation at severity s | At s = 1 |
| --- | --- | --- |
| Viewpoint (`viewpoint`) | Agent camera shifts `0.10s` m and turns `10s` degrees toward the table; wrist unchanged | 10 cm, 10° |
| Lighting (`lighting`) | Every light × `(1 − 0.9s)` | ×0.10 |

### Rewordings

Nemotron 3 Super generates alternate instructions. The original gets two
control attempts; each rewording gets one screening attempt. A failed
screening attempt can trigger confirmation and, if it meets the gate and
passes the meaning check, word-edit reduction. Without a failing wording,
there is no reduction or minimum to claim.

The meaning check preserves object/target words. It can reject synonyms and
miss a changed spatial relation. Generated instructions need human review;
this is not proof that two instructions mean the same thing.

## 6. Reading a report

Read verdict, task/checkpoint, videos and summary first. **Why it's
trustworthy** connects measured counts to the report. **Full evidence** keeps
candidate histories and family tables; removing the global evidence page has
not removed these records. A selected video illustrates an attempt, not its
repeatability; the counts establish the latter within the chosen gate.

| Layout field | Meaning |
| --- | --- |
| `start`, `reference`, `hybrid` | Failing layout, passing benchmark layout, or reference plus selected changes. |
| `entity`, position cm, rotation deg, joints, score | Available differences and reference-distance score. |
| `#`, `phase`, `role`, `selection` | Candidate row, algorithm stage, purpose, applied shifts/shares. Citation `c37` means row 37. |
| `outcomes`, `decision`, `gate met`, `skipped`, `late` | Attempts, gate decision and early-decision accounting. |
| `necessary`, `sufficient` | Removing the entity stopped reproduction / the entity reproduced alone. Local rerun findings. |
| `necessary_not_sufficient`, `sufficient_not_necessary` | Needed but insufficient alone / sufficient alone but not in a valid final set. |
| `confirmed`, `not_in_final`, `inconclusive` | Needed and sufficient with one entity left / excluded / unsettled. |
| Effort | Candidates, attempts, Job time and estimated compute cost. |

| Disturbance field | Meaning |
| --- | --- |
| Smallest reproducibly failing severity | Smallest verified failing level found, not a universal threshold. |
| Physical value | Family formula expressed in units, such as blur sigma in pixels. |
| Last non-reproducing level | Highest tested level below the threshold that missed the gate; not proof of safety. |
| Levels in the order tried | Per-family table: `s`, failures/attempts, result, and order/phase (`tried as`). |
| Agent/wrist mean or std ratio | Perturbed brightness/contrast divided by unperturbed; 1 is unchanged. |
| Levels tried, Episodes, Stop reason | Search effort and why it ended. |

| Wording field | Meaning |
| --- | --- |
| `orig`, `p01`… | Original instruction and numbered rewordings. |
| `kind`, `instruction` | Original/paraphrase and exact text sent. |
| `outcomes`, `decision` | Attempts and control/passed/reproducing decision. |
| `word edits`, `meaning check` | Edit count and kept/dropped object/target-word check. |

Nemotron's guesses, reading and next steps are **interpretation, not evidence**.
Tavily retrieves sources; Nemotron 3 Ultra proposes steps from the measured
case and those sources. Schema/citation checks can reject an answer, with at
most one bounded repair. Validation is not a scientific endorsement. Invalid
new text is withheld; existing accepted text can remain after a failed refresh.

## 7. Verdicts, run statuses and stop reasons

| Verdict | Meaning |
| --- | --- |
| Failure repeats | Measured condition met the failure gate. |
| No failure found | No tested condition met it; a valid bounded result. |
| Stopped / Incomplete | Not fully answered; inspect reason and retained findings. |
| Run failed | Execution/infrastructure error, not a robot-policy failure. |

The run page distinguishes submission, GPU waiting, running, downloading,
stopping, completed, stopped, failed and interrupted. Icons/words accompany
colour: red for repeated failures, green for passes, amber for attention.

| Stop reason | Interpretation / recovery |
| --- | --- |
| `budget_exhausted` | Candidate budget ended; kept result is bounded. |
| `no_reproducible_failure` | Finished negative result. Nothing to reduce. |
| `nominal_controls_failed`, `control_not_passing` | Undisturbed scene/original wording did not pass; attribution invalid. |
| `check_incomplete`, `layout_skipped` | Untouched check undecided, or layout disabled despite failure. |
| `no_reference`, `reference_not_passing` | No suitable passing reference. |
| `failing_not_reproducible`, `no_faithful_failure` | Initial/reconstructed condition missed the gate. |
| `import_invalid`, `import_mismatch`, `original_mismatch` | Invalid state, wrong scene or instruction mismatch. |
| `spend_cap`, `max_hours` | Next Job refused / time reached. Raise limits before Resume; never lower. |
| `capacity_unavailable` | No GPU after bounded submissions. |
| `download_failed` | Paid Job finished; Resume retries downloading, not the GPU experiment. |
| `auth_expired`, `backend_error`, `process_ended` | Renew sign-in or inspect local error, then Resume to reattach. |
| `stopped_by_user` | Explicit Stop; inspect retained progress before Resume. |
| `paraphrase_failed`, `llm_required`, `original_unknown` | Wording generation failed/disabled, or original instruction unavailable. |

## 8. Replay verdicts

A replay tests a **known** failure; it does not search for another. Layout
cases rerun the saved trigger/reference; disturbance cases rerun failing
thresholds/controls; wording cases rerun failing wording/original control.
Supported cases expose **Regression test**. A negative screen without a
failing condition is not a reduced regression case.

| Recorded result | Original checkpoint | New compatible checkpoint |
| --- | --- | --- |
| Failure repeats | Still fails | Still fails |
| No longer repeats, control passes | Did not repeat (amber) | Fixed (green) |
| Control fails or result incomplete | Inconclusive | Inconclusive |

“Fixed” applies to the saved condition, not general robustness. A new
checkpoint needs its Hugging Face model ID and exact revision in a compatible
GR00T N1.7 LeRobot format; compatibility is not automatically established.
Older replay metadata can mark the checkpoint unrecorded. A partial multi-Job
replay retains per-Job results but has no overall verdict; `--expect` reports
inconclusive (exit 5).

## 9. Spending and claim boundaries

Before a Job, reserve its timeout (deadline plus ten minutes, rounded to a
minute) and a four-minute start allowance at the spec's hourly rate. Settle
afterward against measured container time. Estimates need billing reconciliation.

Only the **first Job** must fit to start. Later Jobs are refused if their
reservations exceed the remaining cap. Review counts the check plus the
larger branch, not both branches added together. Typical figures are
estimates; GPU waits, longer tasks and retries can change time and cost.

The cap covers **Nebius Jobs**, not Token Factory, Tavily, storage or all
account charges. Start confirms paid execution; reading cases and making dry
runs does not start GPU work. Research cannot make an invalid result valid.

Every claim is limited to the tested task, start, seed, checkpoint, family and
range. Reduction can stop early or miss smaller failures. Repeatability gates
and generated text are not causal proof, exhaustive coverage or formal
verification. Real robots/other simulators require new adapters; they are not
supported by this implementation.
