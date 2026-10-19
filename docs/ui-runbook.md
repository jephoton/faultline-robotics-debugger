# Faultline UI runbook

> **This file is the mechanical reference** for using the Faultline control
> panel. Each demo gives exact inputs and expected outputs, checked against
> the recorded showcase cases on October 19, 2026, for the single **New
> diagnosis** (ADR 0035). It is not the video script and not the setup guide.
> What every term, column and severity means is on the **Reference** page.
>
> - **Setup, CLI and recovery commands:** [operator runbook](codex-handoff/RUNBOOK.md)
>   and [quickstart](setup/diagnose.md).
> - **How the system works:** [architecture](architecture.md).
> - **Public, read-only gallery:**
>   [faultline-robotics-debugger.vercel.app](https://faultline-robotics-debugger.vercel.app/)
>   (no controls). It is due to be refreshed with the showcase cases below.
>
> **Spending rule.** Demos 1–4 only read saved evidence or make dry runs; they
> create nothing in the cloud and cost nothing. Demos 5 and 6 press **Start**
> or **Run the test**, which submits Nebius GPU Jobs on your account. Do them
> only with an agreed spend cap. The form's default caps are examples, not
> approval.

## Setup (before the demo)

1. **Start the control panel** from the repository root:

   ```bash
   faultline ui --open
   ```

   From a source checkout without installing:
   `PYTHONPATH=src python -B -m robot_debug.cli ui --open`. To show only the
   bundled demo case, add `--artifacts demo/root`.

2. Open <http://127.0.0.1:8765>. **Expected:**
   - at the top of the sidebar, **New diagnosis** and **Running** ("Nothing
     running.");
   - one **Cases** list, each row with its name, fault code and outcome;
   - at the bottom, **Setup**, **Reference** and **Run your own**.

   Cases share one diagnosis workflow; navigation does not split them by
   implementation type. Each case still explains the conditions actually
   tested. There is no global All evidence page: inspect a case's own evidence
   instead. The original records remain on disk.

   **Reference** is the one page that explains everything the panel shows.
3. Only before Demos 5 and 6, open **Setup**. **Expected:** "Everything
   needed is ready." The checks are:
   - Nebius sign-in;
   - Token Factory key;
   - backend settings in a local spec;
   - Docker (optional);
   - a Tavily key for related research (optional).

   The Nebius sign-in check can take up to 20 seconds. If it says the sign-in
   needs attention, run `nebius iam whoami` in a terminal and sign in.

### The showcase cases

| Fault code | Name | Route | Verdict |
| --- | --- | --- | --- |
| `FL-S-8E0D` | l10-start14 | Layout: a failing start shrunk to its trigger | Failure repeats (four shifts) |
| `FL-A-D582` | object-start0 | Probes: a disturbance that breaks a passing start | Failure repeats (blur from s = 0.4625) |
| `FL-A-F526` | catalog-spatial | Probes: nothing broke it | No failure found |
| `FL-L-C72C` | ui-paraphrase-spatial | Instruction rewordings, restored locally from the archive | No failure found |


---

## Demo 1 — Layout route: a failing start shrunk to its trigger

**Point:** a start that fails untouched is shrunk to the smallest set of
layout differences that still fails. Reruns decide this, not the model's
opinion, and the result is kept as a regression test.

1. Under **Cases**, open **l10-start14** (`FL-S-8E0D`).
2. **Expected header:** the fault code, verdict **Failure repeats**, kind
   **Scenario reduction**, **LIBERO-10, task 0**, and the instruction "put
   both the alphabet soup and the tomato sauce in the basket".
3. In **Videos**, press **Play all**. **Expected:** three clips, playing in
   step:
   - **Original failing start** (failed, red);
   - **Minimal cause** (failed, red);
   - **Passing reference** (passed, green).

   Set **Speed** to `0.5x` to compare the arm's approach. Clear **Keep in
   step** to move one clip on its own; ticking it again lines all three up at
   the earliest position.
4. In **Report**, read **Summary**. **Expected:**
   - Verdict: reproduces.
   - Failing start: benchmark start 14. Reference: benchmark start 4, the
     nearest start that passed.
   - Four kept shifts:
     - basket position 2.1 cm (93.8% of the full difference);
     - milk 2.2 cm (87.5%);
     - orange juice 0.8 cm (100%);
     - the arm's joints (5 joints, up to 2.1°, 93.8%).
   - Status: stopped at the candidate budget, entity-minimal (each kept
     shift is needed), sizes not fully shrunk.
5. Read on: **Screen**, **Result**, **Minimal cause**, **Differences between
   the failing start and the reference**, then **Hypothesis** and
   **Hypothesis vs result**. Nemotron 3 Ultra ranked the arm first and the
   soup second. The reruns show the arm is needed but not enough on its own,
   and the soup is not needed at all.
6. In **Candidates**, choose **Show all 38 rows**. The phases:
   - **gate** (0–1): the failing start fails 4 of 5; start 4 passes 5 of 5;
   - **probe** (2–6): each of the five differences alone passes;
   - **ddmin** (7–18): only the four without the soup fail (row 15, 4 of 4),
     and removing any one of the four makes it pass;
   - **shrink** (19–37): each kept shift is halved towards the reference
     while it still fails.

   One honest limit: the basket at 81.25% also failed (row 31), but the
   search kept 93.75% (see the Reference's worked example).
7. **Nemotron's reading** (collapsed) holds the model's hypotheses, labelled
   as interpretation, not evidence. **Regression test** is Demo 6. **Run
   details** (collapsed) gives the Jobs, spend and time.

**Talking point:** "Five things differ between a failing and a passing
start. Reruns, not the model, show that four are needed together: each alone
passes, and removing any one makes the failure go away. Nemotron guessed the
soup mattered; it does not. That is the minimal trigger, and the case reruns
it on any future checkpoint."

**Variant: a failure from your own scene.** On the New diagnosis page, choose
**A failure from my own scene (file)**. Upload a
start-state JSON file, for example any case's `minimal-candidate.json`, with
its suite and task. The file must fail 4 of 5 first, or the run stops ("The
imported start did not fail reliably"). A file from another scene stops with
"The imported start did not match the task's scene." The case names the file
by a fingerprint, not a start number.

---

## Demo 2 — Probe route: a disturbance that breaks a passing start

**Point:** a start that passes untouched is probed. Faultline finds the
smallest severity of each disturbance that reliably breaks it.

1. Under **Cases**, open **object-start0 - stress test**
   (`FL-A-D582`).
2. **Expected header:** verdict **Failure repeats** (red), kind **Stress
   test**, **LIBERO-Object, task 0**. The sentence: "The policy fails
   reliably under 2 of 4 disturbance families; the lowest threshold is
   gaussian blur at severity 0.4625."
3. In **Videos**, press **Play all**. **Expected:** five clips:
   - **Unperturbed control**: passed;
   - **Gaussian blur at s = 0.4625**: failed;
   - **Gaussian noise at s = 1.00**: failed;
   - **Contrast reduction at s = 1.00**: passed;
   - **Darkening at s = 1.00**: passed.

   The blur clip shows what the policy saw at the smallest blur that breaks
   it.
4. In **Report**, read **Summary**. **Expected:**
   - unperturbed control 0 of 5 failed;
   - Gaussian blur fails from s = 0.46, a blur sigma of 3.70 px;
   - Gaussian noise fails only at s = 1.00 (noise sigma 100 of 255);
   - darkening and contrast: no failure up to s = 1.00.
5. In the second table, **Levels in the order tried**, follow blur:
   - 0.2: 0/5 and 0.4: 1/5;
   - 0.6: 4/5, so the gate is met;
   - then bisection: 0.5: 4/5, 0.45: 1/5, 0.475: 4/5, 0.4625: 5/5.

   The boundary lies between 0.45 and 0.4625.
6. **Research context:** public sources about the robustness of
   vision-language-action policies to degraded images, found with Tavily and
   summarised by Nemotron 3 Nano. Context, not evidence.
7. **Run details:** 2 Jobs (the check, and one probe Job for the four
   families), US$0.90, about 37 minutes.

**Talking point:** "The start passes untouched. Blur with a sigma of under
4 pixels breaks it every time, while darkening and contrast at full strength
do not. Faultline found that boundary to within 0.0125 severity, and the case
reruns it on the next checkpoint."

What each family and severity means physically is in the
[Reference](reference.md), section 5.

---

## Demo 3 — When nothing breaks it, or the start is unreliable

**Point:** "No failure found" within a tested range is a result, not an
error. A start that fails some attempts untouched cannot blame a
disturbance.

1. Under **Cases**, open **catalog-spatial** (`FL-A-F526`).
   **Expected:** verdict **No failure found** (green), LIBERO-Spatial task 0.
2. **Summary:** the unperturbed control failed 0 of 5. JPEG compression,
   colour cast, motion blur and dead pixels each show "no failure up to
   s = 1.00".
3. **Videos:** the control and the four families at s = 1.00, all passed in
   green.
4. **Levels in the order tried:** every family was tried at s = 0.2, 0.4,
   0.6, 0.8 and 1, with 5 attempts each. All are 0/5 except motion blur at
   s = 1: 1/5, which does not meet the 4-of-5 gate.

**Talking point:** "The policy kept working through JPEG at quality 5, a
strong colour cast and 20% dead pixels. One motion-blur failure at full
strength is not a repeatable failure."

**An unreliable start.** If the check fails some attempts but not 4 of 5,
the run ends with the **flaky** route. Nothing more runs, no case is made, and
no disturbance is blamed. The run page shows "The start is flaky untouched"
in amber.

### Optional wording example (local archive restored)

Open **ui-paraphrase-spatial**, fault code **FL-L-C72C**, under **Cases**.
It is the recorded October 17 run, not a new test. In the report's **Screen** table, the
original instruction has two successful attempts; each of four rewordings has
one successful screening attempt and passed the mechanical meaning check.
No wording failed reliably, so there was nothing to confirm or reduce.

Talking point: "We also test whether changing the instruction's wording breaks
the policy. These four did not, at this one task and start. That is a bounded
success result, not proof of general language robustness."

This case is restored in the local panel only. It has not been added to the
published gallery or the bundled demo. Its archive copy is preserved; no new
GPU Job or language-model call was needed.

---

## Demo 4 — Plan a diagnosis without spending (dry run)

**Point:** one New diagnosis. The review shows what will happen in each case
and what it costs, before anything is created.

1. In the sidebar, choose **New diagnosis**. **Expected:** the promise
   "Faultline runs your start untouched. If it fails, it finds the smallest
   change that triggers it. If it passes, it looks for the smallest
   disturbance or rewording that breaks it."
2. Under **What do you want to do?** (with "A start is one of the
   benchmark's 50 fixed starting layouts for a task"), choose one:
   - **Check a start I name** (the usual). This is how you bring a failure
     from your own evaluation. In the standard LIBERO evaluation, episode *n*
     (counted from 0) begins from start *n*. Some tools count from 1 or across
     tasks.
   - **Find a failing start for me**: tries a range of starts and shrinks one
     that fails reliably. No probes.
   - **A failure from my own scene (file)**: a saved start state outside the
     50 benchmark starts (Demo 1's variant). No probes.

   Each option shows its route in one line. Choose **Next: settings**.
3. **Settings**, for a named start:
   - **Suite**, **Task** (its instruction is shown) and **Start**. The
     defaults are LIBERO-Object, task 0, start 0.
   - **If the start passes untouched, also probe**, on by default, with
     **Disturbance families**. **Blur**, **Noise**, **Darken** and
     **Contrast** are ticked, "where the policy has failed before"; the other
     six are one tick away.
   - **Rewordings to ask for** (0 skips them).
   - **Spend cap (US$)** (default 2.5) and **Hour limit** (default 1.5).
   - The Nemotron option.
   - **Find related research**, ticked only when a Tavily key is found.
     Without a key, Review shows a note; it never blocks Start.

   Choose **Review**.
4. **Expected on Review**, under **Dry run**, three blocks. Each has its
   Jobs, a **Worst case** and a **Typical** estimate:
   - **First: check the start untouched**: typically about US$0.43 and
     16 minutes.
   - **If it fails: find the smallest layout change**: typically about
     US$0.68 and 25 minutes. Continuations are used only if needed.
   - **If it passes: probe**: LIBERO-Object fits the four default families in
     one Job, typically about US$0.82 and 29 minutes.

   Then **Total worst case** (the check plus the larger branch), **Typical
   total if it fails**, **Typical total if it passes**, and **This machine**
   (the setup checks).
5. **Do not press Start diagnosis.** With the default US$2.50 cap, Review
   says "The first Job fits, but not all of them" and names `reduce` and
   `probe-image-1`.
   - Each Job is charged what it measured, so those are refused only if the
     check costs its worst case (US$1.22).
   - A typical check leaves room for either branch's first Job.
   - A run stopped at the cap can be resumed after raising it.

**Edit YAML** shows the `mode: diagnose` spec the form writes. Once you edit
it, it becomes the source of truth until **Discard YAML edits and use the
fields**. The wizard's own **Back** returns to the previous step; the
top-left **Back** returns home and drops the form.

---

## Demo 5 — Run it: watch the route, stop and resume (paid)

**Point:** the whole loop from the browser, with a safe stop.

**Recorded example:** `FL-A-D582` was made this way on October 19, with the
defaults (LIBERO-Object, task 0, start 0, four families, US$2.50 cap). Only
one paid run can be active at a time; a start is refused while another run's
process is alive.

1. Follow Demo 4 with a cap and hour limit you agree to, then choose **Start
   diagnosis** once.
2. **Expected:** the run page opens.
   - The readout's status word follows the Job: **Submitting a Job**,
     **Waiting for a GPU** (amber), **Running**, **Downloading results**.
     The readout also shows the current step and **Spent** of the cap.
   - **Cloud Job** shows the Job's phase; **Spend and time** shows spent
     (solid) and the reserved worst case (hatched).
   - The run appears under **Running** in the sidebar.
   - **Steps** starts with **Check the start untouched**.
3. Once the check is read, the run page shows the **route**:
   - "The start failed untouched: finding the smallest layout change" (red);
   - "The start passed: probing" (green; the recorded example);
   - "The start is flaky untouched" (amber). Either it failed some attempts
     but not 4 of 5, so nothing more runs; or a probe's own control failed,
     so the probes still to come are skipped.
   - "Passes untouched" (no probes chosen).

   If the check cannot decide (an unfinished or invalid start), the run stops
   with `check_incomplete`; a resume reruns the check.
4. **Recorded timings:**
   - the check took 16 minutes: 5.3 waiting for a GPU and starting, 8.1
     running, about 2.4 reading the results (US$0.35);
   - the probe Job took 30 minutes (US$0.54). Only 6.5 of those were testing
     (135 episodes at 20.9 a minute); 5.6 were downloading the model.

   The run took 36.5 minutes and US$0.90 in all.
5. Leaving the page or closing the tab does not stop the run. The run page
   refreshes every 5 seconds while the run is active (and pauses while the
   tab is hidden). The sidebar's **Running** list refreshes every 10 seconds.
6. **To stop:** choose **Stop**, then **Stop the run** (or **Keep running**).
   The status shows **Stopping** while the current Job is cancelled and
   charged for the time it ran (nothing if it never got a GPU).
   - A stop after a probe Job finished still saves that probe's case.
   - **Resume** continues the same run from its last finished step. It
     re-attaches to a Job that is still running and never pays for that Job
     twice, but work that **Stop** cancelled runs again on a new Job and
     costs again.
7. **At the end:** status **Completed** and "The case is saved." When you
   watch a run finish, the page opens the case after a 3-second countdown;
   **Stay here** cancels it.

**Rewordings.** Set **Rewordings to ask for** above 0 to add a wording probe.
Nemotron 3 Super writes everyday rewordings, a meaning check drops any that
lose an object or target, and a failing wording is reduced to the smallest
word change. The wording probes run so far found no failure: GR00T passed
every rewording tried.

If **Start** reports a timeout or a server error, do not press Start again.
The page shows its own warning ("The run may have started…") and hides
Start. Check **Running** in the sidebar for a minute; the server waits up to
30 seconds for a new run to report in.

---

## Demo 6 — Regression test: rerun a case on a policy (paid: one Job)

**Point:** every case is a regression test. After the policy changes, rerun
its failing condition and see whether it still fails.

1. Open a case with a failure, for example `FL-A-D582`, and scroll to
   **Regression test**. The purpose line says what it reruns:
   - a layout case: the minimal scene and its passing reference;
   - a disturbance case: each failing disturbance at its threshold, with the
     unchanged start as its control;
   - a wording case: the failing wording, with the original as its control.

   Five attempts each.
2. Under **Test a policy**, choose **Which policy do you want to test?**:
   - **The original policy**: the case's own checkpoint. This confirms the
     failure still repeats. For the first Demo 6 walkthrough, choose this;
     no checkpoint ID or revision needs entering.
   - **A new checkpoint**: for example a retrained policy. Fill in
     **Hugging Face model id** and **Revision (commit hash)**; both are needed,
     so the result names exactly which policy ran. Use a compatible GR00T N1.7
     checkpoint in LeRobot format for the same LIBERO suite and its full pinned
     commit hash. A model name or arbitrary latest revision is not enough.
3. The cost line says "Costs up to US$… on your Nebius account if you run
   it." **Limits** (closed) holds the spend cap and hour limit, pre-filled
   from the test's own plan.
4. Choose **Estimate cost**. The review lists the Job and its worst case.
   **Stop here unless the spend is agreed.** With agreement, choose **Run the
   test** once.

**Expected result**, under the section's history, with the policy tested:

| Result | Meaning |
| --- | --- |
| **Still fails** (red) | The failing condition still fails. |
| **Fixed** (green) | On a new checkpoint, it no longer fails. |
| **Did not repeat** (amber) | On the original policy, it no longer failed: the case may be flaky. |
| **Inconclusive** (amber) | The control failed, the Job did not finish, or the test stopped part-way. |

**Recorded:**
- `FL-A-D582`, October 19: **Still fails** on the original policy, US$0.35.
  Blur at s = 0.4625 failed 4 of 5. Noise at s = 1.0 failed 3 of 5 (it
  failed 4 of 5 when found), so its threshold is borderline.
- `FL-S-8E0D`, October 19: **Still fails** on the original policy
  (`nvidia/gr00t17-lerobot-libero_10-640` at `5ee08ab`), US$0.37. The minimal
  scene failed again and the reference passed 5 of 5.

**From a script:** the section shows the command
`faultline replay <case folder> --spec replay.yaml --expect fixed`, which
exits 0 when the verdict is the one expected. Use `--expect reproduces` for
the original policy. A new checkpoint goes under `policy.checkpoint` in the
spec.

**Regression test or New diagnosis?** A regression test reruns a known
failure, so results compare across checkpoints. It catches a fixed failure
that comes back later. A New diagnosis searches afresh for failures; see the
Reference, section 1.

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
| **Completed** | Finished, including "No failure found" and the flaky route; **Open the case** shows the result when there is one. |
| **Stopped**, **Failed** | Ended early; the text says why. **Resume** if offered. |
| **Interrupted** | The run's process ended unexpectedly. **Resume** re-attaches to any Job it left running. |

Colours: green for a pass, red for a failure, amber for anything that needs
attention, always with an icon and a word. The run page also shows the
**route**: layout, probes, flaky or passes.

- **Videos:** every case kind shows clips:
  - layout: original, minimal and reference;
  - disturbances: the control, and each family at its threshold or top
    severity;
  - rewordings: original and reworded.

  A case recorded without them says so.
- **Regression test:** any case with a failing condition and saved inputs
  can be rerun. A case without saved inputs says it cannot be.
- **"Stopped early" on a reproducing layout case:** the entity reduction
  finished, but the size shrinking did not. Sizes at 100% are not minimal.

## Recovery

| Symptom | What to do |
| --- | --- |
| Setup: Nebius sign-in needs attention | Run `nebius iam whoami`, sign in, **Check again**. Then **Resume** any stopped run. |
| Run fails at once: "a Nebius quota is used up" (buckets) | Each run's bucket is kept until its objects expire (1 day). Delete emptied `faultline-*` buckets (Nebius refuses non-empty ones), then **Resume**. |
| Cloud Job: waiting for a GPU | Normal. It resubmits up to six times; nothing is billed while waiting. |
| Status **Interrupted** | **Resume**. |
| Stopped at the spend cap or hour limit | Under **Raise the limit before you resume**, enter a larger **New spend cap (US$)** or **New hour limit**, then **Resume**. A limit can be raised on a resume, never lowered. |
| Stopped: `download_failed` | The Job finished and is paid for, but its results could not be downloaded (a dropped connection). **Resume**: it downloads them again, keeps files already complete, and does not run the Job again. |
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

1. **The layout case** (Demo 1) → **Play all** at `0.5x`: failing, minimal,
   passing. In the Summary, the shifts are needed together. In
   **Candidates**, each alone passes and removing any one passes.
2. **`FL-A-D582`** (Demo 2) → **Play all**: the control passes; blur at
   s = 0.4625 fails. "A blur sigma under 4 px breaks it every time."
3. **Regression test** on either case: the history shows **Still fails** on
   the original policy. "After the next fine-tune, the same test says Fixed or
   Still fails."
4. Close on `FL-A-F526`: nothing broke it, and evidence is specific to these
   starts, this policy and these attempts.

For the control panel, add: **New diagnosis** → **Check a start I name** →
**Next: settings** → **Review**. Show the check, the two branches with their
typical cost and time, and stop before Start.
