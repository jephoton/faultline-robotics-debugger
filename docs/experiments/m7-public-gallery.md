# M7a step 5: public gallery

## Result — October 17, 2026

Published and verified:
[Faultline gallery](https://faultline-robotics-debugger.vercel.app).
Jethro authorized publication after refreshing the handoff. The site is a
read-only export of recorded cases, not the local control panel and not a
hosted robot simulator. No new GPU Job, Nemotron generation or Tavily search
was performed for this publication; no paid hosting upgrade or domain purchase
was made. Hosting usage remains subject to the account's existing plan.

The existing exporter and committed React bundle were reused without a
production-code change. Payload source checkpoint: `2fa0603` (handoff refresh,
with application code unchanged from `9b39b5d`). The export holds **five cases,
25 videos and 56 deployment files**, totaling **2,658,394 bytes**, with no
omitted-case warnings. Vercel serves 55 content files; `vercel.json` is platform
configuration, not public content.

## Evidence scope

| Public case | What it shows |
| --- | --- |
| `FL-S-AFB5` | Independently imported LIBERO-10 failing start, reduced to five entity shifts; sizes retained conservatively, not a completed size minimum |
| `FL-A-A70E` | LIBERO-Object scene audit, no reproducible disturbance failure within range |
| `FL-A-08D3` | LIBERO-Goal nominal controls failed, so the audit correctly stopped |
| `FL-A-F526` | LIBERO-Spatial image-family audit, no reproducible failure within range |
| `FL-M-52D8` | Earlier occlusion reduction with its episode videos and research context |

The default export does not include run-only paraphrase results that registered
no case. Audit pages have their recorded outcomes and reports but no exported
audit videos. The M4 case shows its stored explanation fallback honestly;
research is context, not evidence. The scenario's saved case conservatively
retains full shift sizes although its historical report contains a later
successful 75% joint-offset candidate; the size search exhausted its budget.
Do not claim that every accepted shrink was promoted into that saved case,
that the report's size resolution was completed, or that a global minimum or
causal proof was established. Source experiment records were not rewritten.

## Privacy and static-mode acceptance

- Independent source/output review inspected the public projection, JSON,
  Markdown, bundle, media references and copied case files. No real cloud
  resource IDs, credentials, email addresses, user-specific paths, raw specs,
  backend logs/state, source maps or functions were found in the upload.
  Public case/evidence fingerprints and human Job labels are intentionally
  retained; they are not cloud resource identities.
- Exported session: `mode: static`, `controls: false`, `token: null`.
  All 15 JSON files parse and all 36 distinct referenced media URLs resolve.
- Vercel's final dry run enumerated exactly 56 reviewed files and explicitly
  excluded `.env.local`, `.gitignore` and `.vercel`. Linking a directory creates
  a local OIDC credential file automatically; it was not uploaded. Never deploy
  the repository or `artifacts/` wholesale.
- The website needs no Vercel login. Visitor checks verified all **55 served
  files byte-for-byte by SHA-256** against the reviewed export, including every
  MP4. Home, session and library return the expected content types over HTTPS.

Selected SHA-256 fingerprints:

| File | SHA-256 |
| --- | --- |
| `data/session.json` | `58ed714db2ecd1470913f1dccceb07ef4ca63d805781151d8146324913ad65d6` |
| `data/library.json` | `106db884d6a000ef7816d82691dfc1349529ea4dec46ecc564333002d521dcc2` |
| JavaScript bundle | `49b9655555151571191b4710cbc45e140c2668651ca2df3030d225107968ddc6` |

## Browser and local checks

- Existing export/library unit modules: **77 tests, OK** on Python 3.11.
- Unauthenticated Chromium: home → scenario link → direct-link refresh;
  all five case deep links load; the representative 256×256 robot video
  decodes and plays (26.05 s). Reports, guide and assets load.
- Direct `/new`, `/setup`, `/evidence` and `/run/not-a-real-run` routes expose
  no control forms. No state-changing requests or third-party requests were
  made by the tested journey; no page errors or unexpected failed HTTP
  responses were observed. The initial `/api/session` static fallback is
  expected and does not reach a provider.
- Layout checks at 375, 768 and 1440 px found no horizontal page overflow;
  screenshots were visually inspected. Dark-theme toggle and mobile-menu
  Escape behavior passed.
- Automated axe WCAG A/AA checks found zero violations on home, scenario and
  occlusion pages. Each of the two tested case pages had one incomplete check needing human
  judgment; this is not a claim of complete accessibility certification.
- CPU-only checks and publication did not rerun any robot experiment or change
  the recorded outcomes. Local screenshots and check scripts remain ignored
  under `artifacts/public-gallery-qa-20261017/`.

## Redeploy, October 18

Approved by Jethro to correct a false claim: the scene-goal case (control
failed, nothing searched) read "No failure up to severity 1" and "no failure
found" per family; it now reads "not tested". Fresh export
`artifacts/public-gallery-20261018/` (ignored): the same five cases and 25
videos, 56 files (the 55 before plus the bundle's `THIRD-PARTY-LICENSES.txt`),
static session with no controls. The dry deploy listed no `.vercel`, `.env` or
spec files. The production deployment is READY, and the public site serves the
new bundle and the corrected case without a login.

## Regenerate and publish safely

Use a fresh ignored output directory; do not overwrite original evidence or
deploy a linked directory without inspecting what will be uploaded:

```bash
faultline export --out artifacts/<fresh-gallery-dir>
vercel link --yes --project faultline-robotics-debugger --scope <your-scope> --cwd artifacts/<fresh-gallery-dir>
vercel deploy --dry --format json --scope <your-scope> --cwd artifacts/<fresh-gallery-dir>
vercel deploy --prod --yes --scope <your-scope> --cwd artifacts/<fresh-gallery-dir>
```

Inspect the dry-run file list, privacy guard, static session, media and case
count before the production command. Added cases or explanations change the
public payload and require a renewed publication review. No live API keys or
hosting environment variables are needed by the static site. The linked
project's local metadata/credential files must remain excluded.

The installed CLI was Vercel 54.20.1 on Node 24.12.0. Its initial TLS connection
failed until the process used `NODE_USE_SYSTEM_CA=1`, trusting the workstation's
system CA store; TLS verification remained enabled. This is local Node trust
configuration, not a Nebius or NVIDIA defect. See
[Node system-CA guidance](https://nodejs.org/learn/http/enterprise-network-configuration)
and [Vercel deployment commands](https://vercel.com/docs/cli/deploy).

M7a is complete. Next is M7b: submission story, video, judge-facing setup/repo
audit, required feedback and billing reconciliation. New paid experiments or
public image publication remain separate decisions.

## October 19 redeploy: the showcase cases

Jethro gave the go on October 19. The export `artifacts/public-gallery-20261019`
(ignored) holds **three cases and 13 videos** (13 MB):
- `FL-S-8E0D`: the layout route;
- `FL-A-D582`: the probe route;
- `FL-A-F526`: nothing broke it.

It was made with `faultline export --case <id>` for each case.
- **Payload checks:**
  - static session (`controls: false`, no token);
  - no provider ids, keys or local paths in any JSON, Markdown, HTML or text
    file;
  - research shown only as our summary plus source titles and links.
- **Production deploy** to the existing project. The live site shows only
  these three cases, with the bullet results, videos and **Still fails**
  regression results naming the checkpoint tested, and no console errors.
- **Removed from the public gallery:** `FL-S-AFB5`, `FL-A-A70E`, `FL-A-08D3`
  and the September occlusion case. In the local control panel they moved to
  `artifacts/archive-2026-10-19/`, which is not deleted and can be restored.
