# Judge-facing readiness audit — October 20, 2026

Generated audit, not organizer approval or a security certification. Source
snapshot: `171abae003a79093f986adacdcc04047659a714f` (application unchanged
from the October 20 published checkpoint). Findings below distinguish recorded
evidence, new checks, and work still requiring Jethro.

Independent spec/evidence and final quality reviews passed. Corrections
included explicit paid-execution disclosure, bounded README claims, exact
measurement citations and a history-heading link. Document target checks
passed for 180 links; the review also checked feedback/submission anchors.

## Current rules check

Sources checked October 20: [official rules](https://nebiusglobalaihackathon.devpost.com/rules),
[overview and judging](https://nebiusglobalaihackathon.devpost.com/), and
[organizer advice](https://nebiusglobalaihackathon.devpost.com/updates/46205-how-to-build-a-winning-project).

- Deadline: October 30, 10:00 PDT; October 31, 01:00 Singapore. Aim for October 29.
- Physical AI explicitly permits no-hardware projects: show at least one
  minute of key application modules operating. Our simulator interpretation
  fits this wording, not an organizer-specific approval.
- Runtime use can be Token Factory inference or named AI Cloud services.
  Actual GR00T Serverless Jobs and Nemotron calls provide both paths.
- Required materials include English description, public source with an
  open-source license and setup instructions, chosen track, tool feedback,
  and a public YouTube demonstration shorter than three minutes.
- Keep judge access free through December 15. Physical AI has a demo-URL
  exemption, but still requires a working, testable project.
- Eligibility, ownership and third-party rights require entrant confirmation.

The overview's four equally weighted criteria map to implementation,
coherent product design, credible audience/impact, and quality of idea.
The organizer advice requests explicit spoken Nebius/NVIDIA attribution and
specific onboarding/reuse feedback, not just logos.

## New repository checks

| Check | Observation | Limit |
| --- | --- | --- |
| Canonical repository | GitHub reports `jephoton/faultline-robotics-debugger` PUBLIC, MIT detected | No visibility/settings changes made |
| Latest main CI | [39283937968](https://github.com/jephoton/faultline-robotics-debugger/actions/runs/39283937968) completed successfully | Does not test real GPU provisioning |
| Fresh local checks | Clean snapshot: 3,166 unittest tests run, 63 skipped, exit 0; existing front-end environment: 336 tests and typecheck passed | Front-end dependencies were not reinstalled; existing non-failing React `act(...)` warnings remain |
| Portable documentation | Judge-facing local links checked; personal workstation paths found in two historical handoffs and removed | Historical generic remote/container paths remain contextual examples, not fresh setup instructions |
| Clean installation | See [clean-checkout audit](clean-checkout.md) | Same Windows host, isolated snapshot/venv; not a fresh-machine or paid cloud acceptance test |
| Public gallery | October 20 deployment checked all 40 served files, including 13 videos, plus unauthenticated browsing | Recorded results, not public execution; [publication record](../experiments/m7-public-gallery.md) |

README review found stronger claims than the data supports: globally smallest
triggers, automatic replay on every checkpoint and universal checkpoint
compatibility. The branch narrows these to bounded reduction and requested
replay on compatible checkpoints. No measured evidence is edited.

## Secret and dependency review

Gitleaks **8.30.1**, downloaded from its upstream GitHub release with archive
SHA-256 checked against the release checksum file, scanned a tracked-tree
archive and all locally reachable Git refs. Credential/private working files
were excluded by scanning the archive, not the live artifacts directory.
Raw, redacted scan reports stay ignored under `artifacts/`.

- History scan: **1,136 commits with scan content**, approximately 25.58 MB;
  seven generic-key findings.
- Tracked snapshot: approximately 7.76 MB; four generic-key findings.
- Triage: six historical findings (three still current) are simulator-state
  SHA-256 selectors under `videos.*.key`, not access credentials. The other
  is ordinary model-access/Token Factory planning prose. The source writes
  these selectors via `scenario_state.state_hash` and
  `scenario_experiment`'s video selection logic. No confirmed credential
  leak was found among these findings. No broad suppression rule was added.
- No tracked `.env`, private key, credentials store, SQLite database or
  Vercel project configuration was found by the filename check.
- GitHub API reports secret scanning and push protection **disabled**.
  This audit did not turn them on. Local scanning cannot assert the absence
  of all secrets, unrecognized formats, dangling Git objects or remote-only refs.

`npm --prefix web audit --omit=dev --json` reports **two moderate package
entries**, from two React Router advisories propagated to react-router-dom:

- [Open redirect advisory](https://github.com/advisories/GHSA-wrjc-x8rr-h8h6):
  requires attacker-controlled paths reaching navigation. Inspected app
  destinations are fixed internal prefixes with case/run identifiers;
  this is a limited reachability assessment, not an exploit proof or patch.
- [SSR hydration advisory](https://github.com/advisories/GHSA-337j-9hxr-rhxg):
  upstream excludes declarative routing. Faultline uses `BrowserRouter` and
  `createRoot`, without server-side hydration.

Installed React Router is 6.30.6; npm proposes a **major** upgrade to 7.18.4.
No automatic audit fix or routing migration was made during submission prep.
Keep this as dependency debt, not a clean vulnerability scan claim. Python
dependency vulnerability scanning and a penetration test were not performed.

## Rights and claim boundaries

Keep [NOTICE.md](../../NOTICE.md) and bundled third-party license texts with
the test build. The external HDF5 dataset's conflicting license metadata is
already documented; do not add that private source dataset to the gallery or
repository. Rendered scene assets retain upstream terms. The notices are not
a legal clearance of all derivative media; Jethro must confirm permitted use
before final publication/submission. No image/model-weight publication is
part of this audit.

The free gallery and bundled offline demo give judges an account-free evidence
path. New GPU experiments still require the user's own provider account and
model access. Do not describe that as free hosted execution. The rules' broad
testing-access language warrants making this distinction explicit in Devpost;
seek organizer clarification if they require unrestricted paid execution.

## Remaining gates

1. Supplied September 19–October 19 views now show AI Cloud $42.04 and Token
   Factory $0.13 including VAT. Review other dates and project filters only
   if making a lifetime/account-wide cost claim; one AI Cloud account was used.
   See [the period reconciliation](billing-reconciliation.md). Do not add
   overlapping session estimates.
2. Jethro confirms first-hand feedback and entrant/right-to-use declarations.
3. Review the draft story and timed video plan, then record/edit and check
   the actual final video's duration and at least one minute of module footage.
4. Approve the final public uploads/submission and preserve the judge build.

No GPU, Token Factory or Tavily calls, new cloud resources, hosting upgrade,
public redeployment or submission were made by this audit.
