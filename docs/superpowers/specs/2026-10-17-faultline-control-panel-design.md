# Faultline control panel: UI overhaul design

**Status:** Accepted by Jethro on October 17, 2026 (M7a step 4). Decision
record: ADR 0033. The implementation plan follows from this spec.

## Problem

The viewer grew milestone by milestone into two disconnected pages: the
September home page (an episode catalog, the M4 case panel and a linked
two-video comparison) and `/diagnoses` (a plain list of `faultline diagnose`
results with raw Nemotron JSON). Nothing shows the journey ADR 0027 asked
for (import, diagnose, reduced case, replay), audits show almost nothing, and
the home page's run list takes about two minutes to load on a full
`artifacts/` folder and re-requests on a timer, so it hangs.

## Decisions (Jethro, October 17)

| Question | Decision |
| --- | --- |
| Audience | Both: one set of pages is the local tool and, exported, the public gallery |
| Old home page | Fold into cases: the M4 case joins the case list, the linked player moves onto case pages, the episode catalog survives as a local-only "All evidence" page with its load fixed |
| Relation to the CLI | The UI is a wrapper around the CLI: a full control panel |
| Wrapper scope | Full: guided "New diagnosis" form, dry run, confirm, live progress, Resume, safe Stop, Replay, case pages, setup checks |
| Front-end stack | React + Vite (TypeScript) |
| Layout | Workspace: persistent sidebar of runs and cases, detail on the right |
| Stop | A safe Stop in this version |
| Look | Alarm-first control-room style (ISA-101 inspired) with a scan-tool fault code and readout header on each case |

## Architecture

### Parts

- **Front end (`web/`):** React 18 + Vite + TypeScript, a single-page app.
  Its production build is written into the Python package
  (`src/robot_debug/viewer/app/`) and committed, so `pip install` needs no
  Node. CI rebuilds it and fails if the committed bundle differs, then runs
  the front-end tests (Vitest + Testing Library). Node and package versions
  are pinned (`.nvmrc`, `package-lock.json`).
- **Control server (`robot_debug.viewer.server`, extended):** still Python
  standard library (`ThreadingHTTPServer`). It serves the bundle (with a
  fallback to `index.html` for app routes), the read APIs and the control
  APIs. New entry point `faultline ui`; `faultline-viewer` remains as an
  alias.
- **Static export (`faultline export`):** writes the bundle, JSON for the
  chosen cases and their videos into a folder, plus a `vercel.json` rewrite
  for app routes. With no server, the app shows cases only. Deploying it is
  M7a step 5 and needs Jethro's go.

### Read APIs

| Endpoint | Returns |
| --- | --- |
| `GET /api/session` | `mode` (`local`), whether controls are enabled, the per-session control token, version |
| `GET /api/cases` | Every case: registered diagnoses plus the converted M4 case, with fault code, kind, verdict, suite, task |
| `GET /api/cases/{id}` | The case, its diagnosis entry, explanation, `report.md` text, the run's step timeline and ledger summary when the run folder exists, and replay results |
| `GET /api/runs/active` | Runs whose process is alive (started from the UI or a terminal) |
| `GET /api/runs/{run}/progress` | Steps, current Job state, spend (spent, reserved, cap), elapsed against the hour limit, last log lines |
| `GET /api/evidence` | The old episode catalog, cached by folder modification time; never two scans at once |
| `GET /api/environment` | Nebius CLI signed in, image reference set, Hugging Face secret name set, Token Factory key present (presence only, never the value) |
| `GET /media/...` | Videos under the artifact root, as now |

The static export writes the same shapes to `data/session.json`
(`mode: static`, no controls), `data/cases.json` and `data/cases/{id}.json`.
The app reads `/api/session` and falls back to `data/session.json`.

### Control APIs

All are `POST`, enabled only in local mode, and mirror a CLI command:

