# Final cleanup batch implementation plan

> **For agentic workers:** use executing-plans. Jethro explicitly requested
> inline execution in one pass, overriding the usual smaller-agent handoff.

**Goal:** finish the post-walkthrough integration, quiet background commands,
and make the product documentation usable without another feature milestone.

**Architecture:** preserve the detached diagnosis owner, its ledger, Stop and
Resume; only short captured CLI subprocesses become windowless on Windows.
Reference defines evidence; Run your own covers setup/operation and links to
the quickstart for lengthy infrastructure commands. Neither duplicates demos.

**Tech stack:** Python 3.11, unittest/pytest, React/TypeScript, Vite/Vitest,
local Playwright checks, existing bounded Token Factory formatter pipeline.

## Ownership, autonomy and gates

One inline execution/integration owner for all files, Git, viewer and external
calls; no concurrent agents or overlapping edits. Tasks run sequentially, with
independent concerns reviewed separately before final integration.

- Green: merge accepted repair code, tests, copy/docs, local exports, offline
  demo refresh, bundle build, Git integration/push explicitly in this batch.
- Amber: quiet captured CLI launch flags and one D582 next-steps refresh using
  stored facts/sources. Inspect the payload/call budget first. Preserve previous
  accepted interpretation if validation fails; never manufacture acceptance.
- Red: no GPU runs, simulator/model/algorithm changes, new cloud provisioning,
  broad data deletion, new Tavily searches, or production gallery redeploy.
  Prepare a privacy-filtered export for review, do not publish it.

## Execution checklist and commit boundaries

### 1. Accepted next-steps repair integration

- [ ] Merge `worktree-agent-aff20f6737887e095` into the current feature branch.
  Preserve the newer legacy-audit fallback in `scripts/regenerate_case_context.py`.
- [ ] Run `PYTHONPATH=src python -B -m pytest tests/test_next_steps.py
  tests/test_token_factory.py tests/test_regenerate_case_context.py -q`.
  Existing repair tests must exercise one retry only and fail-closed behavior.
- [ ] Review diff for request bounds, secret handling and summed provenance.

### 2. Hide routine Windows command windows (test first)

- [ ] Add tests for `robot_debug.backends.run_command`: Windows uses
  `subprocess.CREATE_NO_WINDOW` (fallback numeric value 0x08000000), other
  platforms omit Windows flags; capture, timeout and exit behavior unchanged.
  Assert timeout still propagates. Run failing tests before implementation.
- [ ] Set only the captured runner's `creationflags` on Windows. Do not change
  viewer `DETACHED_PROCESS`, process groups, breakaway handling, Stop, watchdog
  or interactive terminal commands. Setup and Nebius calls share this runner.
- [ ] Run runner, backend, viewer environment/launcher/process tests; exercise
  an innocuous local subprocess on Windows, never a paid Job.
- [ ] Commit `fix(windows): hide captured background command windows`.

### 3. Product copy and document rewrite

- [ ] Apply approved copy items 51/52/54 in
  `web/src/components/case/TeamSections.tsx`: shortened trust hints, "Ranked
  by Nemotron before any rerun.", remove redundant full-reading disclaimer.
- [ ] Write failing content tests in `web/src/pages/pages.test.tsx` for the
  revised reference/guide roles and preserved links/safety information.
- [ ] Rewrite `docs/reference.md` around scope, terms/gates, layout reduction,
  probe formulas, report columns, statuses, replay, spending/claim boundaries.
  Preserve severity formulas and the nonmonotonic basket example; remove
  setup commands, repeated pitch/walkthroughs and duplicated estimates.
- [ ] Rewrite `web/src/content/guide.tsx` as a short operational path: offline
  preview, prerequisites, model access, image, spec, dry run/start, recovery and
  replay. Preserve setup anchors (`prerequisites`, `huggingface`, `image`,
  `spec`, `run`, `resume`, `view`) and links to quickstart/runbook/reference.
- [ ] Bring `docs/setup/diagnose.md` in line with one diagnosis pipeline and
  implemented replay types; never promise arbitrary checkpoint compatibility
  or an all-services spending guarantee. No secrets or personal paths.
- [ ] Run web tests/typecheck/build; commit source and generated bundle as
  `docs(ui): streamline reference and operating guide`.

### 4. D582 interpretation refresh

- [ ] Dry-run the existing regeneration helper against the D582 run, inspect
  exact payload, model/call ceiling and cached sources; no Tavily/GPU call.
- [ ] Refresh next steps only, not already accepted scenario explanations.
  Use the existing repaired request path; maximum two bounded POSTs. Keep
  returned invalid prose out of accepted records and preserve prior sidecar.
- [ ] Verify case ID and raw outcome hashes unchanged, record acceptance or
  honest rejection and actual attempt/token provenance in the handoff/feedback.
  Stop this task if its budget or credentials are unavailable; complete all
  remaining local tasks and report the precise gate.

### 5. Full verification, offline demo and gallery preparation

- [ ] Refresh `demo/root` from FL-S-8E0D with allowlisted reviewed files.
  Exclude research snippets/provider identities/secrets; keep metadata coherent.
- [ ] Update `docs/ui-runbook.md`, `docs/codex-handoff/STATE.md`, relevant
  architecture/operator notes and `FEEDBACK.md` with observed project defects.
  Walkthrough is finished; remove stale "waiting for Demo 6" gates.
- [ ] Run full Python suite and full web suite/typecheck/build; verify rebuilt
  committed bundle is fresh. Browser-check Home, both docs, three showcase
  cases, restored wording case, dry-run review and retained evidence tables.
  Never press Start or Run the test during QA.
- [ ] Export only the three approved showcase cases into a new local gallery
  folder; scan the output and preview locally without production deployment.
- [ ] Integrate checked feature branch into main without rewriting history;
  verify `gh auth status` resolves to jephoton, push, inspect CI outcome.
- [ ] Commit handoff/verification results. Stop before billing reconciliation,
  first-hand feedback, submission audit/rules check, video/write-up/submission.

Completion means each item has evidence or an explicit external gate, not that
an invalid model answer was accepted or an unapproved deployment occurred.
