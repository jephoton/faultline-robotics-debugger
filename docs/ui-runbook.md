# Faultline UI runbook

> **This file is the mechanical reference** for using the Faultline interface:
> every scenario, exact inputs, and expected outputs, checked against the
> recorded cases on October 19, 2026, for the single **New diagnosis**
> (ADR 0035). It is not the video script and not the setup guide. What every
> term, column and severity means is on the **Reference** page.
>
> - **Setup, CLI and recovery commands:** [operator runbook](codex-handoff/RUNBOOK.md)
>   and [quickstart](setup/diagnose.md).
> - **How the system works:** [architecture](architecture.md).
> - **Public, read-only gallery:**
>   [faultline-robotics-debugger.vercel.app](https://faultline-robotics-debugger.vercel.app/)
>   (five cases, no controls).
>
> **Spending rule.** Demos 1–6 only read saved evidence or make dry runs; they
> create nothing in the cloud and cost nothing. Demos 7 and 8 press
> **Start**, which submits Nebius GPU Jobs on your account. Do them only with
> an agreed spend cap. The form's default caps are examples, not approval.

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
   **Scenario reductions**, **Stress tests**, **Language** and **Earlier**
   (each row with a green, red or amber bar), and at the bottom **Setup**,
   **Reference**, **Run your own** and **All evidence**.

3. Only before Demos 7 and 8, open **Setup**. **Expected:** "Everything
   needed is ready." with the checks Nebius sign-in, Token Factory key,
   backend settings in a local spec, Docker and (for related research) a
   Tavily key. Docker and Tavily are optional. The Nebius sign-in check can take up
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

**Point:** Faultline shrank a failing start to the smallest set of
differences that still fails, using reruns rather than the model's opinion,
and kept it as a replayable test.

1. In the sidebar, under **Scenario reductions**, open **import-l10-start14**
   (`FL-S-AFB5`).
2. **Expected header:** fault code `FL-S-AFB5`, verdict **Failure repeats**,
   kind **Scenario reduction**, **LIBERO-10, task 0**, and the instruction
   "put both the alphabet soup and the tomato sauce in the basket".
3. In **Videos**, press **Play all**. **Expected:** three clips,
   **Original failing start** (failed), **Minimal cause** (failed) and
   **Passing reference** (passed), playing in step. Set **Speed** to `0.5x` to
   compare the arm's approach. Clear **Keep in step** to move one clip on its
   own; ticking it again lines all three up at the earliest position.
4. In **Report**, read **Summary**. **Expected:**
   - Verdict: reproduces.
   - Failing start: imported file `6be6e4e2f06d` (from benchmark start 14).
   - Reference: benchmark start 28, the nearest start that passed.
   - Five kept shifts, each at 100% of the full difference: soup position
     2.9 cm, cream cheese 1.1 cm, milk 2.4 cm, orange juice 3.7 cm, and the
     arm's joints (6 joints, up to 2.6°).
   - Status: stopped at the candidate budget; entity-minimal (each kept entity
     is needed); sizes not fully shrunk.
5. Read on in the report: **Screen** (starts 24–33 screened; 28 is the nearest
   passing one), **Result** and **Minimal cause**, then **Differences between
   the failing start and the reference** (six entities, with the distance
   score), **Hypothesis** and **Hypothesis vs result**. Nemotron ranked the
   robot first; it is needed, but not enough on its own.
6. In **Candidates**, choose **Show all 26 rows**. Expected:
   - **0–1** gates: the failing start fails, start 28 passes 5 of 5.
   - **2–7** probe: each of the six alone passes.
   - **8–17** ddmin: no group reproduces until **18**, the five without the
     tomato sauce, which fails 4 of 4.
   - **19–22**: removing any one of the five makes it pass.
   - **23–25** shrink: the arm offset at 50% and 25% does not reproduce; at
     75% it does.

   The [Reference](reference.md) (sidebar **Reference**) explains every
   phase and column.
7. **Nemotron's reading** is collapsed: open it for the model's hypotheses,
   labelled as interpretation, not evidence. **Replays** says what a replay is
   for. **Run details** (collapsed): 3 cloud Jobs, US$1.80 of a US$2.80 cap,
   1 h 14 min.

**Talking point:** "The arm and five objects differ between a failing and a
passing start. Reruns, not the model, show that five are needed together:
each alone passes, and removing one from the five makes the failure go away.
That is the minimal trigger, and the case replays it on any future
checkpoint."

> **Limits:** a local minimum for one task, one start pair and one
> checkpoint. Row 25 proves the arm offset at 75% still fails, but the
> recorded case keeps 100%: a defect fixed on October 18 discarded it, and
> new runs record it. The bundled `soup-start14-demo` (in `demo/root`) is the
> October 13 recording of the same failure: the same five entities, with the
> soup and the arm shrunk to 87.5%.

---

## Demo 2 — A stress test with a clean negative result

**Point:** "No failure found" within a tested range is a result, not an error.

1. Under **Stress tests**, open **catalog-spatial** (`FL-A-F526`).
2. **Expected:** verdict **No failure found**, LIBERO-Spatial task 0.
3. In **Report**, read **Summary**. **Expected:** unperturbed control 0 of 5
   attempts failed; JPEG compression, Colour cast, Motion blur and Dead
   pixels each "no failure up to s = 1.00".
4. In **Videos**, press **Play all**. **Expected:** five clips:
   - **Unperturbed control**;
   - **Colour cast**, **Dead pixels**, **JPEG compression** and **Motion
     blur**, each at s = 1.00.

   Each clip is marked passed, in green. These show what the policy saw at
   full strength, and that it still succeeded.
5. In the report's second table (**Levels in the order tried**). **Expected:**
   every family was tried at s = 0.2, 0.4, 0.6, 0.8 and 1 with 5 attempts. All
   levels are 0/5 except motion blur at s = 1: 1/5.
6. **Run details:** 1 Job, US$0.82.

What each family and severity level means physically (for example dead
pixels at s = 1.00 is 20% of the pixels) is in
the [Reference](reference.md), section 5. These four are the image
catalog families; the New diagnosis form starts with a different four (Blur,
Noise, Darken, Contrast) checked.

**Talking point:** "The policy kept working through JPEG down to quality 5, a
strong colour cast and 20% dead pixels. One motion-blur failure at full
strength is not a repeatable failure. The gate needs 4 of 5."

Also try **scene-object** (`FL-A-A70E`):
- camera viewpoint 1/5 at s = 0.8 and 1.0, lighting 0/5 at every level;
- videos of the control, the moved camera and the dimmed lights at
  s = 1.00.

---

## Demo 3 — When the control fails, nothing can be judged

**Point:** a stress test only means something if the undisturbed start passes.

1. Under **Stress tests**, open **scene-goal** (`FL-A-08D3`). Its sidebar row
   has an amber bar.
2. **Expected:** the readout verdict **Stopped** in amber. The report's
   **Summary**:
   - unperturbed control 3 of 5 attempts failed, so no disturbance can be
     judged;
   - stopped early (`nominal_controls_failed`);
   - camera viewpoint and scene lighting "not tested (the run stopped before
     this family was searched)".

   **Videos** holds one clip, the **Unperturbed control**, marked failed in
   red. With the single diagnosis, this start would be reported as
   **flaky**.

