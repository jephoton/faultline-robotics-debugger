# M5C bounded Nemotron client and evidence-bound sidecars

Status: Accepted boundary October 5. Jethro approved immutable per-call
sidecars bound to case/packet identity; CLI-first, read-only viewer, text-only
model/data scope and ten-call / US$0.02 ceiling are already accepted.
Implementation fields below are bounded implementation choices, not new
robotics, model, cloud or perturbation decisions.

## Architecture and alternatives

Use the standard-library HTTPS client, existing offline kernel, immutable
case-local report JSON, and a later GET-only viewer read path. An SDK would
add dependencies/default retries; an overwrite-per-case report would lose
history. Neither is needed. No provider call on browser refresh, no chat,
no cloud controls, no source edits. Root alone runs any live call.

Authenticated read-only `/v1/models` succeeded on the approved global endpoint
October 5 and returned `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, not the lowercase
recipe spelling. Use this exact ID; never silently change model or region.
User reports a funded inference account; credit expiry remains unverified.
Catalog presence is not proof a generation succeeds.

## Transport and budget boundary

Fixed base `https://api.tokenfactory.nebius.com/v1/`; only GET `models` and
POST `chat/completions`. Verified TLS, redirects refused, no automatic retries,
direct HTTPS rather than forwarding credentials through environment proxies.
Twenty-second socket timeout; maximum response 262,144 bytes, read at most
one byte beyond the limit. No raw HTTP body, headers, key or traceback in logs
or artifacts. Fixed sanitized errors. Test injection is through a transport
callable, never a CLI arbitrary URL or mock-as-live option.

Read `NEBIUS_API_KEY` from process environment or explicitly selected `.env`.
Reject contradictory duplicate entries, malformed quotes, excessive secret
file size, symlinks, CR/LF and nonprintable keys. Never execute dotenv content,
expand variables or log values. The browser/server must never load a key.

Send only trusted fixed instructions plus `validate_evidence_packet` output.
Request compact JSON observations/hypotheses/limitations with evidence IDs,
explicitly state the final mask is not per-episode geometry or a global minimum,
and prohibit causal-proof claims. Limit request JSON to 6,000 UTF-8 bytes;
this is a byte bound, not an assertion of exact tokenizer counts. `max_tokens`
is 600; temperature 0; nonstreaming; request JSON-object mode. No unsupported
reasoning knobs or inferred model aliases. If output is truncated, malformed,
or unusable, preserve fallback and log that result rather than auto-retrying.

Start with one generation. Conservatively reserve the entire US$0.02 approval
before POST, retain it even on interruption/error, and never automatically
refund from estimated token cost. At published $0.06/M input and $0.24/M output,
the model's full 262,144-token context plus 600 generated tokens is $0.01587264
before any extra fees. This conservative reservation avoids pretending byte
length proves token counts. Ten is the authorized maximum, not a target:
this increment admits one paid attempt in the fixed pilot directory. No retry
or alternate pilot directory can reset that allowance. Additional calls require
explicit budget reconciliation/approval, not deleting the reservation.

Reserve exclusively in `artifacts/m5-nemotron-pilot/reservation.json` relative
to this checkout, using atomic create, fsync and no symlink traversal. The
reservation binds schema version, fixed cap, attempt number 1, case ID,
packet ID and exact model. A preexisting or malformed reservation refuses a
new POST. Local transport fixtures use temporary pilot roots; the CLI has no
pilot-root/cap/token/model/endpoint overrides. This is an application guard,
not an account-wide billing limit. Estimated usage is not reconciled billing.

Before paid execution root rechecks current published rates, funded-account
confirmation and source integrity; expiry unknown stays explicit. Extract
usage only from ordinary nonnegative integer counts; reject contradictory
totals, completion counts above 600 or a different returned model. Unknown
usage/cost stays null. Price calculations use Decimal, never label them billed.

## Immutable report contract

`explanation_store.py` provides `ExplanationStoreError`,
`make_stored_report(case_id, packet, report, provenance)`,
`validate_stored_report(value)`, `store_report(workspace, value)` and
`read_case_reports(workspace, case_id)`.

