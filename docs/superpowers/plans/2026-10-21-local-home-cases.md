# Show all cases on the local home

Approved: match the public gallery's case-card list on the local home while
retaining active runs above it and the New diagnosis action. No changes to
cloud execution, sidebar filtering, evidence, static hosting or paid work.

Small sequential change, one integration owner; no independent substantial
tasks to delegate. Routine implementation follows the accepted UI choice.

1. Update home tests to require all library items as cards in local mode,
   retaining active-run/action behavior. Observe the expected failure first.
2. Replace Latest case with Cases and map the existing list, preserving
   loading, error and empty states. Update accessibility test heading anchors.
3. Run web tests/typecheck/build, committing the regenerated packaged assets
   with the source change so CI's bundle-consistency check remains valid.
4. Start the existing loopback server with artifacts/runs available; avoid
   restarting any active experiment. Verify live home cards and sidebar.
5. Record the local behavior in handoff, make a conventional commit and
   leave the server running for the owner's demo. No public redeploy or push.
