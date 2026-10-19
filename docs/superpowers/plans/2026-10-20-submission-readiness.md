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

- [ ] Use `git archive HEAD` into a fresh temporary directory. Record source
  SHA and distinguish a clean local snapshot from an actual fresh machine.
- [ ] Create a new Python 3.11 venv without system site packages. Install
  `.[cli,cloud]` from the snapshot, not the existing editable environment.
- [ ] From outside the source directory, check `faultline --help`, packaged
  viewer assets and installed imports; serve the snapshot's `demo/root` on
  an unused loopback port and check health, case data and video bytes.
- [ ] Run the README's unittest command in the snapshot. Save lengthy raw
  output only in ignored/local paths; record counts, skips and limitations.
- [ ] Do not build/push the 20 GB GPU image, sign in or run cloud diagnostics.
  Missing optional tooling or network access is a bounded limitation, not a
  reason to claim an untested paid path works.
- [ ] Write exact portable commands, observations and actionable defects.

## Task 2: Evidence-grounded submission draft (Green, evidence writer)

**Own:** `docs/submission/devpost-draft.md` only.

- [ ] Read README, FEEDBACK, final-showcase, workflow-evidence and relevant
  ADR/experiment records. Cite repository-relative evidence next to numbers.
- [ ] Draft tagline, problem/audience, solution, implementation, demonstrated
  results, limitations, challenges, learning, next steps and Built With.
- [ ] Explain genuine GR00T/Serverless and Nemotron/Token Factory roles,
  optional Tavily research and human-reviewed model suggestions.
- [ ] State budget-local reduction, not global minimality, causal proof,
  universal compatibility or demonstrated end-to-end cost savings.
- [ ] Identify four supported suites versus actual task/start coverage.
  Separate public recorded gallery from runnable installed control panel.
- [ ] No invented personal experience, costs, users or novel-research claim.
  Mark draft for human approval; do not update Devpost.

## Task 3: Rules, repository and cost-readiness review (Green/Amber, coordinator)

**Own:** `docs/submission/readiness-audit.md`, `docs/submission/README.md`,
`docs/submission/video-plan.md`, README claim corrections if needed, and
existing handoff/index/roadmap updates.

- [ ] Read the current official rules/overview. Link primary sources and
  record deadline, hardware-free Physical AI wording, required artifacts,
  tool feedback, video constraints and judging access duration. Avoid
  unnecessary quotations; source-derived summary must remain concise.
- [ ] Verify repository visibility/license and latest CI with GitHub CLI.
  Never change visibility. Inspect tracked files, snapshot link targets,
  known secret patterns and user-specific paths; do not print secret values.
  Distinguish current tree, reachable history and provider-side scanning.
- [ ] Inspect existing cost records and list reconciliation inputs without
  adding overlapping experiment/session totals together. Do not claim billed
  totals or trigger authentication just to avoid requesting billing figures.
- [ ] Write a timed sub-three-minute pitch outline using existing cases,
  at least one minute of modules operating, explicit spoken required-tool
  attribution and clearly labeled saved evidence. No fabricated live runs.
- [ ] Record the smallest human-input checklist: billing totals/periods,
  feedback confirmation, narration/video choice, publication/submission go.

## Task 4: Review and verification (Green, reviewer then coordinator)

- [ ] Independent reviewer checks draft/evidence agreement, install scope,
  secret-handling boundaries, source links and remaining human gates.
- [ ] Correct substantive findings before declaring readiness. Routine
  documentation fixes stay in this step; code fixes require reproduction,
  tests and proportionate review rather than opportunistic refactoring.
- [ ] Verify changed-document links and `git diff --check`. For code changes,
  run the affected tests and maintain red/green evidence.
- [ ] Make atomic commits: plan; audit evidence; submission drafts; handoff.
  Stage exact paths only. Check `gh auth status` before an authorized push;
  never publish draft submission contents externally without review.
- [ ] Update STATE and PROJECT_PLAN with verified results, real limitations
  and next human action. Report what is ready versus what remains untested.

## Acceptance

A new session can find the audit and draft from the stable handoff. Installation
claims name the tested environment and source SHA; the free demo is usable
without credentials. No new cloud/model charge, visibility change, redeployment
or Devpost/YouTube submission occurs. Final readiness remains conditional on
the explicit human gates, not merely passing unit tests.
