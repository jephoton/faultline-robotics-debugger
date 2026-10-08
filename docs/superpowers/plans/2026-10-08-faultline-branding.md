# Faultline Branding Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the isolated
> viewer/metadata task. Root owns documentation, integration and local viewer
> verification. All changes implement Jethro's explicit naming/scope request.

**Goal:** Name the product Faultline without breaking replay or existing commands.

**Architecture:** Presentation/metadata rename only; preserve `robot_debug`
imports, schema identifiers, artifacts and external resource identities.
**Tech Stack:** Existing Python standard-library viewer, setuptools metadata,
Markdown; no new dependencies or cloud work.

## Ownership and concurrency

Root: README.md, PROJECT_PLAN.md, PROJECT-LEARNING-GUIDE.md, AGENTS.md,
docs/codex-handoff/PROJECT.md and STATE.md, ADR 0011, ADR 0019, this plan,
current naming statements in docs/research/2026-10-06-submission-alignment.md,
and corresponding startup roadmap. Historical plan examples may receive
presentation-name updates or explicit supersession notes, not path rewriting.

Smaller-model builder: pyproject.toml, src/robot_debug/viewer/web/index.html,
src/robot_debug/viewer/server.py and __init__.py, tests/test_viewer_server.py,
tests/test_faultline_branding.py. Use an existing clean attached worktree on a
new codex/faultline-branding branch. No Git integration or external mutation.

Dependency map: root docs || isolated builder -> spec review -> quality review
-> root cherry-pick -> focused tests, reference audit, HTTP checks -> commit.

## Task 1 — viewer and package branding (green)

- [ ] Run existing viewer tests before editing.
- [ ] Add a failing HTTP test requiring `<title>Faultline</title>` and
  `<h1>Faultline</h1>` in the homepage; assert old `Robot Debug Console` is absent.
- [ ] Add metadata tests requiring `name = "faultline"`,
  `faultline-viewer = "robot_debug.viewer.server:main"`, and the preserved
  `robot-debug-viewer` alias. Read pyproject.toml directly; no package publishing.
- [ ] Run the new tests and observe branding failures before implementation.
- [ ] Replace title/h1 and startup banner (`Faultline Viewer: http://...`),
  update viewer module descriptions, distribution name and new console alias.
  Preserve all APIs, DOM IDs, layouts, import names and artifact contracts.
- [ ] Run `C:/Windows/py.exe -3.11 -m unittest tests.test_faultline_branding
  tests.test_viewer_server -q` with PYTHONPATH=src, then `git diff --check`.
- [ ] Commit only owned files as `chore(branding): name viewer and package Faultline`.

## Task 2 — docs and scope (green; naming already decided)

- [ ] Update current product titles/branding and provisional-name statements.
- [ ] Mark all additional HPC work as optional stretch; preserve measured M3
  evidence and explicitly record the preference for a separate HPC project.
- [ ] Synchronize root/detailed milestone sections and persistent handoff.
- [ ] Scan tracked references; keep actual folder/repository names, historical
  VM names, import paths and compatibility command examples intact. Mark old
  pending-name statements as superseded by ADR 0019.
- [ ] Commit explicit documentation paths with a Conventional Commit.

## Task 3 — review and integration (root)

- [ ] Independent spec review: exact new branding, compatibility alias,
  unchanged behavior and no out-of-scope rename/provider operation.
- [ ] Independent quality review after spec approval: regression tests and
  packaging compatibility; root alone integrates reviewed code.
- [ ] Run focused tests and full suite as proportionate regression checks;
  verify homepage branding and `/api/health` against the local viewer.
- [ ] Report committed versus pushed accurately. Advise on GitHub/local-folder
  renames without performing either. No new spending or publication approved.
