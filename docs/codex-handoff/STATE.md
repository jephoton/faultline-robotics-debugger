# Faultline current project state

> Generated handoff snapshot, maintained against committed code and experiment
> notes. Older entries are preserved in
> [the historical state archive](STATE-history-through-2026-10-17.md); their
> next steps, balances and one-run allowances are not current authority.
> Read **Post-walkthrough cleanup — October 19** for the latest work.
> Earlier dated proposals and allowances below are historical, not new authority.

## Current position — October 19, 2026

Jethro finished the six demo walkthroughs and explicitly authorized the complete
cleanup batch inline, including suppressing transient command windows and
rewriting Reference/Run your own. Implementation and local verification are
finished; see the checkpoint below for publication and submission gates.

## Post-walkthrough cleanup — October 19

- Accepted repair branch `worktree-agent-aff20f6737887e095` merged, preserving
  the legacy-audit report fix. Manual UI copy items 51/52/54 applied. The older
  “two agents in flight” handoff below is superseded, not work to redo.
- Captured backend CLI calls use `CREATE_NO_WINDOW` on Windows; a real child
  returned console handle zero. Output, exit codes and timeout propagation
  remain tested. Detached owner, process groups, Stop and Resume are unchanged.
  Restarted the local viewer with no active runs, using its owned terminal.
- Reference is an evidence dictionary (about 2,520 words versus 5,611 before),
  with gates, severity formulas, report fields, replay verdicts and claim limits.
  Run your own is the operational route with stable Setup anchors and links to
  detailed setup/UI scenarios. Quickstart no longer describes old modes or
  scenario-only replay, or puts token values on CLI arguments.
- D582 next steps refreshed from stored sources: first response rejected,
  single repair accepted, four suggestions. Provenance: two attempts, 6,973
  prompt tokens, 472 completion tokens. US$0.04 is the two-response reservation
  envelope, not a billed charge. No GPU Job or Tavily search. Case ID unchanged.
  Initial commentary incorrectly said one attempt and was corrected from the
  saved record. `research.previous.json` keeps the earlier interpretation.
  After refresh, all **1,312** raw evidence files matched the **two original
  export manifests**; no measured outcomes were rewritten.
- FL-S-8E0D's offline demo refreshed from registered evidence, including its
  candidate/replay history. Accepted next steps and source titles/URLs are
  included, but source snippets/search text and the private run-folder selector
  are excluded. Original artifact files remain unchanged. Its existing accepted
  scenario suggestions were retained, not regenerated or claimed improved.
- Verification: full local Python suite **3,103 passed, 60 skipped, 3,153
  subtests passed**; added offline-demo/export checks **34 passed, 36 subtests**.
  Full web suite **336 passed**, typecheck/build passed. Windows tests covered
  hidden runner behavior and unchanged lifecycle. Browser checked the rewritten
  docs/anchors, three showcase cases, wording example, unchanged evidence
  tables, New diagnosis through dry-run Review, and static three-case preview;
  no page errors, failed responses or paid Start actions. Existing React
  `act(...)` warnings remain non-failing. Skips are not validation of optional
  dependencies or live-GPU paths.
- Prepared **only** the approved three-case/13-video export at ignored
  `artifacts/public-gallery-20261019-cleanup-final/`; exporter privacy checks and
  static preview passed. No production redeploy. Do not copy private artifacts,
  `.env` or credential-bearing Vercel files into it.
- Preview caught one existing card-summary error: a partly reduced case said
  sizes were not shrunk. It now says **not fully shrunk**, with a failing-then-
  passing regression assertion. Another 56 library/demo tests and 27 subtests
  passed. Integrated into `main` without history rewrites; GitHub authentication
  was verified as `jephoton`, and the cleanup was pushed. CI for the final
  checkpoint must be checked independently of earlier recorded counts.

