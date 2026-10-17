# Faultline UI runbook

> **This file is the mechanical reference** for using the Faultline interface:
> every scenario, exact inputs, and expected outputs, checked against the
> recorded cases on October 18, 2026. It is not the video script and not the
> setup guide.
>
> - **Setup, CLI and recovery commands:** [operator runbook](codex-handoff/RUNBOOK.md)
>   and [quickstart](setup/diagnose.md).
> - **How the system works:** [architecture](architecture.md).
> - **Public, read-only gallery:**
>   [faultline-robotics-debugger.vercel.app](https://faultline-robotics-debugger.vercel.app/)
>   (five cases, no controls).
>
> **Spending rule.** Demos 1–6 only read saved evidence or make dry runs; they
> create nothing in the cloud and cost nothing. Demos 7–9 press **Start**,
> which submits Nebius GPU Jobs on your account. Do them only with an
> agreed spend cap. The form's default caps are examples, not approval.

## Setup (before the demo)

1. **Start the control panel** from the repository root:

   ```bash
   faultline ui --open
   ```

   From a source checkout without installing:
   `PYTHONPATH=src python -B -m robot_debug.cli ui --open`. To show only the
   bundled demo case, add `--artifacts demo/root`.

2. Open <http://127.0.0.1:8765>. **Expected:** the sidebar shows
   **New diagnosis**, **Running** ("Nothing running."), the case groups
   **Scenario reductions**, **Stress tests**, **Language** and **Earlier**,
   and at the bottom **Setup**, **Run your own** and **All evidence**.

3. Only before Demos 7–9, open **Setup**. **Expected:** "Everything needed is
   ready." with four checks: Nebius sign-in, Token Factory key, backend
   settings in a local spec, and Docker. The Nebius sign-in check can take up
   to 20 seconds. If it says the sign-in needs attention, run
   `nebius iam whoami` in a terminal and sign in.

The recorded cases (the public gallery holds the first five):

| Fault code | Name | Kind | Verdict |
| --- | --- | --- | --- |
| `FL-S-AFB5` | import-l10-start14 | Scenario reduction, LIBERO-10 task 0 | Failure repeats |
| `FL-A-F526` | catalog-spatial | Stress test, LIBERO-Spatial task 0 | No failure found |
| `FL-A-A70E` | scene-object | Stress test, LIBERO-Object task 0 | No failure found |
| `FL-A-08D3` | scene-goal | Stress test, LIBERO-Goal task 0 | Stopped (control failed) |
| `FL-M-52D8` | September occlusion case | Occlusion, LIBERO-Object task 0 | Failure repeats |
| `FL-L-C72C` | ui-paraphrase-spatial | Language, LIBERO-Spatial task 0 | No failure found (local only) |
| `FL-L-CEB3`, `FL-L-6CE6` | paraphrase-l10, paraphrase-task0 | Language, LIBERO-10 and LIBERO-Object task 0 | No failure found (local only) |

---

## Demo 1 — A failure that needs five shifts together

**Point:** Faultline reduced a failing start to the smallest set of
differences that still fails, using reruns rather than the model's opinion.

1. In the sidebar, under **Scenario reductions**, open **import-l10-start14**
   (`FL-S-AFB5`).
2. **Expected header:** fault code `FL-S-AFB5`, verdict **Failure repeats**,
   kind **Scenario reduction**, **LIBERO-10, task 0**, and the instruction
   "put both the alphabet soup and the tomato sauce in the basket". An amber
   **Stopped early** note says the candidate budget was reached.
3. In **Videos**, press **Play all**. **Expected:** three clips,
   **Original failing start** (failed), **Minimal cause** (failed) and
   **Passing reference** (passed), playing in step. Set **Speed** to `0.5x` to
   compare the arm's approach. Clear **Keep in step** to control each clip on
   its own.
4. In **What changed between the passing and failing start**. **Expected:**
   failing start "your imported file 6be6e4e2f06d", reference "benchmark start
   28 (nearest passing start)", **Differences found** 6 (the arm and five
   objects), and five rows, all at **Share** 100%:

   | Entity | Part | Size |
   | --- | --- | --- |
   | alphabet_soup_1 | position | 2.9 cm |
   | cream_cheese_1 | position | 1.1 cm |
   | milk_1 | position | 2.4 cm |
   | orange_juice_1 | position | 3.7 cm |
   | robot | joints | 6 joints, up to 2.6° |

