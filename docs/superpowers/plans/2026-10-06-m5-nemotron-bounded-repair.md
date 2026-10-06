# M5C bounded Nemotron repair implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development
> with test-driven-development, followed by independent spec and quality review.

**Goal:** Permit exactly one newly approved US$0.02 attempt without discarding
the first failed attempt or weakening evidence/secret safety.

**Architecture:** Keep the model, endpoint, prompt, JSON mode and report schema.
Raise the fixed output/usage bound to 4,096 and socket timeout to 90 seconds.
Use a new fixed reservation directory; retain the old directory untouched.
Add only an allowlisted truncation error code, not raw provider diagnostics.

**Tech stack:** Existing Python 3.11 standard library and unittest.

## Execution checkpoint

- [x] Task1 implementation, red regressions,56focused green tests, exactSHA
  spec and quality reviews; root integrated as `8110001`.
- [x] Task2 full581tests, preflight, one paid attempt, unchanged source/old
  reservation and actual HTTP report checks. Request completed structurally.
- [x] Actual output depth/citation limitations recorded in pilot/feedback/handoff.
- [ ] Final publication/CI verification and human report/viewport acceptance.

Both allowances consumed. No automatic follow-up request. Structural success
does not certify usefulness or factual grounding; M5B is a separate open gate.

## Accepted boundary and ownership

Jethro approved this repair and one new US$0.02 attempt on October 6. No GPU
compute, new model, undocumented thinking flag, automatic retry or extra cap.
Root owns Git integration, credentials, paid call, original evidence and docs.
One smaller balanced builder owns the tightly coupled six code/test files in
the existing clean attached client worktree, based on this committed plan.
Use gpt-5.6-sol medium: Terra was unavailable in the preceding batch.
Spec reviewer reads code/tests independently; quality reviewer follows spec
acceptance. Neither reviewer nor builder reads real keys or calls providers.

```text
root plan -> isolated builder -> spec review -> quality review
          -> root integration/full tests -> one live call -> evidence review
root naming/alignment/handoff maintenance proceeds independently of builder
```

Green: tests and documentation. Amber: exact limit/reservation/error-code repair.
Red: any further attempt, model/prompt change, GPU start or new data sharing.
Stop on unresolved important review findings. Do not repeatedly ask about
the accepted repair. No UI changes or new sidecar keys/version in this patch.

## Task 1 — Coupled client/store/CLI repair

Files: `src/robot_debug/token_factory.py`, `explanation_store.py`,
`scripts/explain_case.py`, `tests/test_token_factory.py`,
`tests/test_explanation_store.py`, `tests/test_explain_case.py`.

- [ ] Write failing tests before production edits. In existing client payload
  test change expected tuple to `(MODEL, 4096, 0, False)`. Add accepted usage
  boundary 4096 and rejected 4097, Boolean, negative and malformed totals.
  Use the existing valid response/content fixture, not a real request:

```python
response = self.response(usage={"prompt_tokens": 100, "completion_tokens": 4096,
                               "total_tokens": 4196})
result = request_interpretation(PACKET, KEY, lambda *args: response)
self.assertEqual(result["provenance"]["completion_tokens"], 4096)
self.assertEqual(result["provenance"]["estimated_cost_usd"], 0.00098904)
```

- [ ] Test HTTPSConnection receives timeout90 with existing mocked connection;
  preserve exact host/TLS, response262144-byte/request6000-byte bounds.
  Change the old601-overflow fixture to4097 (601 is now legal usage).
- [ ] For exact-model, validated-usage, single-dict-choice responses whose
  `finish_reason` is exactly `length`, expect null content, status
  `invalid_response`, fixed error `output_limit`, trustworthy usage/cost.
  Unknown finish reasons/malformed choices/wrong model remain `invalid_response`.
  No raw content, reasoning, headers or unvalidated finish reason is persisted.
- [ ] Store tests round-trip completed4096, legacy600 and new output_limit
  fallback, retaining old report identities without migration. Reject4097 and
  `completed` paired with `output_limit`; retain all existing safety tests.
- [ ] CLI regression: create an old reservation in a temporary sibling
  `m5-nemotron-pilot`, snapshot its bytes, patch module `PILOT_ROOT` to sibling
  `m5-nemotron-pilot-repair-20261006`, run existing injected live orchestration.
  Assert one POST, unchanged old marker, new exclusive marker, second invocation
  refuses before POST even if marker is partial. No real credentials/network.
- [ ] Run focused tests expecting red, then make minimal production changes:

```python
# token_factory.py
_TIMEOUT_SECONDS = 90
# payload max_tokens and _usage upper completion bound: 4096
# Existing invalid response status gains fixed output_limit only for the
# trusted exact-model/usage/single-choice length boundary described above.
# explanation_store.py
# _integer(completion, 4096)
# invalid_response permits error_code in {"invalid_response", "output_limit"}
# scripts/explain_case.py
PILOT_ROOT = REPOSITORY_ROOT / "artifacts" / "m5-nemotron-pilot-repair-20261006"
```

The CLI remains `live`, with no caller-selectable model, endpoint, limits,
reservation path or retry flag. Default request remains one POST. Keep all
fresh-source checks before reservation and after inference. Old reports keep
schema_version1, exact key set and immutable storage. Cost remains estimate,
billed cost null. A 90-second socket timeout is not a hard wall-clock deadline.

- [ ] Run the three focused suites, self-review, explicit-path commit
  `fix(explanation): bound one approved longer Nemotron attempt`.
- [ ] Independent spec then quality review at exact SHA, with regression tests;
  repair and re-review important findings before root integration.

## Task 2 — Root verification, live acceptance and handoff

- [ ] Integrate reviewed commit only. Run full suite (baseline578/fourWindows
  skips), diff check, confirm old local reservation remains and new path absent.
- [ ] Revalidate registered M4 case/packet and hash all116source evidence files.
  Reuse the original metadata-only packet and local ignored `.env`; never print
  the key or provider raw body. Authenticated preflight must find exact model.
- [ ] Execute existing guarded `live` command exactly once. Full new US$0.02
  reservation is consumed even on interruption/rejection. No further retry.
  At1096input/4096output tokens estimated maximum isUS$0.0010488 before extras;
  262144input/4096output conservative estimate isUS$0.01671168 before extras.
- [ ] Inspect stored report citations/claims, source hashes and HTTP viewer
  collection. Describe interpretation as generated/human-review required,
  never factual authority. If rejected, retain honest fallback and stop paid work.
- [ ] Update pilot record, FEEDBACK.md, PROJECT_PLAN.md and handoff state;
  record actual usage/latency and unknown posted charges. M5C acceptance still
  requires useful real interpretation and browser QA; M5B replay is separate.
- [ ] Commit docs explicitly, push, check exact-SHA CI and clean status.

## Exact local commands

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p test_token_factory.py -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p test_explanation_store.py -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p test_explain_case.py -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -q
git diff --check
```

Focused discovery must run nonzero tests. All provider test transports are fake;
only root's separately gated real attempt demonstrates hosted model use.
