# M5C offline explanation contract

Status: Proposed for Jethro's review, October 4, 2026.
The model/data/cap decision is already accepted in ADR 0014; this document
settles the smaller packet/report contract before implementation. No key,
provider call, new dependency, simulator or UI change is required.

## Purpose and recommended approach

Prepare the useful offline portion of M5C while Token Factory access is pending:
build an allowlisted evidence packet, derive an ordinary factual summary, and
validate a supplied explanation without trusting it as an experiment result.

Options:

1. **Two pure Python modules, recommended.** Packet preparation and report
   validation need no network or credentials. They can be tested now and reused
   by a separately bounded provider CLI and the read-only viewer later.
2. Wait for the key and build everything together. Less intermediate code,
   but credentials would unnecessarily block privacy and regression testing.
3. Build an SDK client plus viewer integration immediately. More demo-visible,
   but mixes paid-request safety, persistence and UI with an unsettled schema.
   Not the first increment.

Use existing Python 3.11/unittest and the standard library. Do not introduce
an agent framework, model SDK, tokenizer, database or a general chat interface
for this offline increment. This decision is reversible: a provider adapter
will consume these functions without changing experiment outcomes.

## Input boundary

The future live caller must obtain a case through `case_store.inspect_case`,
which revalidates source evidence. The pure kernel cannot inspect files or
prove provenance. It validates shape only, and labels outcomes as reported.

`src/robot_debug/evidence_packet.py` exposes:

```python
class EvidencePacketError(ValueError): ...
def make_evidence_packet(case: dict) -> dict: ...
def validate_evidence_packet(packet: dict) -> dict: ...
def packet_identity(packet: dict) -> str: ...
```

Only this allowlist may appear in the outbound packet:

```json
{
  "schema_version": 1,
  "task": {"suite": "libero-object", "task_id": 0, "reset_index": 0},
  "reduced_mask": {
    "family": "agentview-opaque-rectangle",
    "rectangle": {"x": 0.625, "y": 0.0, "width": 0.375, "height": 0.375},
    "fill_value": [0, 0, 0]
  },
  "episodes": [
    {"evidence_id": "0123456789abcdef", "role": "reduced",
     "raw_outcome": "task_failure", "gate_outcome": "policy_failure"}
  ]
}
```

The sample is illustrative, not a real episode or provider response. The mask
describes the case's final reduced condition, not every listed episode. Parent
and other-candidate geometry is not available in this projection; no fabricated
parent area, global minimum, missing-pin recovery or per-episode geometry.

Exclude case/source paths, media, instructions, stage names, arbitrary strings,
policy/runtime identity, provenance, raw trace events, operator logs, credentials,
measurement payloads and imported capability/limitation text. In particular,
do not turn source-authored instructions into model instructions. Task IDs are
deliberate for this small increment; a trusted human-readable label can be
designed separately if actual pilot usefulness needs it.

Rules:

- Schema version is integer 1, not Boolean; exact fields, no unknown fields.
- Preserve the existing case task/mask validation via `normalize_case`; map
  any upstream exception to a fixed, non-secret `EvidencePacketError` message.
- Task/reset indices must be ordinary nonnegative integers, at most 1,000,000.
- At most 64 episodes, at least one; unique 16-character lowercase hex IDs.
  Sort by ID for stable serialization; never silently truncate episodes.
- Roles: `nominal`, `parent`, `reduced`, `other`.
- Raw outcomes: `success`, `task_failure`, `episode_timeout`,
  `infrastructure_error`. Gate outcomes: `success`, `policy_failure`,
  `infrastructure_error`. Allow only consistent pairs: success/success,
  task_failure/policy_failure, episode_timeout/policy_failure,
  infrastructure_error/infrastructure_error. Unknown or contradictory pairs
  fail rather than being relabeled.
- Reject Boolean/nonfinite/oversized numbers; mask remains inside unit image;
  fill is null or three integer bytes. No arbitrary metadata survives.
