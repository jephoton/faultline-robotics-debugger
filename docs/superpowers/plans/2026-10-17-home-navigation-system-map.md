# Home navigation and current-system explanation

**Scope:** Jethro clarified that the top main-content Back button always goes
home and requested a full-system diagram to understand the current three UI
choices. This is an accepted navigation correction and documentation of the
existing implementation, not approval to regroup modes or redesign execution.

**Ownership/concurrency:** Coordinator owns the minimal shell/test correction,
bundle build, architecture explanation and Git/server lifecycle. The current
architecture and flow will be independently reviewed against UI/orchestrator
source after drafting. No overlapping edits or paid provider calls. The earlier
smaller implementation worker reached its limit; this bounded correction is
completed by the coordinator rather than pretending the active model changed.

- [x] TDD: open a case, navigate to Setup, then click the top Back button.
  Require home rather than the previous case. Observe failure with old history
  navigation, then replace its handler with `navigate('/')`.
- [x] Keep home-page hiding, placement outside sidebar, static-mode behavior
  and the diagnosis wizard's separate previous-step buttons unchanged. Run
  focused/full web tests, type check and rebuild the committed bundle.
- [x] Extend the existing architecture handoff `docs/codex-handoff/PROJECT.md`
  with a numbered user-journey diagram and a deployment/data-flow diagram.
  Explain three implementation modes versus two user intentions, controls,
  imports, gates, model roles, valid no-failure endings and unsupported paths.
  Link actual source and distinguish current UI support from recommendations.
- [x] Verify real local navigation including non-home previous history; confirm
  server health. Review diagram syntax and facts; update STATE and commit
  separate UI and documentation units with Conventional Commits.

No public redeployment, new inference, simulation or cloud provisioning is
included. Proposed grouping of audit and paraphrase remains for Jethro's review.

**Verification:** the revised navigation regression failed against the old
history handler, then all 13 Shell tests and all 180 web tests passed with the
home handler; type check and production build passed. Real Chromium verified
case-to-guide-to-Back returns home, direct entry, main-not-sidebar placement,
home hiding, no page errors and no overflow at 375px. Server health passed.
Both diagrams parsed and rendered with Mermaid 11.12.0, and all architecture
document relative links resolved. Independent source review passed; no paid
provider call or public redeployment occurred.
