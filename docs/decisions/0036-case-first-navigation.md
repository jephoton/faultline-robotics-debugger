# ADR 0036: Case-first navigation, without a global evidence page

- Status: accepted by the project owner, October 19, 2026.
- Context: the unified diagnosis pipeline makes engine-based sidebar groups
  confusing. A proposed replacement with small type labels adds taxonomy
  without helping the demonstrated workflow. The global episode browser has
  not established a separate user need and exposes historical scan warnings.
- Decision: use one Cases list, with name, fault code and outcome; no type
  headings or badges in case navigation/gallery cards. Keep method and tested
  conditions in the case itself. Remove All evidence from product navigation
  and routing, rather than replacing it with an advanced page.
- Preservation: retain per-case Full evidence, original files, archive copies,
  kind fields and internal evidence APIs. No evidence deletion or algorithm
  change follows from this decision.
- Demo: restore the existing FL-L-C72C wording result locally. All four
  rewordings passed their single screening attempt; nothing was reduced.
  Do not run a paid test just to populate navigation or imply a wording failure.
- Consequences: fewer navigation concepts and a case-centered evidence trail.
  Cross-case analysis may be reconsidered if a concrete workflow needs it;
  removal of a global page is not a claim that aggregate analysis is useless.
- Publication: these changes do not authorize a new public export/deployment.

Implementation: [bounded plan](../superpowers/plans/2026-10-19-simplified-case-navigation.md).
