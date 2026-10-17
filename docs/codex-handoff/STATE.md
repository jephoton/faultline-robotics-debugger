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
The **published gallery still shows the old audit wording** until it is
re-exported and redeployed, which needs Jethro's go.

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

1. M7b: plan the three-minute pitch/demo, write-up, public-repository/judge setup
   audit, required tool feedback and billing reconciliation. Roadmap target is
   October 29; recorded submission deadline October 30, 10:00 PT.
2. Keep the public gallery static. New cases or regenerated interpretations
   require inspecting the changed public payload before redeploying. The
   publication record discloses absent audit videos, no default paraphrase
   case, M4's stored explanation fallback and unfinished scenario size search.
3. Any new paid experiment, hosting upgrade or public container image requires
   its own accepted scope and gate; M7a completion does not authorize it.

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
