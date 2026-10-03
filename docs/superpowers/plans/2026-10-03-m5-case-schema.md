# M5A Case Schema Kernel Implementation Plan

> **For agentic workers:** Use subagent-driven-development or executing-plans,
> with test-driven-development. Steps use checkboxes. Root integrates only
> after independent spec review followed by quality review.

**Goal:** Provide a strict, deterministic JSON case contract and replay-input
assessment shared by the later importer/exporter and read-only viewer.

**Architecture:** Pure Python functions normalize structural data, compute
identity and enumerate recipe prerequisites. This unit performs no filesystem
inspection and cannot establish historical confirmation or exercised replay.
The next bounded case-I/O plan will reconcile source artifacts before deriving
capabilities; do not mistake structural validation for evidence validation.

**Tech Stack:** Python 3.11 standard library, unittest; no new dependencies.

## Authority, ownership and dependencies

The [case contract](../specs/2026-10-03-m5-case-contract-design.md) is accepted.
This is green implementation within that contract, not a new fault family or
algorithm. No cloud/provider calls, viewer changes, source artifact mutation,
external format reader or execution command. Root owns docs and integration.

Builder: balanced smaller-model fallback `gpt-6-sol` at medium reasoning
(preferred Terra is unavailable in the agent tool). Own only new
`src/robot_debug/cases.py` and `tests/test_cases.py`. Work in the reused linked
worktree on `codex/m5-case-schema`; no merge or push. Root prepares the next
case-I/O mapping while this isolated builder works. Reviewer reads only.

```text
accepted A1 -> schema builder -> spec review -> quality review -> root integration
                  || root source-mapping preparation (read-only)
integrated schema -> separate bounded case-I/O plan -> CLI -> viewer
```

Expected outputs: tested pure API and a Conventional Commit; no working import
CLI is claimed at this unit's exit. Runtime-profile metadata supplementation
and reimport validation are later I/O work, not omitted milestone requirements.

## Exact public API and normalized shapes

```python
class CaseValidationError(ValueError):
    """Malformed or unsupported version-1 structural case data."""

def normalize_case(value: dict) -> dict:
    """Return an independent normalized copy; validate stored identity if present."""

def case_identity(value: dict) -> str:
    """Full SHA-256 of normalized identity fields, ignoring stored case_id."""

def recipe_missing(value: dict) -> list[str]:
    """Sorted dotted field names for absent replay inputs; not runtime verification."""
```

Top-level allowed keys exactly match the accepted contract: schema_version,
case_id, source, task, policy, runtime, perturbation, protocol, evidence,
measurements, capabilities, limitations. All required except case_id may be
absent when constructing a new record; normalization fills the computed ID.
Validate stored case_id against the computed full lowercase hash.

Strict identity groups (reject unknown keys, boolean numbers, nonfinite values):

- source: adapter `existing-m4-v1`; summary/replay each reference object
  `{path: str, sha256: str}`; optional profile of that same reference shape or
  null. Paths are nonempty portable root-relative POSIX paths, no absolute,
  drive, backslash, empty segment, `.` or `..` components. Hash is 64 lowercase
  hexadecimal characters. Path checks are syntactic only in this module.
- task: suite `libero-object`, task_id and reset_index nonnegative integers,
  seed/env_seed integer or null, reset_strategy `libero-init-state-index`.
- policy: model_id/checkpoint_revision string or null, provenance mapping.
- runtime: project_revision/upstream_harness_revision/simulator_image_digest
  string or null, provenance mapping. Non-null revision values must be nonempty;
  simulator digest must be `sha256:` followed by 64 lowercase hex characters.
- perturbation: family `agentview-opaque-rectangle`, rectangle with exactly
  x/y/width/height, fill_value integer 0..255 or null. Coordinates finite numeric,
  normalized to floats, 0<=x/y<=1, width/height>0, right/bottom<=1. Normalize
  negative zero to zero. Do not clamp invalid rectangles.
- protocol: failures=4, max_attempts=5, reject_successes=2, nominal_controls=5;
  strict integers, not booleans. These are the existing diagnostic rules, not
  configurable new experiment algorithms.