**Next:** reviewed gallery redeploy needs Jethro's go. Then do billing
reconciliation, first-hand FEEDBACK review, clean-checkout/public-repo audit,
current Devpost rules check, write-up, pitch video/cover and final submission.
These have not been claimed complete. No new GPU tests are needed for cleanup;
M3/HPC expansion remains optional stretch work.

Execution plan: [final cleanup batch](../superpowers/plans/2026-10-19-final-cleanup-batch.md).

## Earlier M7a completion checkpoint — October 17

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

- **One diagnosis workflow:** check the start untouched, then reduce a reliable
  failure's differences from a passing reference, or probe a passing start with
  image/scene families and instruction rewordings. A flaky start stops without
  blaming a disturbance. The CLI owns diagnosis, spend ledger, evidence,
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
  case evidence, scenario Replay, setup checks and guide. Local
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

## UI walkthrough follow-up — October 19

- Jethro completed Demo 6 and authorized the full inline cleanup batch above.
  The earlier wait-for-walkthrough gate is cleared. Public redeploy and the
  submission-readiness checks remain separate gates; no new GPU work was run.
- **FL-A-F526 table fix:** its older single-audit case has a saved `audit`
  summary but no `groups`. The report-regeneration helper only handled grouped
  cases, so it misleadingly kept the old compact table. It now uses the saved
  legacy step when groups are absent, retaining the safeguard for missing
  explicit group summaries. F526's local report/registration was refreshed
  with zero Token Factory/Tavily/Job calls and recoverable report backups.
  Raw summary and case-file SHA-256 values stayed unchanged. Both F526 and
  D582 render four readable per-family level tables in the local browser.
  The public export is not refreshed by this local change.
- **All evidence warning diagnosed, not fixed:** six historical M3 synthetic
  dry-run aggregates contain `synthetic`/`case_id`, not the real harness
  `benchmark`/`tasks` fields. The generic catalog scans them and emits one
  `synthetic_aggregate.json: KeyError` per file. The warning list is a scan
  diagnostic, not robot-policy failures; the API still returned 2,022 episodes
  during inspection. No evidence or archive data was removed.
- **Latest accepted UI scope (supersedes the earlier proposals):** Jethro
  rejected arbitrary type labels for the unified pipeline and explicitly asked
  to remove All evidence. Use one Cases list without type headings/badges in
  navigation and the static home gallery. Keep names, fault codes, outcomes,
  case-specific methods and per-case Full evidence; preserve raw records and
  internal APIs. A broader Reference/Run your own cleanup is still only a
  proposal: no whole-document rewrite is approved.
- **Wording example restored locally:** copied the archived
  `ui-paraphrase-spatial-20261017T015821Z` run back into `artifacts/runs/`;
  report and step hashes matched on copying, and the archive copy remains untouched.
  The library exposes **FL-L-C72C**: original instruction succeeds twice;
  four rewordings each succeed once in screening. No reproduced wording
  failure and no reduction. No GPU/model call, new test or gallery publication.
- The restored report's old canned limitations falsely implied failures and a
  minimal wording. Its formatter now conditions those claims on observed
  outcomes and verified/edit-minimal reduction evidence. Regenerated only the
  restored local report from its saved summary, without model calls; original
  archive report, raw language summary and steps stay unchanged. The summary
  tables, attempt counts and case identity are unchanged. Relevant Python
  suites passed: 163 tests and 105 subtests.
- **Navigation verification:** 334 web tests passed (including axe structural
  checks), TypeScript check and production build passed; 53 library tests plus
  20 subtests passed. Independent specification and quality reviews passed.
  Browser checked all five local cases in one input-ordered Cases list,
  FL-L-C72C's original plus four wording rows, and `/evidence` Not Found with
  zero evidence-API requests. D582/F526 still expose four per-family tables
  inside Full evidence. No page errors or paid calls. Existing React test
  `act(...)` warnings remain outside this change.
