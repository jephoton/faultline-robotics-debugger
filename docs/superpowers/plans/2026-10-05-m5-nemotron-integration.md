# M5C Nemotron integration implementation plan

> For agentic workers: use subagent-driven-development and TDD. Root alone
> integrates, publishes and executes live requests. Steps use checkboxes.

**Goal:** Complete the accepted CLI → immutable report → read-only viewer
explanation path, with one conservatively reserved real Nemotron attempt.

**Architecture:** Reviewed pure packet/report kernels feed a bounded HTTPS
client; separately reviewed case-local sidecars feed the existing viewer.
No browser secrets/provider calls, source changes, simulator or M3 changes.

**Tech stack:** Python 3.11 standard library/unittest, existing vanilla viewer.
Exact contract: `../specs/2026-10-05-m5-nemotron-sidecars-design.md`.

## Ownership and concurrency

```text
committed design/plan -> clean isolated baseline
 -> balanced client builder: token_factory.py + test_token_factory.py --+
 -> balanced store builder: explanation_store.py + test_explanation_store.py
 -> independent spec then quality/security reviews -> root integration
 -> CLI builder: scripts/explain_case.py + tests/test_explain_case.py
store review/integration -> viewer builder: server/web + tests (parallel to CLI)
 -> review/integration -> root one live pilot/browser acceptance -> handoff
root: external adapter planning/research continues independently
```

Builders use separate clean attached worktrees; no overlapping ownership.
The read-only viewer depends on the reviewed store APIs, not the live client
or CLI. It can therefore proceed independently once the store is integrated;
real-output browser acceptance still waits for the fully reviewed CLI.
Root owns this plan/spec, docs/ADR, Git, credentials and paid execution. Smaller
balanced fallback is gpt-5.6-sol medium (Terra unavailable and gpt-6-sol hit
capacity); reviews use stronger
agents. Green: exact-contract implementation/tests/docs; amber: small helpers,
safe parsing/presentation inside contract; red: new model/data/reset/cloud cap.
Accepted decisions persist; no repeated model-downscale questions.

## Task 1 — Stored reports (independent builder)

- [x] Build fixture with `tests.test_case_io.fixture`, `case_io.import_m4`,
  `case_store.register_case` in separate temporary source/workspace directories.
  Write red test for source-bound offline round trip:

```python
packet = make_evidence_packet(inspect_case(workspace, case_id))
report = build_offline_report(packet)
stored = make_stored_report(case_id, packet, report, offline_provenance)
path = store_report(workspace, stored)
assert read_case_reports(workspace, case_id)['reports'] == [stored]
assert path.name == stored['report_id'] + '.json'
```

- [x] Implement five public APIs and error class in `explanation_store.py`
  exactly as the spec. Recompute kernel report and canonical identity; validate
  provenance; bound reads; refuse changed/unavailable source and symlink escapes;
  immutable atomic publication; malformed sidecars isolate safe warnings.
- [x] Add rejection tests for forged facts/hash/provider/IDs/cost, Boolean and
  oversized numbers, duplicate JSON keys, changed source/packet, symlink case
  and report directories/files, corrupt/oversized records, 101 reports, invalid
  timestamps, fake offline-as-live metadata, detached results and nonmutation.
  Mock network entry points to fail; no real key reads.
- [x] Run focused test then commit `feat(explanation): persist evidence-bound reports`.

Task1 integrated `466b0d7`/`731b82b` after independent spec/quality review.
Root fresh main:20focused passed,505full passed/four platform skips. Review
and repair details are in dev-log; no real inference was executed.

## Task 2 — Client and conservative reservation (independent builder)

- [ ] Create `token_factory.py` and `test_token_factory.py`. APIs:
  `TokenFactoryError(ValueError)` with fixed safe codes;
  `load_api_key(env_file: Path | None=None) -> str`;
  `preflight(api_key: str, transport=None) -> dict` (fixed model/endpoint only);
  `reserve_pilot(pilot_root: Path, case_id: str, packet_id: str) -> dict`;
  `request_interpretation(packet: dict, api_key: str, transport=None) -> dict`.
  Transport callable signature `(method, path, payload, api_key) -> dict`;
  default transport is fixed-base bounded verified HTTPS. Result exact keys
  `response_json`, `provenance`: valid string or null; provenance per spec.
- [ ] Begin red tests: redirect/proxy refusal, no retry after timeout, secret
  absent from exceptions/results, second reservation fails before transport:

```python
reserve_pilot(root, case_id, packet_id)
with self.assertRaises(TokenFactoryError):
    reserve_pilot(root, case_id, packet_id)
```

