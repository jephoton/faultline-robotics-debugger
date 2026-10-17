# Main-content back button

**Scope:** Routine green follow-up to the accepted control-panel UI. Jethro
requested a back button at the top left of the main content, excluding the
sidebar, and restoration of the local server. No provider calls or new design
system, hosted execution or paid work.

**Behavior:** A compact accessible `Back` button above page content on non-home
routes, inside the existing main-content column. Use existing button styling
and a decorative left arrow. Navigate one step back within app history when
available; on a fresh direct entry, navigate to `/` rather than leaving Faultline.
The home page has no back button. Local panel and exported gallery share it.

**Ownership:** A smaller implementation agent owns `web/src/components/Shell.tsx`,
`Shell.test.tsx` and minimal existing icon/style changes only if needed. The
coordinator owns server startup, review, bundle build, verification, handoff and
Git integration. These can proceed independently; no overlapping source edits.

- [ ] Write failing tests for main-not-sidebar placement, previous-route
  navigation, direct-entry home fallback, hidden-on-home and static-mode use.
- [ ] Implement the minimal shared-shell button. Run its focused tests,
  the complete web suite and type check; preserve focus/menu behavior.
- [ ] Rebuild `src/robot_debug/viewer/app/`, review the diff and verify the local
  server and rendered button at desktop/mobile widths. Test back and fallback
  with a real browser; no cloud controls are clicked.
- [ ] Update the current handoff and commit source/tests/bundle as
  `feat(ui): add back navigation above main content` after checks.

The public gallery deployment remains the reviewed version until a separately
inspected fresh export is deployed; a local UI request alone is not a new
publication decision or provider-spending allowance.
