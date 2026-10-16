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
