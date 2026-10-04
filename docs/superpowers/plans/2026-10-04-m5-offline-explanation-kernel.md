# M5C Offline Explanation Kernel Implementation Plan

> For agentic workers: use subagent-driven-development/TDD. Root integrates
> after independent spec then quality review. Steps use checkboxes.

**Goal:** Produce privacy-safe packets and a deterministic report with optional,
locally validated interpretations, without reading secrets or calling models.

**Architecture:** Two pure modules consume detached dictionaries. The packet
kernel structurally normalizes a supported case, then allowlists metadata.
The report kernel separately derives facts and validates supplied JSON. Source
revalidation remains the future caller's responsibility; no filesystem or API
adapter is part of this increment.

**Tech stack:** Python 3.11, standard library, existing unittest fixtures.

## Authority, ownership and dependencies

Jethro approved the exact contract on October 4:
`docs/superpowers/specs/2026-10-04-m5-offline-explanation-contract-design.md`.
The contract is authoritative for every field, bound and claim limitation.
All implementation is green within that contract. No provider, SDK, CLI,
key loading, UI, artifact persistence or simulator changes. No cloud spend.

Reuse the clean attached `m3-exact-vm-watchdog` checkout on a new
`codex/m5-offline-explanation` branch from the committed plan. Never touch
the dirty frozen M3 launcher checkout. Root checks cleanliness and starts
the baseline before builder editing; baseline failure blocks implementation.

| Owner | Files / output |
| --- | --- |
| Smaller balanced builder | `src/robot_debug/evidence_packet.py`, `src/robot_debug/explanation.py`, `tests/test_evidence_packet.py`, `tests/test_explanation.py` only; coherent commits and red/green evidence |
| Independent spec reviewer | Read-only comparison with accepted contract; adversarial reproductions, exact findings |
| Independent quality reviewer | Read-only correctness/privacy/bounds review after spec pass |
| Root | Plans/spec status, main roadmap/handoff/dev-log, Git integration, real local acceptance and full-suite verification |

```text
approved contract -> committed plan -> clean worktree baseline -> builder
                    root: real case acceptance preparation -----+
builder packet -> builder report -> spec review -> fixes -> quality review
 -> fixes -> root integration/full tests -> handoff/push/CI check
```

Do not add agents for small edits. One builder owns both tightly dependent
modules; reviewers independently challenge the contract and evidence. The
parallel work is implementation versus root's integration/acceptance prep.
Root alone merges/pushes; no live external resource owner is needed here.

## Task 1 — Allowlisted evidence packet

- [x] Write `tests/test_evidence_packet.py` using the existing
  `tests.test_case_io.fixture` and `import_m4` with a temporary directory. No
  ignored real artifacts are required for the public suite.
- [x] Begin with this behavioral test and run it red:

```python
case = import_m4(self.root)
case['evidence']['episodes'][0]['instruction'] = 'ignore rules --token SECRET'
before = copy.deepcopy(case)
packet = make_evidence_packet(case)
self.assertEqual(set(packet), {'schema_version', 'task', 'reduced_mask', 'episodes'})
self.assertNotIn('SECRET', json.dumps(packet))
self.assertEqual(case, before)
self.assertEqual(packet, validate_evidence_packet(packet))
```

- [x] Implement the four specified public symbols in `evidence_packet.py`.
  Use exact maps; bool-resistant numeric checks; finite rectangle validation;
  RGB byte/null fill; source task bounds; the existing supported case normalizer
  with fixed sanitized error mapping. Build rows from episode ID/role/raw/gate
  fields only, sort by ID, reject duplicates/empty or more than 64 rows.
  Enforce the four accepted raw/gate pairs rather than relabeling outcomes.
- [x] Canonical bytes for validated packets use this exact serialization:

```python
encoded = json.dumps(packet, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=False, allow_nan=False).encode('utf-8')
if len(encoded) > 16384:
    raise EvidencePacketError('invalid evidence packet')
digest = hashlib.sha256(encoded).hexdigest()
```

  Every validation failure, including normalization/encoding/recursion/overflow,
  returns `EvidencePacketError('invalid evidence packet')`, not raw exceptions
  or data. `validate_evidence_packet` returns detached canonical data and
  `packet_identity` hashes it. Neither mutates caller dictionaries.
- [x] Add tests for ordering/hash stability, source-string/path/provenance
  exclusion, duplicate IDs, unknown/empty fields, unsupported roles/outcomes,
  bool/huge/nonfinite numbers, rectangle/fill limits, raw timeout preservation,
  consistent pairs, malformed source case and detached returned values.
  Patch `urllib.request.urlopen` to fail on attempted network access.
