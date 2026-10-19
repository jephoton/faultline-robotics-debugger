# Legacy report table consistency and UI pre-evaluation

**Goal:** Make FL-A-F526 use the existing readable per-family level tables,
without new experiments, model calls or a broad UI/documentation rewrite.

**Evidence:** The current renderer already emits severity/failures/result/order
tables (as in FL-A-D582). F526's older case has a single `audit` step and no
`groups`; its saved summary exists. `rebuild_report` only considers grouped
audit cases, misidentifies that legacy shape as missing summaries and retains
the old compact report. Reuse `step_summary(..., "audit")` for legacy cases;
do not substitute one summary when an explicitly grouped case is incomplete.

## Ownership, dependencies and scope

```text
Coordinator: reproduction, exact checkpoint guidance and live-artifact lifecycle
  || read-only evaluator: page purpose/overlap/sizes/sidebar recommendations
  -> smaller-model worker: regeneration helper + regression tests
  -> coordinator checks tests -> independent review -> offline report refresh
  -> browser verification -> handoff note / conventional commit
```

Worker owns only `scripts/regenerate_case_context.py` and
`tests/test_regenerate_case_context.py`. Coordinator owns documentation, Git,
the local server and the ignored saved-report refresh. No agent may call a
provider or launch a Job. Do not merge the outstanding next-steps repair branch.

## Tasks

- [x] TDD: add a legacy single-audit fixture whose step has a saved summary but
  whose case has no groups. Assert report regeneration emits one table per
  family, retains all level counts and phase order, and starts no model calls.
  Observe failure against current helper before adding the fallback.
- [x] Retain coverage that missing summaries in explicit grouped cases keep
  the existing report; add a regression if needed. Run the focused test module
  and existing report-renderer tests with native Python 3.11, never `uv run`.
- [x] Review the narrow change, then dry-run the actual legacy run. Refresh
  only its report/registration if planned model calls are zero; preserve the old
  report recoverably and keep case/evidence identities and outcomes unchanged.
- [x] Verify the local API and browser render F526's new tables and D582's
  existing ones. Update relevant handoff/runbook notes and commit atomically.
- [x] Explain All evidence's synthetic-aggregate warnings and recommend sidebar/
  documentation scope with rough measured source sizes. Do not repair/remove
  All evidence, regroup navigation, add a language run, rewrite Reference/Guide
  or publish a gallery without the project owner's decision.

All implementation above is Green inside the explicitly requested table
consistency change. Larger information-architecture choices remain proposals.
Demo 6 is still in progress, so the previously discussed autonomous batch has
not started. No new GPU/API spend or public redeployment is authorized here.

## Verification and review

- Worker observed the legacy report test fail before adding the fallback;
  coordinator's native Python checks passed: 51 focused/report-renderer tests
  plus 6 subtests, and 84 registration/library tests plus 25 subtests.
- Independent review passed, including the explicit-group missing-summary guard
  tested beside a valid legacy summary. The legacy fixture makes no text calls.
- Actual F526 refresh planned and made zero model/provider calls. Case-file
  and raw-summary hashes stayed unchanged; old reports were backed up locally.
- Real Chromium rendered four per-family level tables on both D582 and F526,
  preserved F526's motion-blur 1/5 row and order, and reported no page errors.
- Evidence API warnings reproduced from six synthetic aggregates; diagnosed
  only. The documentation/sidebar recommendations have not been implemented.
- Public export/deployment and the pending repair-branch integration remain
  outside this follow-up. Do not describe these checks as the complete pending
  integration test run.