5. In **Nemotron's guess and what was measured**. **Expected:** the guess
   ranks `robot` first, then `alphabet_soup_1`, `tomato_sauce_1`. The
   measurement says "The model's top suspect was needed but not enough on its
   own." `tomato_sauce_1`, ranked third, is not in the final set.
6. Open **Reruns** → **Show all 8 reruns**. **Expected:** the failing start
   fails 4 of 4 and the reference passes 5 of 5; the robot, the soup and the
   tomato sauce shifted alone each pass; the five shifts together fail 4 of 4;
   leaving out the robot, or the soup, makes the five pass again.
7. **How it was made.** **Expected:** 3 cloud Jobs, US$1.80 of a US$2.80 cap,
   1 h 14 min of a 3-hour limit.

**Talking point:** "The arm and five objects differ between a failing and a
passing start.
Reruns, not the model, show that five are needed together: the ones tried
alone pass, and removing one from the five makes the failure go away.
Nemotron guessed the robot; the measurement says it matters but does not
cause the failure by itself."

> **Limits:** this is a local minimum for one task, one start pair and one
> checkpoint. The entity set is minimal; the sizes were not shrunk (all 100%)
> before the budget ran out. The bundled `soup-start14-demo` (in
> `demo/root`) is the October 13 recording of the same failure: the same five
> entities, with some sizes shrunk (each still needed at least 87.5% of its
> shift).

---

## Demo 2 — A stress test with a clean negative result

**Point:** "No failure found" within a tested range is a result, not an error.

1. Under **Stress tests**, open **catalog-spatial** (`FL-A-F526`).
2. **Expected:** verdict **No failure found**, LIBERO-Spatial task 0,
   **benchmark start 0**, **Unperturbed control** "0 of 5 attempts failed".
3. In **Severity by family**. **Expected:** four ladders (JPEG compression,
   Colour cast, Motion blur, Dead pixels), each tried at s = 0.20, 0.40, 0.60,
   0.80 and 1.00 with 5 attempts. Every level is 0/5 except **Motion blur at
   s = 1.00: 1/5**. Each family reads "No failure up to severity 1.00".
4. **How it was made:** 1 Job, US$0.82.

**Talking point:** "The policy kept working through JPEG down to quality 5, a
strong colour cast and 20% dead pixels. One motion-blur failure at full
strength is not a repeatable failure. The gate needs 4 of 5."

These four are the image catalog families; the New diagnosis form starts with
a different four (Blur, Noise, Darken, Contrast) checked.

Also try **scene-object** (`FL-A-A70E`): camera viewpoint 1/5 at s = 0.80 and
1.00, lighting 0/5 at every level.

---

## Demo 3 — When the control fails, nothing can be judged

**Point:** a stress test only means something if the undisturbed start passes.

1. Under **Stress tests**, open **scene-goal** (`FL-A-08D3`). Its sidebar row
   has an amber bar.
2. **Expected:** verdict **Stopped**, with the explanation "The unperturbed
   policy did not pass reliably, so no disturbance can be judged."
   **Unperturbed control:** 3 of 5 attempts failed. **Camera viewpoint** and
   **Scene lighting** each read "Not tested: the run stopped before this
   family was searched".

**Talking point:** "Faultline refused to blame the camera or the lights,
because the policy already failed this start without them. LIBERO-Goal task 0
start 0 is a weak start, a candidate for Demo 1's mode instead."

---

## Demo 4 — Rewording the instruction (local panel)

**Point:** the same task in other words, screened against the original.

1. Under **Language**, open **ui-paraphrase-spatial** (`FL-L-C72C`).
2. **Expected:** in **Wordings tried**, the original "pick up the black bowl
   between the plate and the ramekin and place it on the plate" (control, 0 of
   2 failed), then four Nemotron rewordings, each **kept** by the meaning check
   and 0 of 1 failed. **Smallest word change that still fails:** "No wording
   failed reliably, so there was nothing to reduce."
