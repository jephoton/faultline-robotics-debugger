# Plan: a team-first case page and research-backed next steps (October 19, 2026)

**Status:** approved by the project owner on October 19, 2026.
- Report: "team-first plus one Nemotron box".
- Research: "make it feed next steps".

## Problem

Walking through Demo 1, the project owner found the case page bloated for a robotics
team.
- **Nemotron's reading** mostly restates **Hypothesis vs result**. Its one
  actionable part is its suggested next tests.
- **Research context** is a list of Tavily sources that nothing uses. Its
  Nemotron 3 Nano summary was even rejected as invalid for `FL-S-8E0D`.
- **A bug:** the explanation packet for `FL-S-8E0D` says milk and orange juice
  were "kept at full difference, untested". The case shrank milk to 87.5% in
  the continuation Job, so the shrink notes reflect only the first reduction
  Job. Nemotron repeated the wrong fact.

A team needs three things:
1. what fails: the result bullets and the videos;
2. why to trust it: the gate, each shift alone passing, and removing any one
   passing (or, for a stress test, the control and the levels around the
   threshold);
3. how to keep it: the regression test.

## Decisions

1. **Case page order** for scenario and audit cases:
   1. the header, the result bullets and the stop notice;
   2. videos;
   3. **Summary**, the report's own Summary section;
   4. **Why it's trustworthy**, built from structured data:
      - *Scenario:* the failing start fails f of n; the reference passes
        n of n; each kept shift alone passes (the probe rows, by number);
        removing any one passes (the minimality rows, by number).
      - *Audit:* the untouched control's failures; for each failing family,
        the counts at the threshold and at the last level that did not
        reproduce. Flag a family that met the gate only narrowly, for example
        a later replay with fewer failures, as **borderline** when the data
        shows it.
   5. **Nemotron**, one compact box:
      - *Scenario only:* "Its guess vs the reruns": the model's top-ranked
        entities, each with its measured label (needed / not needed /
        enough alone), in one short list.
      - *Every case with next steps:* "Suggested next steps": 2–4 items from
        Nemotron, each citing related work `[S#]` or evidence ids. Labelled
        "suggestions, not evidence", and naming the model.
   6. **Regression test**;
   7. **Full evidence**, collapsed: the rest of the report (screen,
      differences, hypothesis, candidates, effort, video table) and Nemotron's
      full reading;
   8. Run details and files.

   Wording, occlusion and older cases keep today's layout wherever the data
   is missing.
2. **Next steps, a new pipeline step after research.**
   - **Inputs:** one Token Factory call per case, with the verified case
     facts (the same facts the research uses, plus the minimal cause or
     thresholds) and the retrieved Tavily sources (title, URL, short
     snippet).
   - **Output:** schema-checked JSON of 2–4 next steps. Each must cite at
     least one source id from the list, or an evidence id from the case.
     Citations are validated against the list; the call fails closed (no next
     steps) on invalid output, like research today.
   - **Model:** Nemotron 3 Ultra. It produced valid structured explanations
     where Nano's research summary was rejected; one call costs about a cent.
     Record this as an ADR 0030 amendment.
   - **Storage:** next steps replace the Nano summary as the research record's
     `next_steps`. The standalone source list folds into the Nemotron box
     ("Sources" beneath the steps).
   - **The New diagnosis research option** keeps its name and needs a Tavily
     key and the Token Factory key; without them, no next steps are made.
3. **Fix the shrink notes** so the explanation packet reflects every reduction
   Job's shrink history (continuations included).

## Contract

The library detail of a case gains:
- `next_steps: { model, status, items: [{ text, cites: [string] }],
  sources: [{ id, title, url }] } | null`;
- `research` stays readable for older cases.

The web uses the existing fields for everything else:
- `scenario.reruns`, `scenario.hypothesis`, `audit.families`,
  `audit.nominal`, `replays`, `report_markdown`;
- the report's `## ` sections, split on the page.

## Work split (two Sonnet agents, worktrees, in parallel)

- **Backend agent.** Owns `src/robot_debug/**`, `scripts/**` and `tests/**`.
  - The next-steps step: prompt, validation and storage.
  - Wire it into `pipeline_research` and the pipeline's research step.
  - Expose `next_steps` in `library.py`.
  - Fix the shrink notes.
  - A local command to regenerate research next steps and explanations for an
    existing run without cloud Jobs: it reuses the cached Tavily results and
    makes Token Factory calls only.
  - Do not run it on real cases: the coordinator runs it.
- **Web agent.** Owns `web/**` and the rebuilt bundle.
  - The case page structure above, against the contract.
  - Use mock data for `next_steps`.
  - Make the Full evidence collapse work in the static gallery.
- **Coordinator:**
  - merges and runs both suites;
  - regenerates the three showcase cases (a few cents of Token Factory
    calls);
  - checks in the browser;
  - updates the Reference and runbook and the ADR 0030 amendment;
  - asks the project owner for the gallery redeploy.

**Autonomy:** green or amber inside these decisions. Stop and report if a
change would need a new simulator image, a paid Job, or a different model.

**Rules:**
- Conventional Commits, no AI attribution.
- No pushes or merges by agents.
- Never touch `artifacts/`.
- Use `PYTHONPATH=src python -m pytest -q -p no:cacheprovider`, never
  `uv run`.
- For web changes: `npm run typecheck`, `npm test -- --run` and
  `npm run build`, with LF line endings.
