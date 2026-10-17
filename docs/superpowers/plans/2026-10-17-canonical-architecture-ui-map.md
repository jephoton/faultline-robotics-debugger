# Canonical architecture and UI coverage plan

> **For agentic workers:** Use executing-plans for the documentation tasks.
> This is a user-requested explanation/documentation step, not UI implementation.

**Goal:** Create `docs/architecture.md` as the canonical system explanation,
clarify two product modes versus three execution paths, and enumerate the UI's
actual controls, evidence and limitations.

**Architecture:** Consolidate the existing architecture material rather than
maintaining two competing full-system maps. Keep `docs/codex-handoff/PROJECT.md`
as a short handoff entry point linking to the canonical document. Document
current behaviour separately from any proposed information architecture.

**Tech Stack:** Markdown, Mermaid; source inspection of React UI and Python
coordinator. No runtime change, package installation, provider call or deployment.

## Ownership, dependencies and autonomy

```text
Coordinator: source/ADR review + canonical-document consolidation
    || read-only UI audit agent: page/field/action/evidence inventory
    -> coordinator integrates inventory and explains tradeoffs
    -> independent documentation/source review
    -> link/diagram/diff verification -> atomic documentation commit
```

The coordinator owns all file edits and Git operations. The audit/review agent
is read-only and reports paths and findings, with no overlapping writes. Use a
smaller capable model for this bounded inventory per project handoff policy.
All documentation maintenance is Green. Choosing a new UI grouping remains Red:
explain alternatives, recommend one, and await Jethro before changing UI code.

## Tasks

- [ ] Inspect ADRs 0027/0032/0033 and UI source. Distinguish product Mode 1
  (`scenario`) from Mode 2 (audit intention, implemented as `audit` or `paraphrase`).
- [ ] Create `docs/architecture.md`, carrying over the reviewed diagrams and
  source anchors with corrected relative links. Add a short glossary, mode
  examples, shared versus mode-specific algorithms, technology responsibilities
  and an inventory of what every current UI page actually exposes.
- [ ] Present wording as an audit subtype with a different search engine;
  explain why neither removing its separate implementation nor silently making
  it part of the numeric-family selector follows from that product grouping.
  Mark any recommended UI change as proposed, not implemented.
- [ ] Replace `docs/codex-handoff/PROJECT.md` with a concise architecture pointer
  and stable product/operating boundaries; update `STATE.md`, `docs/README.md`
  and root `README.md` entry links. Preserve historical plan/ADR links.
- [ ] Independently review actual source against the UI coverage claims; run
  Markdown relative-link checks, Mermaid parse/render and `git diff --check`.
  No test-suite or runtime success claim is needed for docs-only changes.
- [ ] Commit with `docs(architecture): consolidate system and UI reference`.

No new paid run, UI redesign, cloud setup, public gallery redeploy, repository
visibility change or claim of universal/minimal failure coverage is included.
