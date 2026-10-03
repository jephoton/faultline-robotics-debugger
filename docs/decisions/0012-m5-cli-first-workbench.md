# ADR 0012: CLI-first case workbench

**Status:** Accepted by Jethro on October 3, 2026.

## Decision

Keep the existing loopback viewer read-only. Local CLI operations register
supported case evidence and export validated metadata/recipes. Paid execution
and provider calls require separately approved paths and budgets; the viewer
does not launch them.

## Rationale and alternatives

This completes an evidence-to-regression workflow using the working viewer
without making cloud lifecycle infrastructure an MVP dependency. Browser
uploads/write endpoints would add request and filesystem security work; a full
cloud job dashboard would revive expanded M3, which is frozen. Both are outside
the accepted first increment. A later browser interaction can reuse validated
case services after a separate decision.

## Boundaries

- M5A is offline existing-case inspection/readiness/export.
- M5B external state restoration and M5C Nemotron explanations remain gated.
- The exact case schema/capability contract is **proposed**, not accepted by
  this ADR. Review [the A1 contract](../superpowers/specs/2026-10-03-m5-case-contract-design.md)
  before importer or dependent UI implementation.
- Preserve equal evidence panels and one representative nominal by default.
- Expanded M3 remains optional stretch under [ADR 0011](0011-freeze-expanded-m3.md).

Execution is scoped by [the M5 plan](../superpowers/plans/2026-10-03-m5-case-workbench.md).
