# Final submission and version-freeze checklist

Prepared October 21, 2026. This is a procedure and checkpoint record, **not an
executed release or submitted entry**. No push, tag, deployment or form change
is authorized by writing it. The project owner handles media; do not request
another screenshot/cover/video review by an agent.

## Verified checkpoint

**October 21 publication update:** the owner approved adding FL-L-C72C. The
gallery now has four cases, including the passing wording screen, and the same
13 videos. Deployment `dpl_7f7eowiSoNKY8TGYTwwRwAJvbsHq`; all 42 served files
match the fresh export. See the [publication record](../experiments/m7-public-gallery.md).
The three-case HTTP/text fingerprints below record the earlier pre-redeploy
check and must not be mistaken for current library fingerprints. The final
source SHA still awaits approved GitHub integration.

| Item | Verified state |
| --- | --- |
| Public repository | `jephoton/faultline-robotics-debugger`, public; MIT detected |
| Public main SHA | `257c130df213a9d5365e2e50b93dc6c53b54fb7e` |
| Latest main CI | [39283937968](https://github.com/jephoton/faultline-robotics-debugger/actions/runs/39283937968), completed successfully at that SHA |
| Local starting SHA for this check | `1ff75472784329a4ae7b8404156661eb22d8ea87`, branch `codex/submission-readiness`; 15 commits ahead of fetched main |
| Runtime changes relative to main | Two comment-only edits in `token_factory.py`; other pending changes are documentation, not a new app release |
| Gallery | [Production URL](https://faultline-robotics-debugger.vercel.app/), anonymous HTTP 200 |
| Gallery routes/data | All three case routes and their JSON detail documents returned 200; JSON parsed successfully |
| Static boundary | Session reports `mode: static`, `controls: false`, `token: null`; library has three cases and no warnings |
| Story/media | Story approved; screenshots and cover completed, per project owner. Video in progress; no media inspected in this check |

The public README, LICENSE, NOTICE and diagnosis quickstart URLs also returned
200 without credentials. These are HTTP/data checks, not a fresh browser,
video playback, security or installation audit. Earlier install, UI and media
checks remain dated evidence in the [readiness audit](readiness-audit.md).

Gallery fingerprints below are SHA-256 of the fetched response text re-encoded
as UTF-8, not a new whole-deployment binary inventory:

| Path | SHA-256 |
| --- | --- |
| `/` | `cdff47027d3eae6a4cf7965f3d6abd286c2f7ec003639a8dcaf744e2db7bff66` |
| `/data/session.json` | `58ed714db2ecd1470913f1dccceb07ef4ca63d805781151d8146324913ad65d6` |
| `/data/library.json` | `4f912ed1c1c184b3a9d85cfeea79aa3e0ca38f5c279300ba67e5aa57c3003579` |

Preserve the October 21 four-case gallery deployment and its existing
[publication record](../experiments/m7-public-gallery.md). Its source application
checkpoint remains `5f23cae`; the additional export was made at `3ed9654`,
not the future submission-document SHA. A docs-only
integration does not require exporting or redeploying the gallery.

## 1. Finish the form — project owner

- [x] Approve the [story](devpost-draft.md).
- [x] Produce screenshots and cover (owner-confirmed).
- [ ] Confirm Built With tags and select Physical AI in the form.
- [ ] Choose the three subjective questionnaire ratings and approve/paste
  the [nine feedback answers](nemotron-feedback-draft.md).
- [ ] Finish the video and supply its **public YouTube URL**. The owner is
  responsible for checking under-three-minute length, at least one minute of
  operating application modules, spoken Nebius/NVIDIA attribution and rights.
  No agent media review is requested.
- [ ] Confirm eligibility, rights/attributions and any required prior-project
  disclosure. Do not make personal attestations on the owner's behalf.

## 2. Integrate and freeze — only after publication approval

1. Inspect the branch diff and clean status; preserve unrelated work. Confirm
   the approved feedback/draft content is intended for a public repository.
2. Check `gh auth status`; integrate `codex/submission-readiness` into main
   without force-pushing or rewriting history, then push using the approved
   Git workflow. Do not publish temporary evidence, secrets or private media.
3. Wait for CI **on the new main SHA**. The old successful run above does not
   certify the new commit. Fix or disclose failures before freezing.
4. Record full final main SHA, CI URL and gallery publication checkpoint in
   the receipt below. Do not invent a release tag; a full commit SHA is enough.
5. Check the final public README, LICENSE, setup and feedback pages after
   integration, using unauthenticated requests. Keep gallery and offline demo
   accessible; new GPU diagnoses require the operator's own paid account.

No cloud run, model call, paid revalidation, new hosting or gallery redeployment
is needed for this documentation integration. If code/evidence changes later,
reassess verification rather than reusing an old acceptance result.

## 3. Submit and retain — project owner approval required

- [ ] Reopen [official rules](https://nebiusglobalaihackathon.devpost.com/rules)
  immediately before submission; the October 21 check is not a guarantee that
  requirements will not change.
- [ ] Use the gallery and public repository in Try it out; use the actual
  public YouTube link in Demo video, not the gallery link.
- [ ] Confirm final form contents, then explicitly authorize submission or
  submit directly. Saving a draft is not final submission.
- [ ] Save the submitted entry URL and confirmation timestamp without
  secrets or unnecessary personal data. Record final versions below.
- [ ] Keep judge access available through the end of judging:
  **December 15, 2026, noon PST / December 16, 04:00 Singapore**.

Deadline: **October 30, 2026, 10:00 PDT / October 31, 01:00 Singapore**.
Target October 29 to leave a buffer. The broad free-testing requirement and
Physical AI demo-URL exemption do not amount to organizer approval of any
specific access arrangement; clearly disclose recorded/offline versus paid
execution rather than promising free hosted GPU jobs.

## Final receipt — fill only when verified

- Final public source SHA: pending approved integration.
- CI URL/result for that exact SHA: pending.
- Gallery URL: https://faultline-robotics-debugger.vercel.app/
- Gallery deployment record: October 21, `dpl_7f7eowiSoNKY8TGYTwwRwAJvbsHq`;
  four cases, application checkpoint `5f23cae`, export source `3ed9654`.
- Public YouTube URL: pending owner.
- Devpost entry URL and submitted timestamp: pending owner approval/submission.
- Final rules/link check date: pending immediately-before-submit check.