3. **How it was made:** paraphrases written, rewordings screened (1 Job,
   US$0.31).

**Talking point:** "Nemotron 3 Super writes everyday rewordings. A meaning
check drops any that change the task, so a failure cannot come from a
different instruction. GR00T passed all 24 rewordings tried across three
suites."

---

## Demo 5 — The September occlusion case

**Point:** the earliest diagnosis: a grey block covering part of the camera,
shrunk to the smallest block that still causes the failure.

1. Under **Earlier**, open **September occlusion case** (`FL-M-52D8`).
2. **Expected:** verdict **Failure repeats**, LIBERO-Object task 0, the
   result "A block covering 14% of the agent camera view makes the policy
   fail."
3. **Occluded episodes:** 22 recorded episodes, each labelled with its stage
   and role (for example `nominal-control-attempt-01, nominal` or
   `delta-0125-bottom-…, reduced`). The nominal (unblocked) ones pass; the
   starting block (`parent`) and the reduced block (`reduced`) fail in every
   attempt; some trial trims (`other`) still fail and some pass. **Play all**
   plays every clip together; clear **Keep in step** and use a single clip's
   own controls to watch one.
4. **How the rectangle was reduced.** **Expected:** the block starts at 25%
   of the agent camera image and two trims keep the failure: the left edge
   (still fails, covering 18.8%) and then the bottom edge (still fails,
   covering 14.1%).
5. **Nemotron's reading** shows only the stored factual summary: no model
   interpretation was kept for this case. **Research context** lists public
   sources found with Tavily: context, not evidence.

---

## Demo 6 — Plan a run without spending (dry runs)

**Point:** every new run starts with a dry run that shows the Jobs and their
worst-case cost; nothing is created until **Start**.

1. In the sidebar, choose **New diagnosis**, pick a card (see the table
   below), choose **Next: settings**, then **Review**.
2. **Expected on Review:** under **Dry run**, "Planned Jobs. Nothing has been
   created yet.", a table of Jobs with deadline and worst case, **Total worst
   case**, the spend cap and the hour limit; under **This machine**, the
   environment checks. **Do not press Start diagnosis** (it is on this page).
   Use **Back to settings** to change fields. The wizard's own **Back** on the
   settings step returns to the card choice; the top-left **Back** returns home
   and drops the form.

| Goal | Card → option | Fields that matter | Planned Jobs at the form's defaults (worst case) |
| --- | --- | --- | --- |
| Explain a start you know fails | **Find why a start fails** → **A benchmark start I know fails** | Suite, Task, Start | screen US$1.22 and a reduction US$1.86: total US$3.09 against a US$3.50 cap. Continuations are listed but run only if the first reduction stops at its budget. |
| Find a failing start first | **Find why a start fails** → **Search a range of starts** | Starts to search (for example `10-49`), Failures to confirm (of 5) | screen US$1.37 and a reduction US$1.86: total US$3.23 against US$4.00 |
| Diagnose your own failing start | **Find why a start fails** → **A start file of my own** | Suite, Task, **Start file** (a JSON start state, not a video; under 1.5 MB) | as for a known start; the dry run also checks the file (Demo 9 names a file to try) |
| Find the smallest disturbance that breaks a passing start | **Stress-test a passing start** | Start, **Disturbance families** (image: both cameras; scene: at reset) | one audit Job, US$1.34 for the default four image families |
| Test rewordings | **Test rewordings** | Start, **Rewordings to ask for** (1–12); needs the Token Factory key | screen US$1.31, reduce US$1.51 (10 rewordings) |

Exact figures change with the fields: more families, rewordings or attempts
lengthen the deadline. Reductions and the rewording reduction run only if a
failure is found.

**Cap rule shown on Review:**
- If the total is above the cap but the first Job fits, Review says "The
  first Job fits, but not all of them" and Start is allowed. A later Job that
  does not fit stops the run, which can be resumed after raising the cap.
