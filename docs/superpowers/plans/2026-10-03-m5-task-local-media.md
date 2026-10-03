# M5 Task-Local Media Compatibility Implementation Plan

> **For agentic workers:** Use subagent-driven-development and TDD. Root alone
> integrates. This is the approved M5 A3 compatibility fix, not an importer or
> new architecture decision.

**Goal:** Resolve real task-filtered screen recordings without attributing a
video or trace to the wrong global robot task.

**Architecture:** Keep global-ID lookup first; permit task-local ordinal zero
only when existing aggregate metadata proves the pinned single-task filter.
Return missing media plus a useful warning for ambiguous or unsafe matches.

**Tech stack:** Existing Python standard library, unittest and viewer catalog.

## Scope and evidence

The October 1 screen aggregates have one task group, benchmark class
`robot_debug.libero:DiagnosticLIBEROBenchmark`, and integer `params.task_id`
1/2 matching every episode's global task ID. The pinned adapter selects exactly
one task, but the harness filenames use ordinal zero. Existing task-0 runs
have no explicit filter and retain normal global-ID lookup.

Owner: Luna builder, only `src/robot_debug/viewer/catalog.py` and
`tests/test_viewer_catalog.py`, in the reused clean linked worktree on
`codex/m5-media-identity`. Baseline focused catalog tests: 9 passed. Root owns
documentation, all Git integration and real-artifact inspection. No cloud,
API calls, artifact mutation or web/frontend edits. No new dependencies.

## Task 1 — Regressions and minimal lookup fix (green)

- [ ] Extend existing tiny `write_episode` fixtures to cover global IDs 1/2
  with local-ordinal-zero media. One failing test must assert the global
  identity stays 1/2 while video and trace resolve to `task0000` files.

```python
# In an ArtifactCatalogTests method, mutate only its synthetic aggregate:
run = write_episode(self.root, "filtered", success=True)
path = run / "libero-object_aggregate.json"
raw = json.loads(path.read_text(encoding="utf-8"))
raw["config"]["params"]["task_id"] = 2
raw["tasks"][0]["episodes"][0]["task_id"] = 2
path.write_text(json.dumps(raw), encoding="utf-8")
episode = ArtifactCatalog(self.root).list_episodes()[0]
self.assertEqual(episode.task_id, 2)
self.assertIn("task0000_ep0000", episode.video_path)
self.assertIn("task0000_ep0000", episode.trace_path)
```

- [ ] Run focused tests and observe the new positive regression fail before
  implementing the fix. Add negative fixtures for absent/bool/mismatched
  filter, a different benchmark class, multiple task groups/mixed episode
  task IDs, duplicate matching media, and escaping media symlinks when the
  platform supports creating them. Missing/ambiguous media must not remove
  an otherwise valid episode from the catalog.
- [ ] Implement a small contained unique-match helper within `catalog.py`.
  Use the two existing candidate directories, inspect regular contained files
  only, deduplicate identical resolved paths. More than one candidate for a
  media kind is ambiguous: warn and return None, never choose sorted first.
  Preserve direct global lookup; do not fall back after global ambiguity.
- [ ] If no global match exists, allow ordinal-zero lookup only for the exact
  benchmark class above, one task group, a non-bool nonnegative integer filter
  matching the requested global task and all episodes in that group. Keep
  episode index unchanged. No heuristic based solely on a lone video or name.
  Resolve video/trace independently; preserve global episode identity,
  deduplication and all existing classifications. Do not parse video contents
  or change reduction semantics. Implement only enough for these tests.
- [ ] Run focused catalog and server tests; preserve the existing suite.
- [ ] Self-review, explicit-path commit:
  `fix(viewer): resolve proven task-local episode media`.

## Task 2 — Independent review and root integration

- [ ] Read-only spec reviewer verifies exact mapping/ambiguity/containment and
  no unsupported single-task guessing; run focused tests independently.
- [ ] Only after spec pass, quality reviewer checks behavior and tests against
  the requirements. Fix actual blocking findings, not speculative refactors.
- [ ] Root cherry-picks reviewed commits, runs fresh full tests and checks
  the three real screen aggregates against their actual media paths. Do not
  modify recordings or alter one-representative-nominal UI filtering.
- [ ] Root records bug and evidence in dev-log/handoff; no provider fault or
  new experimental/HPC result is implied. Push under existing authority and
  verify remote SHA. Keep M3 frozen.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p 'test_viewer_catalog.py' -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p 'test_viewer_server.py' -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -q
git diff --check
```

Expected: new targeted tests pass, existing tests pass with known platform
skips reported. No task starts the viewer, accesses a provider or changes
the user's selected recordings. Stop for a material contract ambiguity.
