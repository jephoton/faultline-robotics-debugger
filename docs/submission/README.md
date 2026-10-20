# Submission preparation

Working package for human review, not an already submitted entry.

- [Readiness audit](readiness-audit.md): current rules, repo/security checks,
  evidence limits and remaining gates.
- [Clean-checkout test](clean-checkout.md): installation and offline-demo
  checks in a fresh Python environment.
- [Devpost draft](devpost-draft.md): marked paste-ready About the project story,
  separate Built With tags, Try it out links and image/video field guidance.
- [Video plan](video-plan.md): timed pitch and shot list using existing evidence.
- [Billing reconciliation](billing-reconciliation.md): September 19–October 19
  service totals and remaining per-run/lifetime scope limits.
- [Privacy audit](privacy-audit.md): neutral documentation, tracked-tree
  checks, intentional attribution/fixture exceptions and history limitations.

## What the project owner still needs to supply or approve

| Item | Needed input | Current position |
| --- | --- | --- |
| Billing | Review scoped totals; provide other dates only if claiming lifetime spend | September 19–October 19: AI Cloud $42.04 + Token Factory $0.13 = $42.17 including VAT. Only one AI Cloud account used; project filters/currency code not visible. $0.82 remaining is not usage or a spending allowance |
| Feedback | [Approved first-hand notes](../../FEEDBACK.md#first-hand-notes) | User approved the feedback; personal-name heading removed and note text preserved |
| Video | Approve/edit script and select narration approach | Timed draft only, no finished video or public YouTube link |
| Cover | Approve a cover derived from the app after the final story is settled | Not produced; no image-generation spend approved |
| Submission | Confirm track, entrant eligibility, rights/attributions and final content; approve public uploads and submit | No Devpost fields changed or personal attestations made |

## Billing worksheet (do not sum these rows)

| Evidence | Amount | Treatment |
| --- | --- | --- |
| [October 19 showcase](../experiments/m7-final-showcase.md#spend) | US$3.87 estimated | Includes two diagnoses and their replays; not total project spend |
| Earlier unverified subtotal in the [historical handoff](../codex-handoff/STATE.md#previous-handoff-october-19-evening-superseded-by-cleanup-above) | About US$8.21 | Potentially overlapping sessions; match date/resource scope before adding anything |
| October 19 Nemotron repair | Two attempts; 6,973 prompt and 472 completion tokens | US$0.04 reservation envelope, not actual bill |
| Earlier Token Factory estimates | Approximate daily summaries | Not reconciled; may overlap the repair above |

Use posted charges, not credit purchases or remaining balances. Separate AI
Cloud GPU, storage, egress/tax and Token Factory inference where billing makes
that possible. The earlier intended two-account split was not actual usage:
The project owner confirmed only one AI Cloud account was used. Report any
unmatched total transparently rather than forcing it to agree with estimates.
No credentials, account IDs or invoice/payment details belong in this file.

## Final pre-submit check

- [x] Confirm feedback and record billing totals only for the supplied period.
- [ ] Review source/model/media attributions and entrant declarations.
- [ ] Approve the Devpost story and Built With list.
- [ ] Produce and review the actual video and cover; confirm public YouTube URL.
- [ ] Recheck final rules, repository/gallery/video links without authentication.
- [ ] Pin submission source/deployed version and retain free judge access.
- [ ] Submit with the project owner's explicit approval; save confirmation without secrets.

Audit implementation lives on `codex/submission-readiness`; draft content
has not been uploaded to Devpost, YouTube or a new gallery deployment.
