# M7a Step 5: Public Gallery Implementation Plan

> **For agentic workers:** Use subagent-driven development for the bounded documentation task and independent export review. The coordinator alone owns Git integration and Vercel publication.

**Goal:** Repair the project handoff, then publish the existing, privacy-filtered static Faultline gallery and verify it as an unauthenticated visitor.

**Architecture:** Reuse `faultline export` and the committed React bundle. Deploy only a fresh ignored export directory, never the repository or live control panel. Vercel serves static JSON, media and application routes; there is no Python backend, provider credential, GPU, live inference or public run control.

**Tech stack:** Existing Python CLI/exporter, React/Vite bundle, Vercel CLI and browser QA.

## Authorization and boundaries

Jethro's October 17 instruction, "update the handoff docs properly first, then carry on with m7a step 5", authorizes the static gallery publication described in ADRs 0027 and 0033. It does not authorize a paid hosting upgrade, new Nebius/Token Factory/Tavily calls, a public image, repository visibility changes, or a custom domain purchase. Use the authenticated Vercel account if unambiguous; request sign-in if unavailable. Do not work around certificate checks or print credentials.

## Ownership and dependency map

| Owner | Files/output | Boundary |
| --- | --- | --- |
| Smaller documentation agent | `docs/codex-handoff/PROJECT.md`, `RUNBOOK.md` | Approved-state refresh only; no Git/cloud mutations |
| Coordinator | `STATE.md`, `PROJECT_PLAN.md`, this plan, deployment note and later public URL links | Sole commit/push/deployment owner |
| Independent reviewer | Read-only exporter/public output review | No publication, provider calls or source edits |

Handoff refresh/review/commit → export generation → export review ∥ authenticated hosting preflight → static deployment → visitor/browser checks → evidence and handoff update/commit/push. Do not publish until the handoff refresh and privacy review are complete.

## Task 1 — Restore a reliable handoff (green)

- [x] Rewrite `PROJECT.md` as a concise current architecture map: two product modes, CLI/orchestrator/backends, current React control panel, static export, four LIBERO suites, Nemotron per-task roles, Tavily boundaries, replay limitations and local GPU validation boundary. Remove obsolete claims that M5 or Serverless are unaccepted.
- [x] Replace the M3-centric `RUNBOOK.md` with portable installation, test, UI, dry-run, diagnosis, stop/resume, replay, export and recovery commands. Link historical VM experiment notes rather than presenting them as current setup. Record historical test counts as dated evidence, not permanent expected totals. Never write user-specific paths.
- [x] Put a concise authoritative current snapshot at the top of `STATE.md`. Preserve older entries in `STATE-history-through-2026-10-17.md` under an explicit historical/superseded heading. Identify the completed live panel check, estimated/unreconciled costs, current step 5 authorization and no-new-paid-run boundary. Update the roadmap's current status date and publication gate.
- [x] Validate CLI help, relative documentation links and `git diff --check`; independently review factual consistency against ADRs 0027–0033 and the latest experiment notes. Commit explicit paths as `docs(handoff): synchronize current product and operations`.

## Task 2 — Prepare and inspect the exact public payload (green/amber)

- [ ] Run `PYTHONPATH=src python -B -m robot_debug.cli export --help`, then export into a new ignored directory under `artifacts/` without `--force`. Preserve all source evidence and earlier exports.
- [ ] Run the existing exporter/library test modules identified in `tests/`; inspect the generated session, library, case details, reports, media references and deployment configuration. Require `mode: static`, `controls: false`, `token: null`, no private ids/paths/specs/logs/credentials and no omitted cases or missing required videos without disclosure.
- [ ] Have the independent reviewer inspect both the export guard and generated payload. No uploading the repository, `.env`, raw run folders or source maps containing private data. Stop publication for an actual privacy finding; make any required code repair test-first within a separately explicit scope.
- [ ] Record export counts, sizes and checks in `docs/experiments/m7-public-gallery.md` using only public-safe evidence. Preserve model explanations as interpretations and research as context, never verified causal claims.

## Task 3 — Publish static files only (amber within accepted design)

- [ ] Read official Vercel deployment/configuration documentation and installed CLI help. Check CLI identity and relevant existing projects without printing authentication material. Use a clearly named Faultline gallery project; do not overwrite an unrelated deployment or upgrade a plan.
- [ ] Verify the existing export's SPA rewrite preserves `/assets/`, `/data/` and `/media/`. Apply static-only settings in the export/project when needed; no API functions or secret environment variables. Review the exact deployment directory before invoking `vercel`.
- [ ] Deploy the inspected directory to Vercel production with the CLI. User-facing access must work without a Vercel login. Do not treat a protected preview or a successful upload as a usable public gallery.

## Task 4 — Visitor acceptance and durable completion (green)

- [ ] Fetch home, session, library, each case JSON and referenced assets/media; verify HTTPS, content types, SPA direct links and media retrieval. Check that public pages have no start/stop/resume/replay control surface and cannot call a provider.
- [ ] Browser QA: home → representative scenario case → video evidence/report → another case kind → refresh a deep link. Check narrow-screen layout and console/network errors. Report verification limitations honestly; never substitute HTTP success for a rendered-page check.
- [ ] Update the deployment note, README/roadmap and the top handoff snapshot with the stable public URL, exact evidence scope, regeneration/deployment commands and current limitations. Mark M7a complete only if its acceptance checks pass; M7b remains submission/video/write-up work.
- [ ] Commit publication documentation separately (`docs(m7): record public gallery deployment`), check GitHub identity before pushing, then verify CI for the exact pushed commit. No history rewrite, repository visibility change or paid experiments.