Exact record keys: `schema_version` (ordinary integer 1), `report_id`,
`case_id` (64 lowercase hex), `packet`, `report`, `provenance`.
`report_id` is SHA-256 of canonical sorted compact finite UTF-8 JSON excluding
itself; validate IDs rather than trusting filenames. Packet uses the reviewed
kernel. Report must exactly equal the kernel's recomputed absent, rejected or
validated-structure report: supplied facts/disclaimer/hash cannot override it.
Compare canonical bytes, not Python equality that confuses Booleans and ints.
Maximum stored record 65,536 UTF-8 bytes; duplicate JSON keys/nonfinite/cycles,
invalid fields, encoding errors and oversized input fail with fixed safe errors.

Provenance exact fields:

```text
source: offline | live
provider: null | nebius-token-factory
model: null | nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
endpoint: null | https://api.tokenfactory.nebius.com/v1/
created_at: UTC YYYY-MM-DDTHH:MM:SSZ
request_status: offline | completed | transport_error | http_error | invalid_response
error_code: null | authentication_failed | catalog_missing | timeout | http_error | invalid_response
latency_seconds: null | finite nonnegative number
prompt_tokens: null | ordinary nonnegative integer <= 262144
completion_tokens: null | ordinary nonnegative integer <= 600
estimated_cost_usd: null | finite nonnegative number <= 0.02
billed_cost_usd: null
reservation_usd: 0 (offline) | 0.02 (live)
```

Offline provenance has null provider/model/endpoint, no token/cost/latency,
status offline and null error. Live provenance has fixed provider/model/endpoint;
completed has null error, other statuses use a matching fixed error. Token
counts are both present or both null. Cost only when counts present, recomputed
from approved rates; no provider request IDs or arbitrary response metadata.
This is locally recorded provenance, not cryptographically certified provider
authenticity. Fixtures/offline reports cannot claim live invocation.

Store exclusively at `<case-workspace>/<case-id>/reports/<report-id>.json`,
only for a registered, freshly inspectable case with matching packet hash.
Reject symlink/reparse escapes and source changes; write atomically without
overwriting existing reports or changing case/source files. Repeated identical
records may return the existing path only after full validation. Read at most
100 reports, each bounded, and isolate corrupt entries. Return exact envelope
`{reports: [...], warnings: [...]}` with fixed non-private warnings.
For stale/missing source bindings, return no interpretations and a fixed warning.
Recompute current packet identity before accepting a report. Reports are not
automatically bundled into existing portable exports in this increment.

## CLI, viewer and review

`scripts/explain_case.py` offers `prepare` (offline artifact, no credentials),
`preflight` (authenticated catalog GET only) and `live` (explicit paid POST).
Accept `--workspace`, `--case-id` and `--env-file`; safe JSON stdout contains
case/report IDs, interpretation/request statuses and estimated cost only.
Validate/reinspect source before sending and after receipt before persistence;
if it changed, retain the spend reservation but do not attach stale prose.

Viewer later adds GET `/api/cases/<id>/explanations` and a small case-scoped
disclosure beneath existing evidence. Show deterministic facts separately from
“Nemotron interpretation — human review required”, modality text-only, recorded
model/provider, token/latency estimate and billed cost unknown. Evidence-ID
buttons navigate exact available episodes; unmatched/stale IDs never guess.
Absent/rejected/offline reports have honest labels. Select newest valid record
by timestamp then report ID; preserve stored history without a new dashboard.
Use textContent/native controls, no rendered HTML from model text. Browser
refresh calls only local GET. Preserve paired-video layout and nominal filter.

Unit tests never call providers or read real credentials. Root alone performs
the first real request after spec/quality reviews and fresh tests, then checks
actual stored artifact/usage and viewer behavior. Human review of interpretation
is still requested before turning it into a submission claim. M5C completion
requires real evidence-linked viewer output, not a fixture badge. M5B's adapter
and later fresh GPU cap remain separate gates; expanded M3 stays frozen.
