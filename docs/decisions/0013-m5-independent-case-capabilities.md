# ADR 0013: Independent case capabilities

**Status:** Accepted by Jethro on October 3, 2026, after the exact contract review.

## Decision

Represent inspection availability, complete replay inputs, exercised replay and
saved historical failure evidence independently. An import is not an experiment
and cannot promote itself to verified by trusting stored capability flags.

Missing runtime pins require explicit metadata with provenance; do not copy
current repository defaults into an older run. Initial M5A export is metadata
and, where complete, a structured recipe, not a bundle of videos or model assets.

## Rationale

A linear imported/ready/confirmed/reduced status conflates distinct questions.
Rejecting all incomplete cases prevents useful inspection. Independent
assessments retain incomplete evidence while explaining what is missing.
Confirmation requires source aggregate/summary reconciliation and matched
controls; recipe completeness does not prove execution or causal mechanism.

## Implementation boundary

Follow [the accepted contract](../superpowers/specs/2026-10-03-m5-case-contract-design.md).
Begin with the [pure schema kernel](../superpowers/plans/2026-10-03-m5-case-schema.md),
then source reconciliation and CLI persistence/export, then the read-only viewer.
The kernel alone cannot certify historical evidence. External restoration,
Nemotron calls and paid runs retain their separate gates. Expanded M3 is frozen.
