# ADR 0015: Immutable evidence-bound interpretations

Status: Accepted October 5, 2026, by Jethro's explicit design checkpoint.

Store each explanation as an immutable JSON sidecar bound to a registered case
and the canonical evidence-packet hash. Revalidate source evidence before
writing and reading. The viewer only reads local records; it never obtains a
provider key or makes inference requests. Changed source evidence hides stale
interpretations rather than silently rebinding them.

This preserves history without altering robot evidence. The alternative of
overwriting one report loses history; embedding generated prose into original
experiment files blurs the measured/generated boundary. Structural validation
and citations do not certify an interpretation's truth.

Implementation contract and plan:
- `../superpowers/specs/2026-10-05-m5-nemotron-sidecars-design.md`
- `../superpowers/plans/2026-10-05-m5-nemotron-integration.md`

The accepted ten-call / US$0.02 upper ceiling is conservatively reserved in full
for the first attempt; no automatic retry/refund or alternate-directory reset.
No cloud VM start is included.

October6 amendment: [ADR0017](0017-m5-bounded-nemotron-repair.md) specifically
authorizes one separate longer attempt after the first failed interpretation.
It does not permit arbitrary allowance resets; preserve the original marker.