**Talking point:** "Faultline refused to blame the camera or the lights,
because the policy already failed this start without them. LIBERO-Goal task 0
start 0 is a weak start: a candidate for Demo 1's mode instead."

---

## Demo 4 — Rewording the instruction (local panel)

**Point:** the same task in other words, screened against the original.

1. Under **Language**, open **ui-paraphrase-spatial** (`FL-L-C72C`).
2. **Expected Summary:** control: the original wording passed (S S);
   rewordings: 4 screened, 4 kept by the meaning check, 0 dropped; failures:
   none.
3. **Screen** lists each wording with its outcomes, decision, number of word
   edits and meaning check, for example "Take the black bowl located between
   the plate and the ramekin and put it on the plate". **Run details:** 1 Job,
   US$0.31.

**Talking point:** "Nemotron 3 Super writes everyday rewordings. A meaning
check drops any that lose an object or target of the task, so a failure
cannot come from a different instruction. GR00T passed all 24 rewordings
tried across three suites."

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

## Demo 6 — Plan a diagnosis without spending (dry run)

**Point:** one New diagnosis. The review shows what will happen in each case
and what it costs, before anything is created.

1. In the sidebar, choose **New diagnosis**. **Expected:** the promise
   "Faultline runs your start untouched. If it fails, it finds the smallest
   change that triggers it. If it passes, it looks for the smallest
   disturbance or rewording that breaks it."