- Canonical sorted compact UTF-8 JSON, no NaN, maximum 16,384 bytes.
  `packet_identity` is SHA-256 of those canonical bytes, not the source case ID.
  Return detached data; never mutate case input.
- Packet identity is for the local report, not another required outbound field.

## Supplied explanation and deterministic fallback

`src/robot_debug/explanation.py` exposes:

```python
class ExplanationValidationError(ValueError): ...
def validate_explanation(response_json: str, packet: dict) -> dict: ...
def deterministic_summary(packet: dict) -> dict: ...
def build_offline_report(packet: dict, response_json: str | None = None) -> dict: ...
```

Supplied explanation schema:

```json
{
  "schema_version": 1,
  "observations": [{"text": "Reported outcomes differ between these episodes.",
                    "evidence_ids": ["0123456789abcdef"]}],
  "hypotheses": [],
  "limitations": ["These inputs do not establish a causal mechanism."]
}
```

Reject duplicate JSON keys, trailing content/fences, nonfinite values, invalid
UTF-8 serialization, Boolean schema version, unknown fields, malformed/nested
objects, unknown/duplicate citation IDs and empty citation lists. Every
observation/hypothesis needs one or more IDs from the packet. Maximum four
observations, three hypotheses, six limitations; every text is a nonempty
single-line string at most 600 characters; each citation list at most 64 IDs;
whole input at most 16,384 UTF-8 bytes. Empty observation/hypothesis lists are
valid. Validation checks structure and citation membership, **not truth or
whether a citation supports the prose**. There is no causal-proof detector.

`deterministic_summary` derives reported counts by role separately for raw
and gate outcomes, total episodes and final mask area. Preserve timeout versus
task-failure distinctions. Counts are not statistical confidence, fresh
confirmation or reconciled billing. Do not generate a proof/confirmation badge.

`build_offline_report` always returns deterministic facts and a fixed disclaimer:
reported evidence only, budget-local mask, no causal proof, supplied interpretation
requires human review. It returns the packet hash plus:

- `interpretation_status: absent`, with null interpretation when none supplied;
- `interpretation_status: validated-structure`, with detached validated data;
- `interpretation_status: rejected`, null interpretation and one fixed error
  code when validation fails. Preserve identical deterministic facts.

Do not echo rejected raw text or exceptions. None of these statuses establishes
that Nemotron was called. Provider identity, usage/cost/latency, persistence,
human acceptance and viewer labels belong to later integration. Test fixtures
cannot become apparent real NVIDIA/Nebius results.

## Verification and ownership

Builder owns only the two modules plus `tests/test_evidence_packet.py` and
`tests/test_explanation.py`. Reuse the existing tiny M4 fixture/importer for
case test setup, not real artifacts. Root owns this design, the future execution
plan, integration and handoff. No production edits before design approval.

Acceptance tests cover allowlist/privacy removal (injected instructions, fake
paths/secrets/provenance), stable ID/order, nonmutation, bounds, duplicate IDs,
raw/gate distinction, malformed JSON/surrogates/huge numbers, unsupported
citations, detached valid output, and deterministic fallback preservation.
Patch network entry points to fail if any offline test attempts a request.
No file persistence, credential loading, media reading or model API code here.

Concurrency map after approval:

```text
accepted contract -> smaller builder: packet + report/tests -> spec review
                  -> independent adversarial test review --^ -> quality review
root: scoped plan, Git integration, full suite, handoff ------> next checkpoint
```

The independent review is read-only with no overlapping file edits. Root alone
merges and publishes. Commit packet and report as separate coherent units,
then integrate only after spec and quality review and fresh full tests.

## Completion boundary

This increment is complete when offline tests pass and deterministic facts
survive malformed/unavailable interpretations. It does **not** complete M5C.
The next increment adds the bounded provider CLI and local artifact binding,
followed by the viewer read path and a real approved pilot. Credentials,
live catalog/price/balance and spending checks still gate that pilot. No VM
start or expanded M3 work is included.
