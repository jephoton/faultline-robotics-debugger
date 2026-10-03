# M5A case contract

**Status:** Proposed exact A1 contract for review. M5 scope and the CLI-first,
read-only-viewer boundary are accepted. This document does not authorize an
importer implementation, external reset adapter, model call or cloud start.

## Purpose and inspected evidence

A case connects a robot task and a triggering condition to its evidence and
replay prerequisites. It is not a new experiment and does not become verified
merely because a user imports it.

The existing M4 replay manifest records task 0, reset/episode index 0, seed 7,
the reduced rectangle and a four-failure/five-attempt acceptance rule. It has
a model identity and repository revision, but lacks a complete checkpoint and
simulator/runtime pin set. Its companion summary has the reduction lineage,
individual outcomes and controls. Keep that useful historical evidence even
when a recipe is incomplete. Never execute its embedded `replay_command`.

## Alternatives and recommendation

1. **Independent capabilities (recommended):** display inspectability, recipe
   completeness, exercised replay and historical failure evidence separately.
   This is slightly more metadata but avoids misleading progress labels.
2. One linear state (`imported -> ready -> confirmed -> reduced`): simpler UI,
   but a confirmed historical case may still lack portable replay inputs.
3. Reject every incomplete import: strong recipe guarantees, but prevents
   users inspecting recordings and discovering what metadata they must supply.

Use option 1. No database or plugin framework: bounded versioned JSON, existing
catalog/reduction validation, local CLI writes and read-only viewer reads.

## Index schema, version 1

The generated `case.json` contains only the following top-level fields. Unknown
schema versions and malformed required fields are refused. Optional values are
explicitly null; missing information is never filled from today's environment.

| Field | Contract |
| --- | --- |
| `schema_version` | Integer 1, not boolean. |
| `case_id` | Full SHA-256 of canonical identity fields described below. |
| `source` | Adapter `existing-m4-v1`; root-relative summary and replay references, each with SHA-256; no absolute paths or executable commands. |
| `task` | Suite `libero-object`, nonnegative global task ID, nonnegative reset index, seed and environment seed (nullable where absent); reset strategy `libero-init-state-index` for this adapter. |
| `policy` | Model identifier and checkpoint revision, nullable; source references for each supplied value. |
| `runtime` | Project revision, upstream harness revision, simulator image digest; each nullable and evidence-linked. |
| `perturbation` | Existing agent-view opaque-rectangle family, normalized x/y/width/height and fill value; no new fault family. |
| `protocol` | Existing failure acceptance and rejection rules plus nominal-control requirements; preserve current definitions, not a user-editable new search algorithm. |
| `evidence` | Episode references, aggregate hashes, optional video/trace references, raw outcomes, historical gate results and reduction lineage. |
| `measurements` | Reported elapsed times/counts and provenance; costs nullable with kind `warm-estimate`, `allocation-estimate` or `billed`. Do not infer billed cost. |
| `capabilities` | Derived assessment below, with reasons and evidence references. Never trust an imported capability flag. |
| `limitations` | Deterministically generated missing-input and claim-boundary messages. No copied arbitrary log text. |

Case identity is the canonical adapter version, suite/task/reset/seeds, model
and runtime pins, triggering condition and protocol. Source file placement and
media availability are not identity. Filling an identity pin creates a new
case ID; it does not mutate the old case silently. Re-registering an identical
case with identical source hashes is idempotent. A different payload at an
existing ID is refused rather than overwritten. Canonical JSON uses sorted
keys, compact separators, UTF-8 and finite numeric values; normalize rectangle
numbers before hashing so `0` and `0.0` do not create different identities.

## Four independent assessments

