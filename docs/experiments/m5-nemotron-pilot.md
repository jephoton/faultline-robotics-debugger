# M5C Nemotron pilot — October 6, 2026

## Verified execution

Reviewed client, guarded CLI, immutable store and read-only explanation viewer
are integrated. Fresh Windows Python3.11 suite:578testsOK, four platform skips,
84.453seconds. The credential-fixture portability repair passed Linux CI at
`47ad012`; later integration still needs exact-head CI confirmation.

The real registered M4 case was revalidated. CLI `prepare` stored an explicitly
offline facts report, and `preflight --env-file .env` authenticated the fixed
model catalog without displaying credentials. One `live` attempt then used
the approved text-only packet and exact model
`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` on the global Token Factory endpoint.

- Input tokens:1,096; output tokens:600.
- Recorded request latency:8.703seconds.
- Request status:`invalid_response`; interpretation status:`absent`.
- Estimated token cost:US$0.00020976; billed cost remains unknown.
- Full US$0.02 reservation retained; no automatic retry/refund.
- Both reports are immutable, local, evidence-bound sidecars. The local HTTP
  read returned two reports and no source warnings; failed interpretation is
  not displayed as useful model analysis.
- All116original M4 evidence files are unchanged. Before/after aggregate
  SHA256 (sorted relative path:length:file-hash rows separated by LF):
  `9D02442C0197633398EB147D26E222EE6EDA90957E7609C0C2EA782687B98BD1`.

Rates were rechecked against the [official model page](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference):
US$0.06/M input and US$0.24/M output. Estimates are not posted charges.

## Interpretation and limits

The client accepted the exact returned model identity and token usage, but
rejected the completion/interpretation boundary. Using exactly the600-token
ceiling makes truncation the leading hypothesis. It does not prove the
finish reason or hosted reasoning default: the approved client did not retain
those details or raw generated text. Wrong model/invalid usage would not have
retained these counts. Output quality is therefore unassessed, not poor.

The browser automation tool failed to initialise its kernel assets twice,
including after reset. HTTP and Node-VM tests passed, but real375/768/1440px
browser QA for the new panel is pending. Do not reuse old M5A screenshots as
proof of new M5C UI checks.

## Accepted next decision — implementation/review gate remains

Recommend one further **US$0.02 maximum** attempt, with4,096 output tokens
and a90-second socket timeout on the same model, endpoint, packet and JSON
mode. At the observed1,096 input tokens, the output-cap estimate would be
US$0.0010488 before extras. Even the conservative full262,144-input-token
plus4,096-output-token calculation is US$0.01671168 before extras. Preserve
the previous reservation; use a separately approved fixed pilot directory,
never delete/refund the old marker or add an arbitrary CLI cap/path override.

Jethro approved the changed limit/timeout and additional cap on October6.
Root committed the [exact repair plan](../superpowers/plans/2026-10-06-m5-nemotron-bounded-repair.md) covering client/store usage bounds,
backward-compatible old sidecars, safe bounded failure diagnostics (no raw
text/headers), fresh reservation, tests and independent review. Root alone
executes the single next attempt after full-suite/preflight acceptance.
No paid GPU work is included. Another POST waits for implementation, independent
reviews and root acceptance; the old reservation remains consumed.

Alternatives: establish a documented hosted non-reasoning mode first (currently
unverified), or deliberately retain only deterministic reports and reconsider
the M5C product scope. Do not silently change models or use self-hosted-only
thinking parameters against the hosted service.
