# Simplify case navigation and restore a wording example

Approved scope: Jethro requested one archived wording result, challenged type
labels for the unified pipeline, and explicitly requested removing All evidence.
This is a bounded UI correction, not a redesign of Reference or Run your own.

## Ownership and concurrency

- Integration owner: coordinating agent; owns Git, generated bundle, local
  artifacts, documentation, viewer verification and the final review.
- Smaller-model implementer: owns only `web/src/` components/pages and tests.
  No Git integration, external calls or process lifecycle changes.
- Independent reviewer: read-only compliance review, then code-quality review.
- UI implementation runs alongside local archive restoration and a read-only
  investigation of Windows subprocess launches; integration follows both.

## Tasks and acceptance

1. **Green: test-first UI simplification.** Replace sidebar kind groups with a
   single Cases list, preserving item order, names, fault codes and outcomes.
   Flatten the static home gallery consistently and remove card kind badges;
   keep kind data and method-specific context in case details/reports.
   Remove the All evidence link, route and page component. Old `/evidence`
   URLs use Not Found and must not fetch the global evidence API. Preserve
   per-case Full evidence, original artifacts and internal evidence APIs.
   Update affected navigation, route and accessibility tests; show RED/GREEN.
2. **Green: restore one archived result locally.** Copy (do not move/delete)
   `artifacts/archive-2026-10-19/runs/ui-paraphrase-spatial-20261017T015821Z`
   into `artifacts/runs/`, only if absent. Verify report/steps hashes and the
   library entry. Present FL-L-C72C honestly: four passing rewordings, no
   reproduced failure and no reduction. Do not invoke diagnose or replay.
3. **Green: explain console flashes.** Trace short-lived CLI subprocesses and
   polling separately from the detached diagnosis owner. No lifecycle/flag
   changes or paid reproduction in this step.
4. **Green: integrate and verify.** Review compliance, then quality; run the
   complete web suite, type check and bundle build. Browser-check mixed cases,
   restored wording result, removed route and retained per-case evidence.
   Update runbook/current-state and affected architecture references.

## Commit boundaries and gates

- `docs: plan simplified case navigation` (this plan).
- `refactor(ui): unify case navigation and remove global evidence page`
  (checked source/tests and generated bundle).
- `docs: record restored wording demo and navigation changes` (handoff/docs).

No new GPU/Token Factory/Tavily calls, public deployment, archive deletion,
Reference/Guide rewrite, cloud provisioning or pending next-steps repair merge.
Broader post-Demo-6 integration remains waiting for Jethro's completion signal.
The public gallery is unchanged until its separately gated redeployment.

## Inspection addendum: honest restored report limitations

Browser inspection exposed old unconditional wording-report limitations:
they say the listed wordings caused failures and a minimal wording was found,
even for a screen with all passing attempts. Correct only those limitations
in `scripts/report_paraphrase.py`, test both screen-only and verified-reduction
reports in `tests/test_paraphrase_pipeline.py`, then regenerate the restored
local report from its saved summary with this pure formatter. Keep the original
archive report and raw summary unchanged. No new model or robot test.
Smaller-model worker owns these two files, independent reviewer checks the
conditional claims, and root handles local regeneration and Git. Separate
commit: `fix(reports): bound wording claims to recorded evidence`.

## Verification outcome

Completed locally: navigation and report fixes had failing regression tests
before implementation, then 334 web tests and 163 relevant Python tests
(105 subtests) passed. Production build/type check and committed-bundle
freshness passed. Independent specification and code-quality reviews passed.
Browser checks confirmed the five-case list, restored wording outcomes, removed
route without evidence API fetch, and retained D582/F526 per-family tables.
Report regeneration used only saved data; no paid call or public deploy.
