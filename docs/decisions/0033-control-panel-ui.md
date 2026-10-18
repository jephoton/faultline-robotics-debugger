# ADR 0033: Faultline control panel UI

**Status:** Accepted by Jethro on October 17, 2026 (M7a step 4). Design:
`docs/superpowers/specs/2026-10-17-faultline-control-panel-design.md`.

## Context

The viewer is two disconnected pages (the September episode catalog with the
M4 case, and `/diagnoses`), shows no journey from import to replay, renders
Nemotron output as raw JSON, shows almost nothing for audits, and its home
page hangs on a large `artifacts/` folder. ADR 0027 asked for a product-grade
pass centred on import, diagnose, reduced case and replay, and a public
gallery for the Vercel deployment.

## Decision

- **One set of pages for both audiences:** the local tool and, as a static
  export, the public gallery.
- **The UI wraps the CLI:** a full control panel (guided "New diagnosis"
  form, dry run and confirm, live progress, Resume, a safe Stop, Replay,
  setup checks) running the same `faultline` commands as detached processes.
  Controls exist only on the local server (loopback only, per-session token,
  origin and host checks, one paid run at a time); the export has none.
- **Stack:** React + Vite (TypeScript), built into the Python package and
  committed so `pip install` needs no Node; CI checks the bundle is fresh.
- **Layout:** workspace with a persistent sidebar of runs and cases.
- **Old pages:** the M4 case joins the case list, the linked player moves to
  case pages, the episode catalog stays as a local-only "All evidence" page
  with its load fixed.
- **Safe Stop:** new `faultline stop`; the orchestrator cancels the current
  Job, waits for a terminal state, settles the ledger and leaves the run
  resumable.
- **Look:** alarm-first control-room style (greys; red only for a confirmed
  failure, amber for attention) with a scan-tool readout header and a
  display-only fault code (`FL-S-AFB5`) per case.

## Alternatives considered

- Audience: a local results browser only, or a judges' showcase only.
- Old page: keep it as a separate archive, or retire it.
- CLI relation: recorded story plus the next command; add live progress
  only; a spec builder only; run from spec files; compose and follow without
  launching.
- Stack: plain HTML and JavaScript modules (recommended at the time), or
  vendored Preact + htm. Jethro chose React + Vite.
- Layout: pages with top navigation, or a workspace behind a landing page.
- Look: a calm generic product UI (rejected as generic), then an incident
  docket, drafting sheet, seismic survey, teach pendant, bench instrument,
  scan tool and andon board; E (alarm-first HMI) and G (scan tool) were
  sketched as full pages and combined.

## Consequences

- A Node toolchain joins the repository for front-end work only; users and
  CI-free installs still need only Python.
- The local server can now start billable runs, so its safety checks are
  tested like the spend ledger.
- `faultline stop` is a new CLI command and an orchestrator state
  (`stopped_by_user`).
- Deploying the export (M7a step 5) and the final live UI run each need
  Jethro's go at the time.

## Implementation notes (October 17, 2026)

- Built in parallel by two agents against the plan's API contract
  (`docs/superpowers/plans/2026-10-17-control-panel-ui.md`), then integrated:
  `faultline ui` (the panel), `faultline stop` (safe stop), `faultline export`
  (static gallery). The September pages (`viewer/web/`) are retired; their
  data APIs remain. The M4 occlusion case is a library item (`FL-M-…`).
- The case list ("library") draws on three sources: registered diagnoses,
  finished runs that registered no case (for example a paraphrase run that
  found no failure; local only unless chosen with `export --case`), and the
  M4 case store.
- The evidence scan that took about two minutes is cached by modification
  time with one scan at a time (now about 1.4 s cold, 0.25 s warm).
- The bundle ships `THIRD-PARTY-LICENSES.txt` (React, React Router, marked,
  DOMPurify and the OFL fonts), generated at build time; see `NOTICE.md`.
- Integration fixes: the evidence field name (`video_url`), entity names in
  the hypothesis table, half-up rounding of minimal-cause sizes (3.65 cm reads
  3.7, as in the report), the occlusion step wording, no refetch bursts when a
  tab is hidden and shown, an export-guard false positive on a LaTeX paper
  title, and Start never offered again after a start that may have launched a
  run. The audit report's hard-coded scope line is fixed and the three stored
  audit reports were regenerated locally.
- An independent review of the control surface found no way for another
  origin to start, stop or replay a run (token, exact Origin and Host,
  loopback only, no CORS). Its findings (a slow start that could launch two
  runs, read endpoints without the Host check, a stop of a still-queued Job
  charged at worst case, `--no-llm` lost on resume, relative paths, and
  smaller items) are fixed in follow-up commits.

## Amendment (October 18, 2026): report-first case page

Jethro chose a report-first case page. A case with a saved report shows, in
order:
1. the header;
2. the linked videos;
3. the rendered report, which opens with a bullet Summary; long tables fold;
4. Nemotron's reading, collapsed;
5. Replay, with its purpose line;
6. collapsed run details;
7. the files.

The separate minimal-cause, reruns, hypothesis, ladder and wording sections
were removed from that layout (the report holds them, and the old reruns view
showed only the 8 reruns Nemotron cited, not all 26). Cases without a report
keep the structured view. Reports now open with a Summary, explain the
Candidates columns, and claim a size resolution only when shrinking finished.
Stored reports were regenerated locally; the committed demo report was
regenerated. See `docs/superpowers/plans/2026-10-18-report-first-case-page-and-traces.md`.
