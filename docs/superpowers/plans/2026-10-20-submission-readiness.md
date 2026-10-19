# Submission readiness implementation plan

> **For agentic workers:** Use parallel audit tasks with independent file
> ownership, then coordinator review. Do not launch experiments or publish.

**Goal:** Give Jethro an evidence-backed judge-access audit and submission
drafts, leaving billing confirmation, personal feedback and final publication
as explicit human gates.

**Architecture:** Preserve the installed application and read-only public
gallery. Audit a clean source snapshot in an isolated temporary directory;
keep test environments, raw scan output and provider details uncommitted.
Documentation is the deliverable, not a new execution or hosting system.

**Tech stack:** Python 3.11, pip/venv, existing unittest suite and packaged
viewer, Git/GitHub read-only checks, official Devpost rules.

## Authority and exclusions

Jethro approved proceeding with the submission-readiness sequence on October
20. Green: local tests, tracked-file inspection, evidence synthesis and draft
documentation. Amber: wording corrections that narrow unsupported claims.
Red: new costs, model calls, public deployment, changing repository visibility,
submission, personal attestations and choosing a response to ambiguous rules.
No new GPU, Token Factory, Tavily or hosting expenditure is authorized.

Work on `codex/submission-readiness`; do not merge or redeploy merely because
drafts exist. The coordinator alone owns Git integration and external access.
Smaller implementation agents use Luna when Terra is unavailable; the active
coordinator's model is not changed.

## Dependency and ownership map

```text
committed plan
  +-- install auditor: isolated snapshot/install/smoke -> clean-checkout.md
  +-- evidence writer: committed results/feedback -> submission draft
  +-- coordinator: live rules + repo hygiene + CI -> audit + checklist
             all three -> independent review -> corrections -> handoff
```

Agents must not edit shared files, commit, publish, inspect credentials or
mutate cloud resources. Shared docs, README changes and Git remain coordinator
owned. A reviewer is read-only and checks acceptance criteria, not authorship.

## Task 1: Clean-checkout audit (Green, install auditor)

**Own:** `docs/submission/clean-checkout.md` only.

- [x] Use `git archive HEAD` into a fresh temporary directory. Record source
  SHA and distinguish a clean local snapshot from an actual fresh machine.
- [x] Create a new Python 3.11 venv without system site packages. Install
  `.[cli,cloud]` from the snapshot, not the existing editable environment.
- [x] From outside the source directory, check `faultline --help`, packaged
  viewer assets and installed imports; serve the snapshot's `demo/root` on
  an unused loopback port and check health, case data and video bytes.
- [x] Run the README's unittest command in the snapshot. Save lengthy raw
  output only in ignored/local paths; record counts, skips and limitations.
- [x] Do not build/push the 20 GB GPU image, sign in or run cloud diagnostics.
  Missing optional tooling or network access is a bounded limitation, not a
  reason to claim an untested paid path works.
- [x] Write exact portable commands, observations and actionable defects.

## Task 2: Evidence-grounded submission draft (Green, evidence writer)

**Own:** `docs/submission/devpost-draft.md` only.

- [x] Read README, FEEDBACK, final-showcase, workflow-evidence and relevant
  ADR/experiment records. Cite repository-relative evidence next to numbers.
- [x] Draft tagline, problem/audience, solution, implementation, demonstrated
  results, limitations, challenges, learning, next steps and Built With.
- [x] Explain genuine GR00T/Serverless and Nemotron/Token Factory roles,
  optional Tavily research and human-reviewed model suggestions.
- [x] State budget-local reduction, not global minimality, causal proof,
  universal compatibility or demonstrated end-to-end cost savings.
- [x] Identify four supported suites versus actual task/start coverage.
  Separate public recorded gallery from runnable installed control panel.
- [x] No invented personal experience, costs, users or novel-research claim.
  Mark draft for human approval; do not update Devpost.

## Task 3: Rules, repository and cost-readiness review (Green/Amber, coordinator)

**Own:** `docs/submission/readiness-audit.md`, `docs/submission/README.md`,
`docs/submission/video-plan.md`, README claim corrections if needed, and
existing handoff/index/roadmap updates.

- [x] Read the current official rules/overview. Link primary sources and
  record deadline, hardware-free Physical AI wording, required artifacts,
  tool feedback, video constraints and judging access duration. Avoid
  unnecessary quotations; source-derived summary must remain concise.
- [x] Verify repository visibility/license and latest CI with GitHub CLI.
  Never change visibility. Inspect tracked files, snapshot link targets,
  known secret patterns and user-specific paths; do not print secret values.
  Distinguish current tree, reachable history and provider-side scanning.
- [x] Inspect existing cost records and list reconciliation inputs without
  adding overlapping experiment/session totals together. Do not claim billed
  totals or trigger authentication just to avoid requesting billing figures.
- [x] Write a timed sub-three-minute pitch outline using existing cases,
  at least one minute of modules operating, explicit spoken required-tool
  attribution and clearly labeled saved evidence. No fabricated live runs.
- [x] Record the smallest human-input checklist: billing totals/periods,
  feedback confirmation, narration/video choice, publication/submission go.

## Task 4: Review and verification (Green, reviewer then coordinator)

- [x] Independent reviewer checks draft/evidence agreement, install scope,
  secret-handling boundaries, source links and remaining human gates.
- [x] Correct substantive findings before declaring readiness. Routine
  documentation fixes stay in this step; code fixes require reproduction,
  tests and proportionate review rather than opportunistic refactoring.
- [x] Verify changed-document links and `git diff --check`. For code changes,
  run the affected tests and maintain red/green evidence.
- [x] Make atomic commits: plan; audit evidence; submission drafts; handoff.
  Stage exact paths only. Check `gh auth status` before an authorized push;
  never publish draft submission contents externally without review.
- [x] Update STATE and PROJECT_PLAN with verified results, real limitations
  and next human action. Report what is ready versus what remains untested.

## Acceptance

A new session can find the audit and draft from the stable handoff. Installation
claims name the tested environment and source SHA; the free demo is usable
without credentials. No new cloud/model charge, visibility change, redeployment
or Devpost/YouTube submission occurs. Final readiness remains conditional on
the explicit human gates, not merely passing unit tests.

## Execution checkpoint — October 20

All audit and drafting tasks above completed; independent spec and quality
reviews passed. Luna handled installation evidence and the story draft, with
coordinator-owned checks/integration and independent Sol reviews. Routine
corrections stayed within the accepted scope. No application code was changed.

Additional user request: condense root FEEDBACK, keep the table/first-hand
notes and link the chronology. It is now about 870 words (from 4,596); the
original body is preserved in `docs/experiments/tool-feedback-history.md`.
A supplied consumption screenshot is recorded, not fully reconciled, in
`docs/submission/billing-reconciliation.md`. No private screenshot was committed.

Clean snapshot: 3,166 unittest tests run, 63 skipped, exit 0. Existing web
environment: 336 tests and typecheck passed. Snapshot installation and offline
case/video HTTP checks passed. Remaining human gates are listed in the
submission package: billing scope, first-hand confirmation, story/narration,
actual video/cover, rights/eligibility, judge access and final publication.
The audit branch is kept local; this checkpoint does not approve a push,
merge, deployment, paid run or submission.