- **Windows console flashes investigated from code:** each backend command
  starts the Nebius CLI (with WSL as the Windows fallback); `backends.run_command` captures
  output but has no Windows no-window flag. The detached diagnosis owns a
  sequence of short-lived commands, including Job status polls (default 60 s).
  Browser progress polling only reads local state; it is not a GPU submission.
  Flashes therefore do not imply duplicate paid Jobs. This source-based
  diagnosis was not reproduced with a paid run. Process flags/lifecycle are
  unchanged; any quiet-launch fix must preserve detachment, Stop and auth.
- Demo 6 on the existing policy needs **The original policy**, not a guessed
  model ID/revision. New-checkpoint inputs are for a compatible GR00T N1.7
  LeRobot checkpoint and pinned Hugging Face commit, not an arbitrary model.
- The 79-item copy branch (`5e22e9f`) and repair branch are now merged; the
  three manual copy items are applied. Use the post-walkthrough checkpoint's
  current verification, not the older pending-integration instructions below.

## Previous handoff: October 19, evening (superseded by cleanup above)

### Historical branch briefs (both integrated; do not redo)

1. **`worktree-agent-a3b9101bc186fa838`: UI copy changes.** It applies every
   item in `docs/superpowers/specs/2026-10-19-ui-copy-review.md` (Jethro
   approved all of them), except items 51, 52 and 54. Those are in
   `web/src/components/case/TeamSections.tsx`.
   - Merge the branch.
   - Then apply 51, 52 and 54 by hand.
2. **`worktree-agent-aff20f6737887e095`: one repair retry for next steps.**
   - When the check rejects an answer, the model gets the reason and rewrites
     it once.
   - It adds a prompt rule: no combined-removal suggestions when single
     removals already settle it.

   This is needed because `FL-A-D582`'s next steps were rejected 3 times for
   cause or proof wording.

If either branch is missing or unfinished, redo it from its brief: the spec
file for (1), the description above for (2).

### Integration after both merges

1. **Built bundle conflicts.** If `src/robot_debug/viewer/app/` conflicts,
   resolve it by rebuilding:
   - `rm -rf src/robot_debug/viewer/app/assets`;
   - `cd web && npm run build`;
   - `git add -A src/robot_debug/viewer/app`.
2. **Tests:**
   - `cd web && npm run typecheck && npm test -- --run`;
   - `PYTHONPATH=src python -m pytest -q -p no:cacheprovider` (never `uv run`).
3. **Regenerate the next steps.** Token Factory only, about US$0.01–0.02 per
   case:
   - `PYTHONPATH=src python -B scripts/regenerate_case_context.py artifacts/runs/object-start0-20261019T021756Z --env-file .env`;
   - run `--dry-run` first;
   - optionally the same for `artifacts/runs/l10-start14-20261019T032219Z`.

   A rejected answer keeps the old one.
4. **Check in the browser.** Restart the panel (it caches the library), then
   check:
   - Home, New diagnosis and the Review step;
   - `FL-S-8E0D`, `FL-A-D582` and `FL-A-F526`: why it's trustworthy, the
     Nemotron box and the regression test.
5. **Update `docs/ui-runbook.md`** for the changed copy:
   - the "Typical (estimate)" label;
   - removed hints;
   - the Regression test fields;
   - the Nemotron box;
   - why it's trustworthy;
   - the default name `object-t0-start0`.
6. **Refresh `demo/root`.** Copy `artifacts/diagnoses/8e0dbd…/` again, since
   its report, case and explanation changed.
   - Keep `research.json` out (it has third-party snippets), or ship a copy
     with snippets stripped so the offline demo shows its next steps.
   - Drop `research` from `diagnosis.json` `files` if it is left out.
