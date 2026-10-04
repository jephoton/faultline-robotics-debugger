# M5A Read-Only Case Journey Implementation Plan

> **For agentic workers:** Use subagent-driven-development/TDD, after reviewed
> case-I/O integration. Root integrates, starts the viewer and performs visual QA.

**Goal:** Present case readiness, saved failure/reduction evidence and the
regression recipe in the existing viewer as one coherent operator workflow.

**Architecture:** Extend existing GET-only server with case services and a
compact case panel. Reuse paired video/trace UI, without uploads, execution,
provider calls or portfolio dashboard. Case selection scopes evidence but does
not assume that every case is confirmed or replay-ready.

**Tech Stack:** Existing vanilla HTML/CSS/JavaScript, Python HTTP server/unittest.

**Completed October 4:** Integrated as `01c8ea2`, `557c00b`, and `2e2e125` after
independent spec then quality review. Root checked real M4 case registration,
22/22 exact episode links, paired playback, traces, lineage, missing pins,
keyboard/refresh stability and 375/768/1440px layouts. Full suite: 468 tests,
four platform skips; Node syntax and diff checks pass. Operator documentation:
`docs/setup/case-workbench.md`. The legacy source cannot support a safe fallback
for missing IDs, so unsupported IDs remain explicitly unlinked; no guessed
mapping was added. Reduction stop reason absent from retained case metadata is
disclosed rather than invented. M5B/C remain gated separately.

## Scope and ownership

Accepted M5A contract and CLI-first decision; green/amber presentation within
the existing dark industrial console aesthetic. Preserve equal video panels,
one representative nominal default, keyboard navigation, linked playback and
range-streaming containment. No dependencies or cloud/model/browser-write API.

Balanced smaller builder owns only `src/robot_debug/viewer/server.py`,
`src/robot_debug/viewer/web/index.html`, `app.js`, `styles.css` in that same
web directory, `tests/test_viewer_server.py` and a new
`tests/test_viewer_cases.py` if needed. Root owns walkthrough/research/handoff,
real case setup, Git integration and browser QA. No overlapping builders.

Dependencies: schema -> reviewed case-I/O/store -> this viewer -> independent
spec review -> quality review -> root full tests/visual acceptance. B/C research
can proceed independently; no unapproved provider or simulator execution.

## Task 1 — Safe read-only case API

- [x] Extend `make_handler(catalog, web_root, case_workspace=None)` and
  `create_server(artifact_root, host='127.0.0.1', port=8765, case_workspace=None)`
  compatibly; add CLI `--cases` for an explicitly selected local workspace.
  When omitted, case workspace is `artifact_root / 'cases'`. Legacy viewer works
  without registrations. Case state refresh never writes/imports/exports files.
- [x] Add failing HTTP fixtures using actual case services:

```python
response = self.get('/api/cases')
self.assertEqual(response.status, 200)
self.assertNotIn('local-source', response.body.decode())
self.assertNotIn(str(self.source_root), response.body.decode())
```

- [x] GET `/api/cases` returns `{cases: [...], warnings: [...]}`;
  GET `/api/cases/<64-lowercase-hex-id>` returns `{case: ...}`;
  GET `/api/cases/<id>/recipe` returns safe structured replay inputs if complete,
  or `{recipe: null, missing: [...]}` when incomplete. No copied commands,
  absolute source binding or private config in payloads. Validate IDs before
  path joining. Invalid/unknown IDs are controlled 400/404; missing workspace
  returns an empty collection; corrupt case is an unavailable record, not a
  server-wide error. POST/import/export/run routes remain unsupported.
- [x] Test complete/incomplete, missing source, tampered core/hash, conflicting
  metadata, corrupt registrations, path-escape IDs and read-only source/workspace
  hashes. Preserve all existing range/media/episode API tests. Commit
  `feat(viewer): expose read-only case readiness and recipe APIs`.

## Task 2 — Case-to-regression presentation

- [x] Add a compact `#case-workbench` section above existing evidence. Semantic
  label/select `#case-select`, `#case-status` live region, four independent
  capability labels with explanatory captions, missing prerequisites,
  measured counts/times with source-reported provenance, and `#case-recipe`.
  Do not add a card dashboard or imply a linear completed diagnosis for every
  import. Preserve existing CSS tokens/industrial hierarchy.
- [x] Load cases with catalog refresh. Failures in case API must not erase
  available legacy episode evidence. Default first valid case when available;
  an explicit All saved evidence selection preserves original workflow.
  On case selection show only matched case episode IDs; for root-relative
  fallback IDs without eval_id use validated task/reset/stage matches only,
  no arbitrary single-video guessing. Missing links show honest unavailable
  evidence messages, not the previous unrelated episode.
- [x] Show journey labels: inspect -> understand saved evidence -> export a
  regression recipe. Distinguish saved parent/reduced evidence from current
  readiness. Show stop reason/unfinished reduction where available; never
  label a budget-local reduced mask a globally minimal counterexample.
- [x] Show export/replay information as read-only data. Provide a static trusted
  CLI template with validated case ID for local export; never execute it, copy
  untrusted source shell strings, or imply GET downloaded/created an archive.
  An incomplete case still supports metadata export and explains absent pins.
- [x] Render all imported strings with textContent, not innerHTML. Keep focus
  and playback stable during periodic refresh. Cache signatures so polling does
  not rebuild controls/erase selected case or scroll position unnecessarily.
  Empty state gives exact CLI-first next step, not a dead import button.
- [x] Test DOM/assets and API integration through fixtures. If Node available,
  use `node --check .../app.js`; otherwise report limitation. Commit
  `feat(viewer): present saved case-to-regression workflow`.

## Task 3 — Review and real offline acceptance

- [x] Independent spec then quality/security reviews. Root integrates and runs
  full unittest and diff checks. No live robot run is required for UI acceptance.
- [x] Root uses ignored local case workspace for actual saved M4 sources and
  starts/restarts only the owned viewer process. Validate complete fixture and
  real incomplete case, nominal/parent/reduced comparisons, equal video sizes,
  trace/lineage, correct missing-pin labels and no disabled unexplained actions.
  Preserve original artifacts and test hashes before/after registration/export.
- [x] Root writes `docs/setup/case-workbench.md` with fresh-operator commands,
  import/readiness/inspection/export/reimport and limitations. Update README,
  main plan/handoff/dev-log and feedback only for observed tool interactions.
  M5A can be complete while M5B/C remain pending their explicit red gates.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p 'test_viewer*.py' -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -q
git diff --check
```

No browser upload, GPU start, external reset adapter or Nemotron call is
authorized by this implementation plan. No fabricated report demonstrates C.