2. Under **What do you want to check?**, choose one of:
   - **A benchmark start** (the usual): it is checked untouched, then
     diagnosed or probed.
   - **Search a range of starts**: looks for a start that fails, layout only.
   - **A start file of my own**: your JSON start state, layout only. To try
     one, use `demo/root/diagnoses/b3c44e86…/minimal-candidate.json` with
     LIBERO-10 task 0.

   Then choose **Next: settings**.
3. **Settings**, for a benchmark start:
   - Suite, **Task** (its instruction is shown) and **Start**, by default
     LIBERO-Object, task 0, start 0.
   - **If the start passes untouched, also probe**, on by default, with
     **Disturbance families**. **Blur**, **Noise**, **Darken** and
     **Contrast** are ticked, "where the policy has failed before"; the other
     six are one tick away.
   - **Rewordings to ask for** (0 skips them).
   - **Spend cap (US$)** (default 2.5) and **Hour limit** (default 1.5).
   - The Nemotron option.
   - **Find related research**, ticked only when a Tavily key is found.
     Without one, Review shows a note; it never blocks Start.

   Choose **Review**.
4. **Expected on Review**, under **Dry run**, three blocks, each with its Jobs,
   **Worst case** and **Typical** (an estimate):
   - **First: check the start untouched**: the screen Job, typically about
     US$0.43 and 16 minutes.
   - **If it fails: find the smallest layout change**: the reduction (and
     continuations, used only if needed), typically about US$0.68 and
     25 minutes.
   - **If it passes: probe**: the probe Jobs. LIBERO-Object fits the four
     default families in one Job (typically about US$0.82 and 29 minutes);
     LIBERO-10's longer episodes need two (about US$1.16 and 42 minutes).

   Then **Total worst case** (the check plus the larger branch), **Typical
   total if it fails** and **Typical total if it passes**. **This machine**
   shows the setup checks.
5. **Do not press Start diagnosis** (it is on this page). With the default
   US$2.50 cap, Review says "The first Job fits, but not all of them" and
   names `reduce` and `probe-image-1`. Each Job is charged what it measured,
   so those are refused only if the check costs its worst case (US$1.22). A
   typical check (about US$0.43) leaves room for either branch's first Job. A
   run stopped at the cap can be resumed after raising it.

**Edit YAML** shows the `mode: diagnose` spec the form writes. Once you edit
it, it becomes the source of truth until **Discard YAML edits and use the
fields**. The wizard's own **Back** returns to the previous step; the
top-left **Back** returns home and drops the form.

---

## Demo 7 — Replay a case (paid: one Job per replay)

**Point:** every case is a regression test. Rerun it after changing the
policy, and see whether its failing condition still fails.

1. Open a case with a failure. `FL-S-AFB5` is a layout case. A disturbance or
   rewording case that found a failure works the same way.