| Endpoint | CLI equivalent |
| --- | --- |
| `/api/specs/validate` (YAML text) | Loading the spec through `spec.py`; returns its errors |
| `/api/specs/dry-run` (YAML text) | `diagnose --dry-run`: planned Jobs, deadlines, worst-case cost, cap, and a hash of the plan |
| `/api/runs` (YAML text, plan hash, optional import file) | `diagnose`; refused unless the plan hash matches a fresh dry run of the same spec |
| `/api/runs/{run}/resume` | `diagnose --resume` |
| `/api/runs/{run}/stop` | New `faultline stop RUN_DIR` (below) |
| `/api/cases/{id}/replay` (replay spec, expect, plan hash) | `replay --spec ... --expect ...`, with its own dry run and confirm |

The UI writes each spec (and an uploaded import file, size-limited as in
`scenario_import.py`) into an ignored folder, `artifacts/specs-ui/`, and runs
the CLI on that path, so every UI run can be reproduced from a terminal.
Runs start as detached processes (a new process group on Windows, a new
session on POSIX) that log to a file, so they survive closing the tab or
restarting the server. The CLI records its process id and run folder in a
lock file, which is how the server finds active runs, including ones started
from a terminal.

### Safe Stop

`faultline stop RUN_DIR` (and the UI button) writes a stop request into the
run folder. The orchestrator checks for it while it waits; on a request it
cancels the current Nebius Job through the backend, waits until the provider
reports a terminal state, settles that attempt in the ledger at measured
cost (or keeps it `unconfirmed` for `--resume` to settle, as after a sign-in
expiry), records the step as `stopped_by_user` and exits. The run stays
resumable. The cancel command and its terminal states are verified against
the Nebius CLI before implementation.

### Safety boundaries

- The server listens on `127.0.0.1` only and refuses to enable controls on
  any other address.
- Every control request must carry the session token (a random value issued
  to the page at load, sent in a header), and the server checks that `Origin`
  and `Host` are its own loopback address, so another website or a
  DNS-rebinding page cannot start, stop or replay a run.
- One paid run (or replay) at a time; the active run is the single owner of
  Nebius resources. The spec's spend cap and the ledger's worst-case
  reservations are unchanged.
- Secrets never reach the browser: the environment check reports presence
  only, and error messages are the CLI's sanitised ones.

## Pages and flow

**Sidebar (always visible):** "New diagnosis"; **Running** (each active run
with its step and spend, amber when it needs attention); **Cases** grouped as
scenario reductions, stress tests (audits), language (paraphrases) and earlier
(the M4 case), each with its fault code; at the bottom **Setup**, **Run your
own** and **All evidence** (local only).

1. **New diagnosis**, three steps.
   1. *What to diagnose:* "Find why a start fails" (scenario from a benchmark
      start, a range to search, or an uploaded start file), "Stress-test a
      passing start" (audit, image and scene families), "Test rewordings"
      (paraphrase).
   2. *Settings:* suite, task (with its instruction text), start, range or
      file, families, spend cap, hour limit, Nemotron on or off. Errors appear
      inline from `spec.py`. An "Edit YAML" panel shows the generated spec and
      accepts edits (any spec key, so the form need not cover every option).
   3. *Review:* the dry-run table and the sign-in status, then "Start
      diagnosis".
