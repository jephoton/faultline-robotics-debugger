# Post-cleanup gallery redeployment

**Authority:** Jethro's October 20 request to carry on without more decisions
authorizes publication of the already-reviewed three-case static gallery to
the existing Vercel project. It does not authorize new robot/model runs,
hosting upgrades, a new domain, additional cases or repository visibility changes.

**Approach:** reuse `artifacts/public-gallery-20261019-cleanup-final/` and the
existing project association. One inline owner performs checks, publication,
visitor verification and Git; no new architecture or parallel resource owner.
This is execution of the accepted gallery design, not a new product step.

1. Verify clean main/green CI, installed CLI identity and the exact prior site.
2. Check the export matches the committed bundle; require only FL-S-8E0D,
   FL-A-D582, FL-A-F526, 13 videos, static mode/no controls/token and privacy
   guards. Save a local file/checksum manifest. Do not upload raw artifacts.
3. Copy only the existing `.vercel/project.json` association. Use explicit
   `.vercelignore` rules excluding credentials and local deployment metadata;
   inspect the CLI dry-run upload list before production deployment.
4. Deploy to the existing project, with normal TLS verification and a
   process-local system-CA setting if needed. Preserve the prior deployment
   URL for rollback. Stop if sign-in, paid upgrades or project identity is unclear.
5. As an unauthenticated visitor, verify remote file hashes, case deep links,
   playable video metadata, rewritten docs, updated D582 suggestions, F526
   tables, unified navigation and absence of controls. Browser checks must
   reject provider/run mutations and report actual limitations.
6. Record the deployed source, payload counts, scope and acceptance in
   `docs/experiments/m7-public-gallery.md`, handoff/roadmap and FEEDBACK.
   Commit as `docs(gallery): record reviewed cleanup redeployment`, verify
   GitHub identity, push and check CI. No timestamp-only follow-up required.

No billing reconciliation, rules audit, submission writing/video or final
submission is performed just because this publication is approved.
