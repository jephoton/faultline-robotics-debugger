# Faultline current project state

> Generated handoff snapshot, maintained against committed code and experiment
> notes. Older entries are preserved in
> [the historical state archive](STATE-history-through-2026-10-17.md); their
> next steps, balances and one-run allowances are not current authority.

## Current position — October 17, 2026

M1–M6 and **M7a steps 1–5 are complete**, including the control panel's live
acceptance check and the published
[static gallery](https://faultline-robotics-debugger.vercel.app).
Jethro explicitly authorized publication after the handoff refresh on
October 17. Execution plan:
[public gallery](../superpowers/plans/2026-10-17-public-gallery.md).
Publication is authorized for the filtered gallery only, not the repository's
visibility, a public container image, paid hosting upgrades or new GPU runs.
Next is **M7b: demo/video and submission preparation**.

## What exists and what has been demonstrated

- **Two modes:** debug a failing simulator start by reducing its differences
  from a passing reference; audit a passing start with image/scene families or
  instruction paraphrases. The CLI owns the diagnosis, spend ledger, evidence,
  report and case. Four LIBERO suites have live execution evidence.
- **Scenario result:** LIBERO-10 task 0, start 14 versus passing start 28 needs
  a conjunction of five entity shifts. Entity removal is locally minimal;
  shift sizes are only partly reduced, not a global minimum. The case was
  replayed on October 15 and independently replicated through
  `scenario.import` on October 16. See
  [the experiment](../experiments/m7-scenario-reduction.md).
- **Other evidence:** occlusion reduced from 25% to 14.0625% image area;
  external-state replay; camera-role hypotheses; blur/noise thresholds; and
  breadth tests across four suites. Success within a tested range is a valid
  result, not a failure to diagnose. See [the results index](../README.md).
- **NVIDIA/Nebius:** GR00T N1.7 runs on finite Nebius Serverless L40S Jobs.
  Nemotron 3 Ultra proposes scenario hypotheses and explains scenario/occlusion
  evidence, Super generates paraphrases, Nano summarizes Tavily research.
  Model prose is interpretation, not measured evidence (ADR 0030).
- **Control panel:** `faultline ui` serves the committed React/Vite bundle.
  It includes diagnosis setup/dry run/confirmation, live progress, Stop/Resume,
  case evidence, scenario Replay, setup checks, guide and All evidence. Local
  controls require loopback, session token and same-origin checks; one paid run
  at a time. `faultline export` produces a separate static, control-free gallery.
- **October 17 live panel check:** LIBERO-Spatial task 0/start 0, four Nemotron
  paraphrases retained by the meaning check; controls and all paraphrases
  succeeded, so reduction was skipped. Measured-time cost estimate US$0.31
  against the separately approved US$1.30 cap. Result fault code `FL-L-C72C`.
  See [the live check and fixes](../experiments/m7-breadth-pack.md).

## Verified engineering checkpoint

October 17 UI follow-up: the shared shell now has a compact Back button at the
top left of the main-content column, outside the sidebar, on non-home routes.
It always returns home, including when the previous app page was a case;
the diagnosis wizard's separate Back buttons still select the previous step.
Local Python server startup/health and real-browser desktop/mobile
navigation passed; 180 web tests, type check and the production bundle build
passed. No Python/provider execution behavior changed. The public gallery
remains the reviewed publication below; this local UI update has not been
redeployed. The canonical [architecture](../architecture.md) now contains the
full-system/user-journey Mermaid diagrams, glossary, Mode 1/Mode 2 versus the
three execution paths, source anchors and a full page/field/action/evidence UI
inventory. `PROJECT.md` is a short handoff pointer, not a duplicate architecture.
Rewordings belong to the policy-audit intention but retain a separate word-edit
engine. Regrouping the three New diagnosis cards under two intentions is a
proposal for Jethro's review, not an implemented redesign.
Token Factory costs remain outside the GPU ledger; the diagram is not an
all-services budget guarantee. Source audit also identified over-broad UI copy
about causes/minimality, retry cost and incomplete audit coverage; these are
documented review points, not fixes or new validation claims.

October 18: the [UI user runbook](../ui-runbook.md) follows the Tencent
project's demo-runbook format: Setup, then nine demos, each with its point,
exact clicks and inputs, expected output and talking point. Demos 1–5 read the
recorded cases (expected values checked against the live API on October 18).
Demo 6 makes dry runs of every New diagnosis option, with the expected Job
table at the form's defaults. Demos 7–9 (replay, start/stop/resume, import)
are marked paid. Result interpretation, recovery, reset and a 90-second video
route follow. It is distinct from architecture/setup documentation and does
not authorize the paid actions it describes.
Two product fixes came out of checking it:
- The replay cap default (US$1.00, in both the spec template and the panel's
  replay form) was below the replay Job's worst case (US$1.08), so a default
  replay would be refused; both are now US$1.20.
- An audit family the run never searched (scene-goal, where the control
  failed) read "No failure up to severity 1" and "no failure found". It now
  reads "Not tested", and a partly searched family reads "Incomplete".
The gallery was redeployed with the corrected wording on October 18
(`docs/experiments/m7-public-gallery.md`).

Also on October 18:
- A reduction bug was fixed: a verified smaller size was discarded when the
  budget ended between a speculative bisection pair. `FL-S-AFB5`'s arm offset
  was proven at 75% but recorded at 100%. Takes effect from the next image.
- Keep in step now re-aligns clips.
- New technical documentation, consolidated on October 18 into the
  [Reference](../reference.md), which is also a page in the control panel.
- **Next:** the
  [report-first case page and traces plan](../superpowers/plans/2026-10-18-report-first-case-page-and-traces.md).
  Part A (the report-first page) is merged. Part B (per-step traces) is
  **paused**.
- **Narrative settled** (ADR 0034): the minimal trigger, kept as a regression
  test. The README opens with the team workflow, the gap and regression
  testing.
- **Final runs:** fresh reduced cases plus a replay against a second
  checkpoint, on a new image.

At refresh start, local and remote `main` both resolved to `9b39b5d`, with a
clean working tree and successful GitHub CI for that commit. CI ran 2,851
Python tests with eight skips; the web test/build/type-check and committed-bundle
freshness checks passed. These are dated evidence, not a fixed expected test
count. Later changes must be checked independently.

Gallery acceptance: 77 export/library tests passed; five cases and 25 videos
published. All 55 served files matched the inspected export by SHA-256.
Unauthenticated browser checks passed case deep links, video playback,
static-only controls, three viewport sizes, theme/menu interaction and
automated accessibility checks (with two incomplete case-page checks noted).
See [the publication record](../experiments/m7-public-gallery.md) for exact
scope, limitations and portable regeneration commands. No new paid inference
or GPU experiment was run.

The live UI check exposed and fixed: bucket-quota diagnostics, Windows panel
shutdown killing its child run, interrupted/resumed status, Resume polling,
first-Job budget admission, no-failure completion presentation and paraphrase
step labels. Resume reattached the existing Job rather than submitting it twice.
These are recorded project defects, not inferred provider or robot failures.

## Next actions and gates

**Pipeline decision (October 18, ADR 0035):** one New diagnosis that routes on
the untouched result (fails: layout reduction; passes: the chosen probes),
with every finding a replayable case. Built, reviewed and fixed on October
19 (plan `docs/superpowers/plans/2026-10-18-one-diagnosis-pipeline.md`):
- a stop after a probe group keeps that group's case;
- a start that fails some attempts is routed **flaky** and ends after the
  check;
- an undecided check stops with `check_incomplete`;
- a failing audit control marks thresholds unconfirmed;
- replay is planned per case;
- research never blocks Start;
- the form defaults to LIBERO-Object task 0, start 0.

Default cap kept at US$2.50 (Jethro, October 19). Validation approved the
same day with US$4 in total: a diagnosis of LIBERO-Object task 0, start 0 with
the four default families, then one replay of any case it makes. See
`docs/experiments/` once it finishes. Names come after the build. The
Reference no longer uses "Mode 1 / Mode 2".

**Agreed order (Jethro, October 18):** demos → stale public gallery → remaining
things → video and cover → submission. Roadmap target October 29; deadline
October 30, 10:00 PT.

1. **Demos.** Jethro is working through `docs/ui-runbook.md` demo by demo (at
   Demo 4 on October 18). Fix what each demo exposes as it comes.
2. **Stale public gallery.** It predates the report-first page, the Reference
   page, the readout colours and the Keep in step fix. Re-export and
   redeploy only with Jethro's go, after inspecting the payload.
3. **Remaining things:**
   1. **Final showcase runs** (scope chosen by Jethro, October 19; each paid
      start still needs his go and cap):
      - the probe validation run (LIBERO-Object task 0, start 0, four image
        families) and a replay of its case;
      - image v17 with the October 18 reduction fix, then LIBERO-10 task 0,
        start 14 through the pipeline (layout route) and a replay. This
        replaces `FL-S-AFB5` in the gallery;
      - keep `FL-A-F526` as the "nothing broke it" finding.

      The regression loop is shown by replaying on the same checkpoint with
      `--expect reproduces`. `nvidia/GR00T-N1.7-LIBERO` is the only other
      same-suite N1.7 checkpoint, but it uses Isaac-GR00T's format with
      per-suite subfolders, which the override does not load. It is not
      pursued for the submission. A second-task layout case and a flaky-route
      run were offered and not chosen.
   2. **Gallery refresh** with the new cases (Jethro's go). Export only the
      chosen cases (`faultline export --case <id>`). Drop the September
      occlusion case `FL-M-52D8`, `FL-S-AFB5` (replaced), `FL-A-08D3` and
      `FL-A-A70E`; they stay in the local library.
   3. **Results refresh:** README "What it has found", experiment notes, and
      possibly the `demo/` case.
   4. **Billing reconciliation:** Jethro reads the Nebius billing page; compare
      it with the run ledgers; correct FEEDBACK and README costs.
   5. **FEEDBACK.md** final pass, with Jethro's first-hand notes.
   6. **Fresh-machine test** of the README and quickstart from a clean checkout
      (judge usability).
   7. **Rules re-check:** Devpost rules and updates, including any "what changed
      during the submission period" requirement.
   8. **Devpost description** from ADR 0034's story.
4. **Video and cover:** under 3 minutes, at least 1 minute of the product
   working (story: ADR 0034; the runbook's 90-second route), plus a cover
   image.
5. **Submission.** Freeze the submitted versions.

Gates:
- The trace feature is paused (plan Part B).
- Any new paid run, hosting upgrade or public container image needs its own
  accepted scope.
- New cases or regenerated interpretations need a payload inspection before
  any redeploy.

## Boundaries and remaining limitations

- No new GPU, Token Factory or Tavily allowance is granted by gallery work.
  Old caps are historical. Refresh account/balance/expiry, quotas, prices and
  capacity before proposing a new paid experiment. No account balance is
  asserted here; experiment costs remain estimates pending billing.
- Serverless is validated; the local GPU backend is implemented but untested
  on a real GPU. Job startup optimization and a warm Endpoint are deferred.
- `faultline replay` currently accepts scenario cases, not audit or paraphrase
  cases. Checkpoint override does not guarantee policy/suite compatibility.
- Tavily research remains a manual feature demonstrated on occlusion cases;
  audit and paraphrase cases do not yet receive Nemotron explanations.
- Keep evidence scope explicit: one tested task/start/seed is not universal
  coverage, causal proof or a formal-verification certificate. M3 throughput
  measurements are retained; further HPC is optional stretch, not a release gate.
- `artifacts/` is ignored/local and may hold secrets, raw logs and resource
  identities. Never deploy or commit it wholesale. Bucket object expiry does
  not delete buckets; do not delete evidence or resources merely because an
  old archived entry suggested cleanup.
