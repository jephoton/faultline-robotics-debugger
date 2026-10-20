# Judge-facing readiness audit — October 20, 2026

Generated audit, not organizer approval or a security certification. Source
snapshot: `171abae003a79093f986adacdcc04047659a714f` (application unchanged
from the October 20 published checkpoint). Findings below distinguish recorded
evidence, new checks, and work still requiring the project owner.

Independent spec/evidence and final quality reviews passed. Corrections
included explicit paid-execution disclosure, bounded README claims, exact
measurement citations and a history-heading link. Document target checks
passed for 180 links; the review also checked feedback/submission anchors.

## Current rules check

### October 21 recheck and public access

Later on October 21, the owner approved adding the saved rewording example.
The public gallery now has **four cases**, not three, with the existing
13 videos. All 42 served files matched the fresh export, and a focused browser
check verified the wording table and navigation. See the
[publication record](../experiments/m7-public-gallery.md). The earlier
three-case check below is retained as dated evidence. No fresh robot/model
run was required; this does not publish the local readiness branch to GitHub.

Reopened the official rules and overview. The deadline remains October 30,
10:00 PDT; judging ends December 15 at noon PST (December 16, 04:00 Singapore).
The rules still explicitly allow a Physical AI project without hardware to
show at least one minute of key application modules operating. They require
a public YouTube video under three minutes; the form's Vimeo/unlisted options
do not override that specific requirement. Public code, license, setup,
model/platform use and feedback remain required. This is a textual alignment
assessment, not organizer approval or an entrant eligibility determination.

Unauthenticated HTTP checks returned 200 for the repository, public LICENSE,
README, NOTICE and setup guide, gallery root, all three case routes and their
JSON detail documents. The gallery session still disables controls and the
library lists exactly the three showcase cases without warnings. No footage,
image or fresh browser review was performed, as requested by the project owner.
The web text extractor could not render the gallery, so direct anonymous HTTP
and JSON checks supplied the access evidence instead.

Fetched main remains `257c130df213a9d5365e2e50b93dc6c53b54fb7e`, with successful
CI run 39283937968; GitHub still reports PUBLIC and MIT. The local readiness
branch is not integrated/pushed. See the [freeze/checklist](final-checklist.md)
for the exact checkpoint, fingerprints, pending integration and final receipt.

### October 20 original check

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
a legal clearance of all derivative media; the project owner must confirm permitted use
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
2. Feedback is approved, with a neutral heading and unchanged note text.
   Entrant/right-to-use declarations remain for the project owner.
3. Story is approved and screenshots/cover are completed, per the project
   owner. Video remains in progress; the owner handles media compliance, with
   no further agent media review requested. Questionnaire ratings/answers and
   Built With tags still need owner confirmation.
4. Approve public integration/push of the local readiness work, check CI on
   the final SHA, complete the final rules/link check once the video URL is
   available, approve submission and preserve the judge build. Use the
   [final checklist](final-checklist.md); no release was created by this audit.

No GPU, Token Factory or Tavily calls, new cloud resources, hosting upgrade,
public redeployment or submission were made by this audit.