- If even the first Job is over the cap, Review says so and Start is refused.
- The cap covers Nebius Job reservations only. It does not cover Token
  Factory calls or storage.

**Edit YAML** shows the spec the form writes. Once you edit it, it becomes the
source of truth until **Discard YAML edits and use the fields**. Switching card
resets the form's defaults, including the cap.

---

## Demo 7 — Replay a saved scenario (paid: one Job)

**Point:** a saved case is a regression test: rerun it after changing the
policy and see whether the failure still reproduces.

1. Open `FL-S-AFB5` and scroll to **Replays** ("This case has not been
   replayed yet").
2. Choose **What do you expect?** (**No expectation**, **Still reproduces**,
   or **Fixed (after a change meant to cure it)**). Leave **A different
   checkpoint (optional)** empty unless testing another policy; then fill in
   both **Checkpoint id** and **Revision**.
3. Check **Spend cap (US$)** is at least 1.20 (the default). The replay Job's
   worst case is about US$1.08, and a lower cap refuses Start. Choose **Dry run
   the replay**. **Expected:** one Job,
   `replay`, about 23 minutes deadline. **Stop here unless the spend is
   agreed.**
4. With agreement, choose **Start replay** once.

**Expected if run:** the minimal scene and the passing reference each run 5
times. The verdict is "still reproduces" or "no longer reproduces", listed
under **Replays**. The October 15 replay of the demo case still reproduced,
measured at US$0.41.

---

## Demo 8 — Start, watch, stop and resume a run (paid)

**Point:** the whole loop from the browser, with a safe stop.

Recorded example (October 17, cap US$1.30 agreed). Only one paid run can be
active at a time; a start is refused while another run's process is alive.

1. **New diagnosis** → **Test rewordings** → **Next: settings**. Set Suite
   LIBERO-Spatial, Task 0, Start 0, **Rewordings to ask for** `4`, and change
   the defaults to **Spend cap (US$)** `1.3` and **Hour limit** `1.5`. Choose
   **Review**.
2. Review shows screen US$1.19 and reduce US$1.51 (total US$2.71) with "The
   first Job fits, but not all of them". Choose **Start diagnosis**.
3. **Expected:** the run page opens: the readout's status word follows the
   Job (**Submitting a Job**, **Waiting for a GPU** in amber, **Running**,
   **Downloading results**), with the current step and **Spent** of the
   cap. **Steps** lists "Write the paraphrases", "Screen the rewordings",
   "Reduce the wording" and the rest. **Cloud Job** shows the Job's phase: submitting, waiting for a GPU (with
   resubmissions), running, downloading. **Spend and time** shows spent
   (solid) and reserved worst case (hatched). The run appears under
   **Running** in the sidebar.
4. Leaving the page or closing the tab does not stop the run. The run page
   refreshes every 5 seconds while the run is active (and pauses while the tab
   is hidden); the sidebar's **Running** list every 10 seconds.
5. To stop: **Stop**, then **Stop the run** (or **Keep running**). The
   status shows **Stopping** while the current Job is cancelled and charged
   for the time it ran (nothing if it never got a GPU). **Resume** continues the same run from its last finished
   step. It re-attaches to a Job that is still running and never pays for that
   Job twice, but work that **Stop** cancelled runs again on a new Job and
   costs again.
6. **Expected at the end (recorded):** status **Completed**, the later steps
   **skipped**, US$0.31 spent. When you watch a run finish, the page opens the
   case after a 3-second countdown; **Stay here** cancels it. **Open the case**
   leads to `FL-L-C72C` (Demo 4).

If **Start** reports a timeout or a server error, do not press Start again.
The page shows its own warning ("The run may have started…") and hides
Start. Check **Running** in the sidebar for a minute; the server waits up to
30 seconds for a new run to report in.

---

## Demo 9 — Diagnose your own failing start (paid)

**Point:** bring a failing start state; Faultline confirms it, finds the
nearest passing benchmark start and reduces the differences.

1. **New diagnosis** → **Find why a start fails** → **A start file of my
   own** → **Next: settings**. Choose the matching **Suite** and **Task**, then
   the JSON file under **Start file**. The page checks the JSON's syntax and
   size; Review checks that the state fits the task's scene.