7. **Gallery redeploy (needs Jethro's go):**
   - `faultline export --out artifacts/public-gallery-<date>`, with a
     `--case` flag for each of `d-8e0dbd…`, `d-d5825d…` and `d-f52646…`;
   - copy `.vercel/project.json` from `artifacts/public-gallery-20261019/`;
   - scan for ids, keys and paths;
   - `vercel deploy --prod --yes --cwd artifacts/public-gallery-<date>`;
   - record it in `docs/experiments/m7-public-gallery.md`.

### Known small items

- `FL-A-F526`'s report-refresh issue is resolved locally in the UI follow-up
  above: the saved summary was present; the helper did not handle its legacy
  single-audit case shape. Its public copy still awaits a separately approved
  export/redeploy.
- The old cases are archived locally in `artifacts/archive-2026-10-19/` (see
  its README). The WSL `.venv` was mostly deleted by `uv run`; recreate it
  only if needed.
- This machine's network is flaky: Avast WebShield blocked agents, and there
  were DNS and EndpointConnectionError drops. Downloads now retry and resume.

### Remaining to submission

Target October 29; deadline October 30, 10:00 PT.
1. **Finish the demo walkthrough.** Jethro is at Demo 6. Demos 7–8 are paid
   (a replay, and start/stop/resume), so they need a go and a cap, or can be
   skipped.
2. **Integrate, check and redeploy** (above).
3. **Billing reconciliation.** Jethro reads the Nebius billing page. Ledger
   estimates:
   - showcase runs US$3.87;
   - earlier live runs about US$8.21;
   - Token Factory about US$0.15 on October 19 (Ultra's price is not pinned).

   Correct `FEEDBACK.md` and the README costs to match.
4. **`FEEDBACK.md` final pass,** with Jethro's first-hand notes. Add the
   October 19 observations:
   - the per-object download retries and the resume download fix;
   - Ultra's structured output and its rejection rate;
   - Vercel redeploys.
5. **Fresh-machine test** of the README and quickstart from a clean checkout.
6. **Rules re-check:** Devpost rules and updates.
7. **Devpost text:**
   - the story from ADR 0034;
   - the LIBERO scope line;
   - the episode-14 evidence (`docs/experiments/m7-workflow-evidence.md`);
   - the three showcase cases.
8. **Video** under 3 minutes, using the runbook's 90-second route and
   `docs/architecture.md`, **plus a cover image.**
9. **Submit:** freeze versions and tag the release.

**Agreed order (Jethro, October 18):** demos → stale public gallery → remaining
things → video and cover → submission. Roadmap target October 29; deadline
October 30, 10:00 PT.

1. **Demos.** The runbook is restructured into six demos around the showcase
   cases (October 19). Jethro walks through them next and reports what each
   exposes.
2. **Gallery refresh: done October 19** (Jethro's go). The live gallery holds
   the three showcase cases (`docs/experiments/m7-public-gallery.md`). The
   old cases moved out of the local panel to `artifacts/archive-2026-10-19/`,
   which can be restored. Redeploy once more after the demo walkthrough's
   fixes; the policy-failure glossary row is not live yet.
3. **Remaining things:**
   1. **Done on October 19:**
      - the final showcase runs, recorded in
        `docs/experiments/m7-final-showcase.md` (US$3.87 by ledger);
      - the nine-item polish pass;
      - the removal of the departing cases from product documents and code;
      - the `demo/root` swap to `FL-S-8E0D`;
      - the workflow evidence note.

      The regression loop is shown on the same checkpoint;
      `nvidia/GR00T-N1.7-LIBERO` is in a format the override does not load.
   2. **Results refresh:** README "What it has found", built around the
      showcase cases.
   3. **Billing reconciliation:** Jethro reads the Nebius billing page; compare
      it with the run ledgers; correct FEEDBACK and README costs.
   4. **FEEDBACK.md** final pass, with Jethro's first-hand notes.
   5. **Fresh-machine test** of the README and quickstart from a clean checkout
      (judge usability).
   6. **Rules re-check:** Devpost rules and updates, including any "what changed
      during the submission period" requirement.
   7. **Devpost description** from ADR 0034's story, with the LIBERO scope
      line and the episode-14 evidence (`docs/experiments/m7-workflow-evidence.md`).
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