| Assessment | Values and evidence needed |
| --- | --- |
| Inspection | `available` if at least one structurally valid selected episode can be shown; otherwise `unavailable`. Missing video does not erase outcomes/traces. Show separate media counts. |
| Replay recipe | `complete` only with the supported task/reset strategy, both seeds, exact policy/runtime pins, perturbation and protocol; otherwise `incomplete` with an enumerated missing list. Completeness is not successful execution. |
| Exercised replay | `verified` only with a validated run explicitly linked to this exact recipe identity in the intended runtime; otherwise `unverified`. M5A does not run it or fabricate a fresh verification. |
| Historical failure | `confirmed` only when existing validated gate/lineage and matching controls support it; `not-established` when evidence is insufficient; `conflicting` for inconsistent identities or claims. Label this as saved historical evidence, not confirmation performed on import. |

No badge certifies causal mechanism, universal coverage, global minimality or
industrial safety. An infrastructure error is never a policy failure. Existing
M4 evidence can therefore be inspectable and historically confirmed while
its portable recipe remains incomplete and newly exercised replay unverified.

Historical confirmation requires reconciling the summary/replay gate counts
with the referenced aggregate episodes: task/reset/seeds, recorded policy
identity, masks, raw outcomes and matching nominal controls must agree. The
existing reduction-summary validator alone is insufficient. Missing core
evidence gives `not-established`; contradictory evidence gives `conflicting`.
Supplemented runtime pins are proposed replay inputs, not proof that those
pins were used historically unless their provenance establishes that link.

## Local registration and export boundary

- First adapter accepts one existing M4 summary/replay pair and its associated
  aggregates under an explicitly selected artifact root. It is not an arbitrary
  video importer or the later external HDF5 adapter.
- Registration writes a separate case workspace, leaving sources unchanged.
  Local workspace location belongs in ignored CLI configuration, not public
  `case.json`. References must resolve to regular files within the selected
  source root; reject escaping paths/symlinks. Hash inputs and recheck hashes
  on inspection/export. Changed or unavailable source files invalidate dependent
  evidence/readiness instead of retaining stale positive badges.
  Missing/changed optional video or trace affects media availability, not
  recipe completeness. Missing/changed aggregates or summary/replay sources
  invalidate historical confirmation. Recipe completeness depends on intact,
  validated recipe inputs, including any metadata profile it relies on.
- Optional explicit `runtime-profile.json` supplies missing pinned metadata
  and its provenance. It cannot override conflicting source values, invent
  exercised-replay evidence or claim that a seed is a portable world snapshot.
  Current repository defaults are never automatically substituted.
- Export into a new output directory: normalized `case.json`, `README.md` and,
  only when complete, structured `replay_recipe.json`. Reimport requires the
  same referenced source content under an explicitly supplied local root;
  exported metadata alone cannot establish historical evidence. The human summary names
  missing prerequisites and historical/fresh distinctions. No arbitrary copied
  shell strings. Recipes are data; there is no automatic execute command in A.
- Default export is metadata-only: keep source-relative hashes but explicitly
  mark referenced media as not included. A user can inspect these on the source
  machine; another machine does not magically acquire recordings or weights.
  Copying videos/datasets or adding a portable archive is separate scope.
- A second narrow entry path reimports exported normalized `case.json` with
  an explicit local source root. Validate schema and recompute case identity,
  source hashes and capabilities; never accept stored positive badges on trust.
  Equivalence covers normalized identity, recipe inputs and intact core evidence,
  not machine-local configuration or unavailable media.

## Acceptance tests and human checkpoint

Tiny fixtures must demonstrate complete and incomplete cases, historical
confirmation without complete replay pins, complete recipe without exercised
replay, missing media, conflicting identities/gates, infrastructure errors,
duplicate registration, unknown versions, nonfinite/bool geometry, path escape,
source mutation and normalized export/reimport equivalence. No live calls.
An internally consistent summary that contradicts its aggregate must never
receive `confirmed`. An unavailable optional recording must not turn otherwise
intact recipe inputs into an incomplete recipe.

After approval, root writes the exact implementation sub-plan, CLI/API
signatures and test/commit boundaries. A smaller case builder implements it;
independent review precedes integration. The UI builder follows that integrated
contract. Existing media fixes proceed independently in their own worktree.

**Review question:** Approve independent capability badges and explicit pinned
metadata supplementation, with metadata-only export for M5A? This settles the
case boundary; it does not approve M5B/C or paid execution.
