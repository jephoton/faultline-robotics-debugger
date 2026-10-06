# M5B External Reset Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development
> and test-driven-development. Steps use checkbox syntax for tracking.

**Goal:** Build locally testable, sample-specific XML/state restoration helpers
without presenting saved demonstration playback as a fresh policy evaluation.

**Architecture:** One optional-HDF5 kernel validates source/state identity,
resolves installed asset closure and performs ten-step settled restoration.
Existing evaluators/cases remain unchanged until the kernel is independently
reviewed and actual runtime wiring receives its next committed plan.

**Tech stack:** Python3.11 standard library/NumPy, unittest/fake simulator;
isolated research h5py only for actual-sample read acceptance.

## Verified execution checkpoint — October 6

This checkpoint supersedes historical unchecked implementation steps below.

- [x] Tasks1–3 kernel, adversarial regression tests and restoration-order fixtures.
- [x] Task4 independent spec/quality reviews and root integration through
  `8b2dae3`; fresh main suite578OK/four platform skips, node syntax and diff check.
- [x] Actual HDF5 reader acceptance:110state values, fixed source/state hashes,
  all81XML asset references normalize. Actual installed assets remain unverified.
- [x] Handoff/roadmap publication; `b1b4a30` CI successful.
- [ ] Next evaluator/case-identity wiring plan and actual runtime validation.

Production state validation remains exact; synthetic tests change the expected
state constant, never mock the public state hashing function. M5B is not complete;
no paid GPU start or external-reset case-schema change is approved here.

## Ownership, autonomy and dependency map

Root owns plan/spec/docs, Git integration and read-only actual-sample checks.
One balanced smaller builder owns only src/robot_debug/external_reset.py and
tests/test_external_reset.py in a clean attached isolated worktree. Independent
spec then quality reviewers are read-only. This can run independently of the
M5C client/store; no shared file ownership or external-state execution.

```text
accepted ADR0016 -> committed exact kernel contract -> red tests -> kernel
 -> focused tests/commit -> independent spec review -> quality review
 -> root integration/full suite -> actual HDF5 reader acceptance
 -> next runtime/case wiring plan -> fresh live preflight/cap gate
```

Green: validators/tests/local reads. Amber: helpers and explicit source alias
mapping within contract. Red: additional tasks/sample/reset/controller/model,
runtime compatibility claims, cloud start/spend, dataset publication.

Exact field/size/path/restore contract is
`../specs/2026-10-05-m5-external-reset-kernel-design.md`. No flexible generic
importer, dependency upgrades or case-schema changes.

## Task1: Candidate validator and source reader

Files: create src/robot_debug/external_reset.py; tests/test_external_reset.py.

- [ ] Write failing validator fixture tests with canonical110float state,
  fixed sample identity and bounded XML. Use an internal mocked state digest
  only in reader-specific synthetic fixtures; public validator must always
  enforce the actual accepted state hash. Add malformed types/nonfinite,
  forged source/state/XML/reset hashes, cycles and oversized text tests.
- [ ] Run focused unittest and verify failure is missing API, not discovery.
- [ ] Implement exact public APIs/error class and canonical finite detached
  validation; reject unknown fields, Boolean numeric disguises and XML hazards.
  Implement lazy-h5py hard-link/read-one-row path with before/after identity
  checks and exact source hash/size. No image/action reads or arbitrary paths.
- [ ] Inject fake HDF5 objects whose image/actions throw if accessed. Verify
  external/soft/VDS/storage links, missing/mismatched metadata/init state and
  changed source fail closed. Verify optional dependency error is fixed-safe.
- [ ] Run focused tests; commit explicit two paths:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p test_external_reset.py -v
git add src/robot_debug/external_reset.py tests/test_external_reset.py
git commit -m "feat(replay): validate narrow external reset source"
```

## Task2: Full-path asset closure

Same builder/files; sequential dependency onTask1.

- [ ] Write failing temporary-root fixtures: identical basenames in different
  suffixes, the explicit Chiliocosm alias, scenes/../textures, escaping paths,
  repeated markers, unknown namespace, links, missing/large/changed assets.
- [ ] Implement resolution to selected root only, immutable canonical closure
  list and exact resolved-result fields. Never search by basename or open old
  dataset absolute paths. Validate resolved XML/hash/closure before restore.
- [ ] Run focused tests, verify source XML unchanged; commit
  `feat(replay): resolve pinned external scene asset closure`.

## Task3: Restoration helper with observable order

Same builder/files; sequential dependency onTask2.

- [ ] Write fake environment tracking calls and110element simulator state.
  Tests assert reset, XML reset, dimension check, set_init_state, pre-hash,
  exactly ten open-gripper steps, post-hash, last observation. No policy call,
  saved action or dataset image. Test dimension mismatch before state apply,
  state mismatch before settling, step failure, nonfinite post-state and
  changed asset closure before any environment mutation.
- [ ] Implement helper returning exact observation/reset_metadata contract.
  Observation retains upstream raw shape; metadata always keeps robot replay
  unverified. Nominal/perturbed callers restoring same candidate must share
  identical start identity. Never fall back to benchmark reset index0.
- [ ] Run focused tests; commit
  `feat(replay): restore external state with settling evidence`.

## Task4: Review and root acceptance

- [ ] Root supplies exactSHAs/spec to independent spec reviewer; fix/recheck
  findings before independent quality review. Only root cherry-picks into main.
- [ ] Fresh full485+ suite, node syntax and gitdiffcheck; normal unit suite must
  run without installed h5py. Run reader on acquired ignored actual sample with
  research venv; print only bounded hashes/counts, no original XML/privatepaths.
  It must match source/state hashes and remain restoration_verified false.
- [ ] Update research/STATE/roadmap with tested scope and missing actual installed
  assets/runtime. Commitdocs/push, verify exactCIhead. Do not say M5B complete.
- [ ] Root writes next bounded evaluator/case-identity wiring plan from reviewed
  interfaces. Before real simulator/GR00T execution, verify installed runtime,
  controller, camera orientation, repeated restored start and fresh paidcap.

Review checkpoint explains why a saved vector is not yet a replayable policy
case and distinguishes fixture ordering from actual simulator compatibility.