2. **Run page (live):** step timeline (screen, reference, hypothesis,
   reduce, continue, check, explain, case), the current Job state (waiting
   for a GPU with its resubmission count, running, downloading), a spend bar
   (spent, reserved, cap) and elapsed time against the limit, Stop and
   Resume. Problems are plain language with the action ("Your Nebius sign-in
   expired. Sign in, then Resume."). When the run finishes the page becomes
   the case page.
3. **Case page:** a readout header (fault code, verdict, kind, suite and
   task) and a one-sentence result, then evidence by kind:
   - scenario: the minimal-cause table and three linked videos (original,
     minimal, reference) with play-all and speed;
   - audit: a severity ladder per family (failures out of attempts at each
     level, the threshold or "none up to s = 1"), with videos when recorded;
   - paraphrase: the control wording and each paraphrase with its outcome
     and meaning check, and the minimal word change when one was found;
   - the M4 case: its occlusion episodes in the same linked player.

   Then **How it was made** (steps, Jobs, time, cost), **Nemotron's reading**
   rendered as text with its evidence references and labelled "review
   required", with its guess beside the measured verdict, the **Replay**
   panel (last verdict; Replay goes through dry run and confirm), and the
   report and files.
4. **Setup:** the environment checklist with how to fix each failing item.
5. **Run your own:** the quickstart as a page.
6. **All evidence:** the episode catalog (local only).

**Static (gallery) mode** hides New diagnosis, Running, Setup, All evidence
and every action, and shows a short intro panel; case pages are identical.

## Look: alarm-first with fault codes

- **Colour rule (ISA-101 inspired):** surfaces, text and controls are
  neutral greys. Colour marks only abnormal states: red for a confirmed,
  reproducing failure (and Stop), amber for "needs attention" (waiting for a
  GPU, stopped, sign-in expired, nominal controls failed, stopped at budget).
  Normal states, including passing and a replay that comes back fixed, stay
  neutral with an icon and a word. Status is never conveyed by colour alone.
- **Readout header:** each case and run opens with a dark panel in a
  monospace face, phosphor-green text, carrying the fault code, verdict and
  kind; this is the one decorative use of colour.
- **Fault code:** display only, derived from the case so it is stable in the
  export: `FL-` + kind letter (`S` scenario, `A` audit, `L` language, `M` the
  M4 case) + `-` + the first four hex digits of the case id in capitals (for
  example `FL-S-AFB5`), lengthened to six digits if two cases collide. It
  never replaces the case id, which stays visible.
- **Type:** Barlow and Barlow Condensed (headings, labels), DM Mono (ids,
  commands, readouts); self-hosted in the bundle (SIL OFL, listed in
  `NOTICE.md`), so the UI makes no third-party requests.
- **Themes:** light (control-room grey) and dark, following the system
  setting with a toggle.
- **Vocabulary:** the real terms (start, reference, gate, reduction, replay)
  everywhere; the scan-tool motif is limited to the code and the readout.
- **Accessibility:** WCAG 2.2 AA contrast in both themes, full keyboard use,
  visible focus, reduced-motion respected, live regions for run progress.

## Errors and empty states

- Each stop reason (`budget_exhausted`, `nominal_controls_failed`,
  `no_reference`, `import_invalid`, `import_mismatch`, `no_faithful_failure`,
  `original_mismatch`, `stopped_by_user`, and the rest) maps to a plain
  sentence and, where useful, an action.
- Sign-in expiry, GPU capacity exhaustion and validation errors say what to
  do next. Raw exception text never reaches the page; the run log is linked.
- Missing videos, explanations or replays show a short empty state.

## Testing

- Python unit tests: token, origin and host checks; refusal on non-loopback
  addresses; the one-run lock; validate and dry-run through a fake backend;
  plan-hash mismatch refusal; progress parsing; stop request handling in the
  orchestrator; the M4 adapter; evidence caching; export output.
- Vitest: the form steps and inline errors, the run page states, each case
  kind, static-mode hiding.
- Browser checks in the preview pane at each stage (light, dark, phone width).
- One real run started from the UI as the final check, with Jethro's go and
  cap at the time (expected: a paraphrase run, about US$0.35).

## Also fixed

- The audit report's scope line is hard-coded to "LIBERO-Object task 0 with
  seed 7" (`scripts/report_m6_experiment.py`); it must state the run's
  suite, task and start.

## Out of scope

Hosted runs on Jethro's account (rejected in ADR 0027), sign-in or user
accounts, more than one concurrent paid run, a form field for every spec key
(the YAML panel covers the rest), and deploying the export (step 5).

## Build order

1. Scaffold `web/`, the committed bundle and the CI freshness check.
2. Read APIs and case pages, matching today's content.
3. M4 case adapter and the All evidence fix.
4. Control APIs and safety checks; `faultline stop` and the orchestrator's
   stop handling.
5. New diagnosis form.
6. Live run page.
7. Replay.
8. Setup and Run your own.
9. Static export.
10. Remove the old pages; update README, quickstart, runbook and ADR.