Evidence is a mapping; measurements and capabilities are mappings; limitations
is a list of strings. Provenance maps and these nonidentity groups may contain
JSON scalar/list/map values only, with finite numbers and string map keys.
No tuple, bytes, object instances, NaN/Infinity or executable serialization.
These groups will gain their source-derived semantics in the next I/O plan.
`normalize_case` must document that it validates structure only and never
certifies stored capability claims. It preserves JSON data without executing
commands or opening paths. The I/O reimporter must recompute capability claims.

Identity selects source.adapter (not source paths/hashes/profile), task,
policy model_id/checkpoint_revision, runtime revision/digest fields,
perturbation and protocol. Exclude provenance, evidence, measurements,
capabilities and limitations. Canonical JSON: sorted keys, compact separators,
UTF-8, ensure_ascii=False, allow_nan=False. Hash the UTF-8 bytes with SHA-256.
All input must remain unmodified; outputs share no mutable children with input.

Recipe missing fields: task.seed, task.env_seed, policy.model_id,
policy.checkpoint_revision, runtime.project_revision,
runtime.upstream_harness_revision, runtime.simulator_image_digest,
perturbation.fill_value when null. Structural validation ensures the other
task/reset/geometry/protocol prerequisites. Complete means this list is empty,
not that a run was exercised or that failure was confirmed.

## Task 1 — Failing tests and deterministic schema (green)

Files: create `cases.py` and `test_cases.py` above. Fixtures synthetic and tiny.

- [x] Write a reusable complete fixture with source summary/replay dummy
  relative paths/hash, task0/reset0/seeds7, model `example-policy`/revision
  `example-revision`, runtime dummy pins, rectangle x=.625/y=0/w=.375/h=.375,
  fill0 and fixed protocol. Set nonidentity maps empty and limitations empty.
- [x] Add the first failing test before implementation:

```python
raw = complete_case_fixture()
raw['perturbation']['rectangle']['y'] = 0
normalized = normalize_case(raw)
variant = complete_case_fixture()
variant['perturbation']['rectangle']['y'] = 0.0
self.assertEqual(normalized['case_id'], case_identity(variant))
self.assertEqual(recipe_missing(normalized), [])
self.assertNotIn('case_id', raw)  # no mutation
```

- [x] Run and observe missing API failure with a nonzero test count after
  scaffolding imports as needed. Implement the API and the structural contract.
- [x] Add parameterized tests for unknown schema/top/identity-group keys,
  boolean IDs/protocol/geometry, bad digests/hashes/paths, invalid/nonfinite
  rectangles, non-JSON values, stored identity mismatch and deep-copy behavior.
- [x] Test all missing replay fields are enumerated; excluding optional media
  and changing evidence/capabilities/measurement/provenance/source placement
  leaves identity unchanged. Changing a runtime pin, task/reset, mask or fill
  changes identity. Stored positive badges must not affect recipe_missing.
- [x] Run focused tests, self-review, commit explicit owned paths:
  `feat(cases): validate deterministic case schema and recipe inputs`.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p test_cases.py -v
git diff --check
```

## Task 2 — Reviews, integration and next boundary

- [x] Independent spec reviewer checks every identity exclusion, prerequisite,
  strict numeric/path rule, no input mutation and no evidence-certification
  claim; runs focused tests. Fix blocking findings in the builder worktree.
- [x] Independent quality reviewer checks pure API behavior, deterministic
  hashing, recursive JSON validation and tests after spec pass.
- [x] Root integrates only reviewed commits and runs the full suite (baseline
  main 390 tests/four platform skips). Record exact results, not an estimate.
- [ ] Update master plan/current-state/dev-log and push with remote verification.
  Leave A2 incomplete: no CLI or real-case reconciliation exists yet.
- [ ] Prepare the next bounded case-I/O plan against the now-fixed API and real
  M4 source shape. It must reconcile aggregate outcomes/control identity and
  derive statuses; never trust this kernel's accepted JSON as confirmation.

No spending gate is opened by finishing this unit. No new human question is
needed for routine plan-conforming implementation. Escalate only a material
contract conflict; do not repeatedly ask about the accepted schema direction.

**Verified implementation:** main `46a3419` / `d29f87a`, ten focused tests and
400 full-suite tests/four known platform skips. Both independent review gates
passed, including the malformed Unicode/integer correction. The next case-I/O
plan is not implemented by this unit; A2 and the viewer journey remain incomplete.