2. Scroll to **Replays**. The purpose line says what a replay reruns:
   - a layout case: the minimal scene and its passing reference;
   - a disturbance case: each failing family at its threshold, with the
     control;
   - a rewording case: the failing wording against the original.

   Five attempts each.
3. Choose **What do you expect?** (**No expectation**, **Still reproduces**,
   or **Fixed (after a change meant to cure it)**). Leave **A different
   checkpoint (optional)** empty unless testing another policy.
4. The replay's **Spend cap (US$)** and hours default to its own plan (a
   layout replay's worst case is about US$1.08; a disturbance replay plans
   one Job per probe group). Choose **Dry run the replay**. **Stop here
   unless the spend is agreed.**
5. With agreement, choose **Start replay** once.

**Expected if run:** a verdict under **Replays**: still reproduces / still
fails, or no longer. A replay whose control fails, or whose Job does not
finish, is inconclusive, and so is a replay that stops between probe groups
(its partial result is kept). The October 15 replay of the demo case still
reproduced, measured at US$0.41.

---

## Demo 8 — Start, watch, stop and resume a run (paid)

**Point:** the whole loop from the browser, with a safe stop.

Recorded example (October 17, cap US$1.30 agreed). Only one paid run can be
active at a time; a start is refused while another run's process is alive.

1. **New diagnosis** → **A benchmark start** → **Next: settings**. For a
   short run, set a start you expect to pass. Untick the families, set
   **Rewordings to ask for** to `4`, and choose a cap and hour limit you
   agree to. Choose **Review**. The October 17 example below used the older
   rewordings form with the same settings: LIBERO-Spatial, task 0, start 0,
   cap US$1.30.
2. Review shows screen US$1.19 and reduce US$1.51 (total US$2.71) with "The
   first Job fits, but not all of them". Choose **Start diagnosis**.
3. **Expected:** the run page opens. Once the check is read, it shows the
   **route**:
   - "The start failed untouched: finding the smallest layout change" (red);
   - "The start passed: probing" (green);
   - "The start is flaky untouched" (amber): it failed some attempts but not
     4 of 5, so nothing more runs and no case is made; or a probe's own
     control failed, so the probes still to come are skipped;
   - "Passes untouched".

   If the check cannot decide (an unfinished or invalid start), the run stops
   with `check_incomplete`; a resume reruns the check.

   The readout's status word follows the
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

## Demo 9 — Bring your own failing start (paid)

**Point:** a failure from a layout that is not a benchmark start.

Follow Demo 6 with **A start file of my own**, then Demo 8 from Start. The
file must first fail 4 of 5, or the run stops ("The imported start did not
fail reliably"). A file from another scene stops with "The imported start
did not match the task's scene." The case names the file by a fingerprint,
not a start number. The October 16 import of start 14 reproduced the same
five entities as Demo 1 (US$1.80).

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

Colours: green for a pass, red for a failure, amber for anything that needs
attention, always with an icon and a word. The run page also shows the
**route**: layout, probes, flaky or passes.

- **Videos:** every case kind shows clips: layout (original, minimal,
  reference), disturbances (control, and each family at its threshold or top
  severity), rewordings (original and reworded). A case recorded without them
  says so.
- **Replay:** any case with a failing condition and saved inputs can be
  replayed. A case without saved inputs says "This case cannot be replayed:
  its replay inputs were not saved."
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
2. The report's Summary: five shifts needed together; **Show all 26 rows**
   in Candidates: each alone passes, and removing any one of the five passes.
3. Nemotron's robot-first guess versus "needed but not enough on its own".
4. `FL-A-F526`: the control and four disturbances at full strength, all
   passing in green; one isolated 1/5. Close with: evidence is specific to
   these starts, this policy and these attempts.

For the control panel, add: **New diagnosis** → **A benchmark start** →
**Next: settings** → **Review**. Show the check, the two branches with their
typical cost and time, and stop before Start.
