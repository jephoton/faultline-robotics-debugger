# Faultline current project state

> Generated handoff snapshot, maintained against committed code and experiment
> notes. Older entries are preserved in
> [the historical state archive](STATE-history-through-2026-10-17.md); their
> next steps, balances and one-run allowances are not current authority.

## Current position — October 17, 2026

M1–M6 are complete. M7a steps 1–4 are complete, including the control panel's
live acceptance check. The immediate work is **M7a step 5: publish the static
gallery**. Jethro explicitly authorized it after the handoff refresh on
October 17. Execution plan:
[public gallery](../superpowers/plans/2026-10-17-public-gallery.md).
Publication is authorized for the filtered gallery only, not the repository's
visibility, a public container image, paid hosting upgrades or new GPU runs.

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

At refresh start, local and remote `main` both resolved to `9b39b5d`, with a
clean working tree and successful GitHub CI for that commit. CI ran 2,851
Python tests with eight skips; the web test/build/type-check and committed-bundle
freshness checks passed. These are dated evidence, not a fixed expected test
count. Later changes must be checked independently.

The live UI check exposed and fixed: bucket-quota diagnostics, Windows panel
shutdown killing its child run, interrupted/resumed status, Resume polling,
first-Job budget admission, no-failure completion presentation and paraphrase
step labels. Resume reattached the existing Job rather than submitting it twice.
These are recorded project defects, not inferred provider or robot failures.

## Next actions and gates

1. Complete and commit the current architecture/runbook refresh.
2. Generate a fresh ignored gallery export; inspect public projections, reports,
   media and static-mode behavior independently before uploading anything.
3. Use Vercel for the accepted static publication; no credentials or Python
   backend in the deployment. If authentication or account selection is
   unavailable, request only the missing user action.
4. Verify public visitor access, case deep links, media and browser behavior;
   record the stable URL and acceptance evidence. Do not mark M7a complete
   before these checks pass.
5. M7b follows: three-minute pitch/demo, write-up, public-repository/judge setup
   audit, required tool feedback and billing reconciliation. Roadmap target is
   October 29; recorded submission deadline October 30, 10:00 PT.

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