2. **A file to try:** the demo case's minimal failing scene,
   `demo/root/diagnoses/b3c44e86…/minimal-candidate.json`, with Suite
   LIBERO-10 and Task 0. Its dry run is accepted: screen US$1.22, then a
   reduction. Any saved scenario case's `minimal-candidate.json` is in the
   same format.
3. Review, then Start only with an agreed cap.

**Expected if run:** the file must first fail 4 of 5 attempts, or the run
stops ("The imported start did not fail reliably"). A file from another scene
stops with "The imported start did not match the task's scene." The case
names the file by a fingerprint, not a start number. The October 16 import of
start 14 reproduced the same five entities as Demo 1 (US$1.80).

---

## Read the result

A **case verdict** (case pages and the sidebar):

| Verdict | Meaning |
| --- | --- |
| **Failure repeats** | The failure met the 4-of-5 gate. Inspect the reruns to see exactly what repeated. |
| **No failure found** | Nothing met the gate in the tested starts, families or wordings. Bounded evidence, not proof of robustness. |
| **Stopped** (amber) | The diagnosis ended before its question was answered; the text says why (control failed, budget, spend cap, hour limit, capacity, sign-in). |
| **Incomplete** | The run did not finish its work; read what was done before drawing anything from it. |
| **Run failed** (amber) | A local or provider error. Infrastructure errors are not policy failures. |

A **run status** (the run page's readout):

| Status | Meaning |
| --- | --- |
| **Submitting a Job**, **Waiting for a GPU**, **Running**, **Downloading results** | The run is active; Stop is available. |
| **Stopping** | Stop was confirmed; the current Job is being cancelled and settled. |
| **Completed** | Finished, including "No failure found"; **Open the case** shows the result. |
| **Stopped**, **Failed** | Ended early; the text says why. **Resume** if offered. |
| **Interrupted** | The run's process ended unexpectedly. **Resume** re-attaches to any Job it left running. |

- **No videos:** audit and paraphrase cases do not save videos. The tables
  still hold the evidence.
- **Replay:** only scenario cases have a **Replays** section. A scenario case
  without saved inputs says "This case cannot be replayed: its replay inputs
  were not saved."
- **"Stopped early" on a reproducing case:** the entity reduction finished
  but the size shrinking did not. Sizes at 100% are not minimal.

## Recovery

| Symptom | What to do |
| --- | --- |
| Setup: Nebius sign-in needs attention | Run `nebius iam whoami`, sign in, **Check again**. Then **Resume** any stopped run. |
| Run fails at once: "a Nebius quota is used up" (buckets) | Delete emptied `faultline-*` buckets (Nebius refuses non-empty ones), then **Resume**. |
| Cloud Job: waiting for a GPU | Normal. It resubmits up to six times; nothing is billed while waiting. |
| Status **Interrupted** | **Resume**. |
| Progress looks stale | The run page refreshes every 5 seconds while the tab is visible. Check **Log** and **Steps** before acting. |
| Setup: "1 item needs attention" for Docker only | Safe to ignore: Docker is needed to build the image, not to run. |
| Start timed out | Check **Running** before anything else. |

## Reset between runs

Viewing needs no reset. Each run keeps its own folder (`artifacts/runs/`) and
the spec the panel wrote (`artifacts/specs-ui/`). Restarting the panel does
not stop a run: runs start outside the panel's process. The run log says so
when Windows does not allow that.

## A 90-second route for the video

Use recorded cases only; start nothing.

1. Public gallery → `FL-S-AFB5` → **Play all** at `0.5x`: failing, minimal,
   passing.
2. The five-row table: five shifts needed together; **Show all 8 reruns**:
   each alone passes.
3. Nemotron's robot-first guess versus "needed but not enough on its own".
4. `FL-A-F526`: four robust ladders, one isolated 1/5. Close with: evidence is
   specific to these starts, this policy and these attempts.

For the control panel, add: **New diagnosis** → **Test rewordings** →
**Next: settings** → **Review**. Show the dry-run table and stop before Start.
