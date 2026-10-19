# Current-tree privacy audit — October 20, 2026

Generated evidence summary, not a guarantee or formal SPII certification.
The user requested neutral feedback attribution and a check for sensitive
personal information and personal workstation paths.

## Changes

- Feedback heading is **First-hand notes**. The rest was approved by the
  user; its two first-person bullet paragraphs are unchanged.
- Narrative personal-name references were replaced by a neutral project-owner
  role across historical plans, decisions, handoffs and collaboration docs.
  Approval authority, budgets and experiment conclusions were preserved.
- Historical guest/WSL home examples now use marked placeholders, with a note
  that they require substitution. A new AGENTS privacy policy discourages
  future unnecessary personal details.
- Two source comments were anonymized. An AST comparison confirmed the
  executable Token Factory module is unchanged.

## Checked surface and evidence

- **583 tracked files** in the audit snapshot, including committed demo data
  and all **12 packaged viewer files**: hashed JavaScript/CSS, HTML, SVG,
  seven fonts and third-party notices. The final review note adds no private
  data and raw scanner output remains ignored.
- Tracked-text checks found no personal email, actual owner home path or
  workstation-name match. The owner's name remains only in the intentional
  MIT copyright, not narrative docs or source comments. Canonical public
  repository links are intentionally retained.
- Five email-shaped matches were synthetic test inputs. Government-ID,
  card/phone/address and network-address checks produced no confirmed
  sensitive personal finding; hash/UUID, version and test matches were
  distinguished from actual identifying data.
- Legacy VM scripts retain a generic service-home contract and its containment
  checks. Tests intentionally contain fake Windows/Unix paths to verify
  redaction and traversal rejection. These are not actual personal paths;
  this cleanup does not claim the old VM launcher is universally portable.
- Gitleaks **8.30.1** scanned the current tracked-file snapshot, approximately
  **7.82 MB**. It exited 1 with **four** generic-key findings: three known
  simulator-state SHA-256 video selectors and one planning-prose match.
  These were reviewed, not suppressed. No confirmed credential was found in
  those findings. No broad allowlist was introduced.
- **116 focused Python tests passed** (Token Factory, scenario packet,
  viewer export, bundled demo and cloud run records). Markdown link/heading
  checks passed for **202** local references. `git diff --check` and the
  independent final review passed. Numeric-content comparisons preserved
  budgets/results across the mechanical edits; two historical copyright
  descriptions now refer to LICENSE rather than restating the name.

## Boundaries

Ignored artifacts, credential stores and unrelated user directories were not
inspected or published. Media/font screening searched printable metadata
strings; dedicated EXIF/video metadata tools were unavailable, so hidden or
encoded metadata is not certified absent. This is not a penetration test.

**Git history, author metadata and the deployed website were not rewritten.**
Old public commits can still contain historical names/paths. Removing an
actual sensitive historical disclosure would require separate assessment and
authorization for rotation/history cleanup, not merely editing current files.
No confirmed disclosure requiring that action was found in this current-tree
review. The earlier history secret-scan scope remains documented in
[the readiness audit](readiness-audit.md#secret-and-dependency-review).

Changes are local to `codex/submission-readiness`; no push, new cloud/model
call, deployment or provider-setting change was performed.