- [ ] Implement secret reader, GET catalog exact-ID check, fixed prompt/request,
  6,000-byte payload ceiling/600 output tokens, JSON-object mode, response/usage
  parsing and fixed errors. Paid requests require caller to reserve first;
  CLI ordering is separately tested. No source metadata beyond validated packet.
- [ ] Test 262,144-byte HTTP cap, exact host/method/path, redirects/TLS/proxies,
  401/403/429/500/timeouts, duplicate dotenv/quotes/newlines/symlinks, missing
  model/different returned model, truncated response, invalid usage and unknown
  billing, secret-containing response rejection, no retries, byte-bound refusal,
  reservation race/corruption/symlink safety and persistent interruption guard.
- [ ] Run focused test then commit `feat(explanation): add bounded Token Factory client`.

## Task 3 — Review and CLI integration

- [ ] Independent spec reviewer checks both implementations against the exact
  schema/safety contract with adversarial fixtures. Builder repairs and adds
  regressions; exact SHA recheck precedes quality/security review. No unresolved
  important finding before root cherry-picks/fast-forwards.
- [ ] CLI builder owns only `scripts/explain_case.py` and its tests. Prepare
  writes offline sidecar; preflight only authenticates catalog; live obtains
  fresh case/packet → checks key/catalog → reserves fixed repo-local allowance
  → requests once → builds factual fallback/validated report → reinspects
  source → stores exclusively. Reinspect before reserve too if preflight took
  time. No request on invalid/changed/unavailable cases or failed reservation.
- [ ] Red subprocess test for prepare with absent key:

```python
result = subprocess.run([sys.executable, 'scripts/explain_case.py', 'prepare',
                        '--workspace', str(workspace), '--case-id', case_id],
                       capture_output=True, text=True)
assert result.returncode == 0
assert json.loads(result.stdout)['interpretation_status'] == 'absent'
```

- [ ] Test live call ordering via injected orchestration dependencies, failed
  catalog/no POST, stale source/no attach, persistent cap/no second call,
  safe stdout/errors, malformed arguments, no mock-live CLI and no arbitrary
  endpoint/model/cap/pilot-root flags. Commit `feat(explanation): expose guarded case CLI`.
- [ ] Review spec then quality, integrate and run full suite before live use.

## Task 4 — Read-only viewer integration

- [ ] Builder owns `viewer/server.py`, `viewer/web/index.html`, `app.js`,
  `styles.css`, `tests/test_viewer_server.py` and a new focused JS test if needed.
  Add the GET-only explanation route and disclosure per spec. Do not refactor
  existing evidence UI or leak private source bindings/keys through HTTP.
- [ ] Add red HTTP fixtures for valid/offline/rejected/stale/corrupt reports,
  missing case and unsupported methods; assert no network/key access on GET.
  Frontend tests verify safe text rendering, exact evidence navigation,
  clearing previous-case state on change, racing fetch response isolation,
  refresh/new-report behavior and honest missing cost/provenance labels.
- [ ] Keep primary/comparison equal and technical details collapsed. Commit
  `feat(viewer): show evidence-linked Nemotron interpretations`.
- [ ] Independent spec then quality/accessibility review; root integrates and
  runs full suite, JS syntax and actual browser QA at 375/768/1440 widths.

## Task 5 — Root live acceptance and handoff

- [ ] Use the registered 22-episode M4 case only after source revalidation;
  record original evidence-file hashes before/after. Check current official
  prices again and funded-account confirmation. Do not invent credit expiry.
- [ ] Run CLI preflight, then the single `live` command. At most one POST,
  US$0.02 fully reserved, no automatic retry or VM start. Keep billing unknown
  until reconciled; record actual token usage/latency when present.
- [ ] Inspect persisted interpretation for citations and unsupported claims;
  expose it for human review in the viewer, not as accepted truth. If no useful
  valid output, preserve honest fallback and explain the failure before another
  paid attempt. Do not mark M5C complete without real reviewable output.
- [ ] Update FEEDBACK.md with observed onboarding/model strengths/friction and
  separate local defects; update PROJECT_PLAN.md, STATE.md, dev-log and operator
  walkthrough. Commit explicitly, push, verify latest CI and clean worktree.

## Commands and evidence

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p test_explanation_store.py -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p test_token_factory.py -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p test_explain_case.py -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -q
node --check src/robot_debug/viewer/web/app.js
git diff --check
```

Nonzero focused discovery and green full tests required. Baseline is 485 tests,
four Windows skips. Real provider success is separate from offline fixtures;
M5B restoration and a fresh paid GPU cap are not authorized by this plan.
