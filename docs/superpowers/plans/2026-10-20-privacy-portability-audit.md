# Privacy and portable documentation cleanup plan

> **For agentic workers:** Independent documentation cleanup and read-only
> privacy audit, followed by coordinator verification. No paid work or push.

**Goal:** Remove unnecessary owner identification and personal paths from the
tracked release tree, and rename the feedback heading to “First-hand notes”.

**Architecture:** Preserve public repository links, intentional copyright and
third-party attribution, evidence identities and safety-critical runtime
contracts. Personal references in narrative docs become “the project owner”.
Historical home-directory examples become explicitly labeled placeholders;
fake privacy-test inputs remain test inputs, not real personal data.

**Tech stack:** Git tracked-file inventory, local text checks, Gitleaks,
Markdown link/anchor verification and focused Python tests.

## Scope and authority

The user requested this cleanup on October 20 and approved the remainder of
FEEDBACK. Green: text anonymization, personal-data inspection, local checks.
Amber: preserving generic service-account paths as runtime contracts rather
than weakening existing containment checks. Red: rewriting Git history,
changing licensing/attribution, provider settings, publication and spending.
Do not inspect private credential stores or copy ignored artifacts into docs.

## Ownership and concurrency

```text
committed plan
  +-- Luna writer: tracked Markdown anonymization + placeholders
  +-- independent auditor: read-only tracked tree + exposure triage
  +-- coordinator: code comments, scanner, tests, Git and integration
        -> link/meaning/privacy review -> local commit and handoff
```

The writer owns tracked Markdown only, excluding this plan and LICENSE.
The auditor edits nothing. The coordinator waits for the writer before
updating shared handoff docs. No agents commit, publish or mutate cloud state.

## Tasks

- [x] Writer: replace narrative first-name references with a neutral role in
  tracked Markdown, including AGENTS, ADRs, histories and feedback. Preserve
  decisions, budgets and approval meanings. FEEDBACK heading must be exactly
  `## First-hand notes`; fix all links to that heading. Keep its bullet text.
- [x] Writer: replace literal home-directory paths in historical Markdown
  commands with marked `<guest-home>`/`<wsl-home>` placeholders and explain
  that these are historical templates requiring substitution. Do not edit
  source code, generated bundles, evidence files or copyright attribution.
- [x] Auditor: inspect tracked source/docs/config/media metadata for personal
  emails, workstation names, personal home paths, identifiers and credentials.
  Report file/line/category without echoing sensitive values. Distinguish
  synthetic tests, upstream attribution and intentional public repo identity.
- [x] Coordinator: remove two owner-name source comments without changing
  executable behavior. Keep fake privacy-test strings and the legacy generic
  service layout: changing safety-critical launcher semantics is not required
  to remove personal identity. Record this exception explicitly.
- [x] Coordinator: check all changed local link targets/heading anchors,
  instruction meaning, no remaining narrative owner-name references, copyright
  preservation, and `git diff --check`. Run focused packet/export/demo tests.
- [x] Coordinator: scan the tracked snapshot with redacted Gitleaks output;
  preserve false-positive triage and scanner limitations. Do not claim a
  guarantee of no sensitive data or remove real evidence because of hashes.
- [x] Independent final review: verify scope, headings, links, preserved
  first-hand content and separation of synthetic/service paths from actual
  personal paths. Escalate any confirmed secret or sensitive identifier.
- [x] Coordinator: update STATE with feedback approval and audit scope,
  make atomic Conventional Commits and leave the branch local. Historical
  copies already in Git or a deployment are not erased by a working-tree edit.

## Acceptance

No direct owner name in feedback/narrative documentation or source comments.
Intentional MIT copyright/public repository attribution remains. No actual
personal email, workstation path or other confirmed sensitive identifier in
the checked current tree. Home-path fixtures and legacy service contracts are
explicitly classified, not misrepresented as personal data. No Git-history
rewrite, runtime/security-policy change or public deployment is performed.

## Verified execution

135 existing Markdown files were anonymized or had links/placeholders updated;
the feedback heading is neutral and its approved bullet text is unchanged.
Two source comments changed; AST comparison confirms executable behavior is
unchanged. LICENSE attribution is unchanged. The independent review caught two
distorted historical copyright descriptions, now corrected to reference LICENSE.

116 focused tests passed. All 202 checked local targets/anchors resolve and
`git diff --check` is clean. The 583-file tracked snapshot included all 12
packaged viewer files. Gitleaks' four hits were reviewed state-hash selectors
and planning prose; media/font screening was limited to printable strings.
The privacy report states current-tree scope and all exceptions explicitly.
Independent final review passed. Feedback is approved; remaining submission
gates are story/video review, final assets, rights/entrant declarations and
approved publication. The branch remains local; no history or deployment change.