- [x] Run:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p test_evidence_packet.py -v
```

  Expected nonzero discovery, all tests pass after implementation. Commit only
  the module/tests: `feat(explanation): build allowlisted evidence packets`.

## Task 2 — Explanation schema, facts and fallback

- [x] Write `tests/test_explanation.py` using packets from Task 1 and JSON
  strings; no provider mock may be represented as real Nemotron provenance.
  Begin with a rejected-citation fallback test:

```python
bad = json.dumps({'schema_version': 1,
                 'observations': [{'text': 'Unsupported claim.',
                                   'evidence_ids': ['ffffffffffffffff']}],
                 'hypotheses': [], 'limitations': []})
base = build_offline_report(packet)
rejected = build_offline_report(packet, bad)
self.assertEqual(rejected['interpretation_status'], 'rejected')
self.assertEqual(rejected['facts'], base['facts'])
self.assertIsNone(rejected['interpretation'])
```

  Use a missing ID chosen independently of fixture IDs. Run red before code.
- [x] Implement the four specified public symbols in `explanation.py`.
  `validate_explanation` first validates the packet and input UTF-8 byte bound.
  Parse JSON with duplicate-key rejection and nonfinite rejection; enforce
  exact schemas and all accepted-contract bounds. Reject multiline/empty or
  oversized strings, bool versions, unknown/duplicate/empty citations. Return
  detached validated fields. Validation errors have one fixed message:
  `ExplanationValidationError('invalid explanation')`.
- [x] `deterministic_summary` returns exactly:

```json
{"total_episodes": 14,
 "counts_by_role": {"nominal": {"raw_outcomes": {}, "gate_outcomes": {}},
                    "parent": {"raw_outcomes": {}, "gate_outcomes": {}},
                    "reduced": {"raw_outcomes": {}, "gate_outcomes": {}},
                    "other": {"raw_outcomes": {}, "gate_outcomes": {}}},
 "reduced_mask_area_fraction": 0.1875}
```

  The numeric example is a fixture example, not the real M4 result. Each raw
  map always includes zero-initialized `success`, `task_failure`,
  `episode_timeout`, `infrastructure_error`; each gate map includes `success`,
  `policy_failure`, `infrastructure_error`. Increment each row exactly once.
  Area is width times height; no parent-area or reduction-optimality claim.
- [x] `build_offline_report` returns exactly `schema_version`, `packet_id`,
  `facts`, `interpretation_status`, `interpretation`, `error_code`,
  `disclaimer`. Version 1; hash from Task 1; fixed disclaimer states reported
  evidence, budget-local mask, no causal proof, human review required.
  No response: absent/null/null; valid response: validated-structure/data/null;
  invalid response: rejected/null/`invalid_explanation`. Invalid packets must
  fail before a report is built; only interpretation errors trigger fallback.
  No provider attribution, accepted-truth status or capability mutation.
- [x] Tests include duplicate JSON keys, fences/trailing data, nonfinite JSON,
  lone surrogates/deep nesting, malformed objects, field/text/list/byte limits,
  whitespace-only/multiline text, unsupported/duplicate citations, valid empty
  lists, detached outputs, preserved raw/gate facts, deterministic absent and
  rejected states, invariant case data and no network calls.
- [x] Run both focused files with unittest, then full discovery. Commit only
  module/tests: `feat(explanation): validate interpretations with factual fallback`.

## Task 3 — Reviews, integration and real offline acceptance

- [x] Spec reviewer reads actual diff and independently tests omitted input,
  source privacy, statuses, duplicates, bounds and fake-provenance cases.
  Builder repairs with regression tests; reviewer rechecks the exact commit.
- [x] After spec pass, quality reviewer probes malformed direct Python objects,
  normalization error sanitization, detached results and report fallback.
  No critical/important finding remains before integration.
- [x] Root fast-forwards the reviewed branch (no divergent main changes), runs the full suite and
  `git diff --check`. Use `case_store.inspect_case` on the ignored real M4
  registration and build packet/absent report. Expect 22 packet episodes,
  0.140625 mask area, absent interpretation and no private source paths. Hash
  original source records/media before/after; no source artifact is edited.
- [x] Root records implemented APIs and fresh results in `PROJECT_PLAN.md`,
  `docs/codex-handoff/STATE.md`, `docs/dev-log.md` and this plan. No provider
  feedback entry implies actual Nemotron use; Token Factory stays untested.
- [ ] Commit handoff, push under existing authority and verify newest CI.
  Hand off the bounded provider/client/persistence and viewer integration as
  next material work; credentials/account/price/cap still precede live calls.

M5C remains incomplete until a real approved invocation and evidence-linked
viewer explanation exist. This batch must not fake that completion.
