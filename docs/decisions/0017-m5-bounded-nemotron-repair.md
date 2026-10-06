# ADR 0017: One separately approved longer Nemotron attempt

Status: Accepted October 6, 2026, by Jethro's explicit reply.

The first real Nemotron attempt returned1096input/600output tokens and no
valid interpretation. Truncation is plausible, not proven: no finish reason
was retained. Preserve its immutable fallback and full consumed reservation.

Authorize exactly one new US$0.02 attempt on the same exact model, endpoint,
metadata-only evidence packet, prompt and JSON mode, with4096output tokens
and90-second socket timeout. No GPU start, model swap, automatic retry,
undocumented hosted thinking option or additional data sharing is included.

The [repair plan](../superpowers/plans/2026-10-06-m5-nemotron-bounded-repair.md)
fixes the new reservation path at `artifacts/m5-nemotron-pilot-repair-20261006`.
This is a specifically approved new allowance, not a general permission to
reset consumed markers. Keep `artifacts/m5-nemotron-pilot` untouched. Repeated
invocations must refuse before POST after the new marker exists, even partial.

This narrowly amends ADR0015 and the October5 sidecar/client specification:
completion usage may be0–4096, and invalid_response may carry fixed
`output_limit` only for a trusted exact-model/usage/single-choice length result.
Old reports remain valid with unchanged identities; schema/key set stays the
same. No raw body, reasoning text, headers or arbitrary diagnostics are stored.
Request/response byte bounds, source revalidation, immutable store and read-only
viewer remain unchanged. Socket timeout is not a hard overall time deadline.

Alternatives were retaining deterministic reports only or first investigating
a documented hosted non-reasoning mode. The chosen experiment directly tests
the leading output-budget hypothesis without changing the project model.
Another failed output does not authorize another request; reassess with Jethro.
Recorded costs remain estimates until billing is reconciled. Useful output
still needs human interpretation review and viewer acceptance.
