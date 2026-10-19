# Faultline control panel UI: implementation plan

Design: `docs/superpowers/specs/2026-10-17-faultline-control-panel-design.md`
(ADR 0033). Approved by the project owner on October 17, 2026, with an instruction to
carry on autonomously until the overhaul is finished.

**Gates that still need the project owner:** the one real (billable) run started from
the UI, and any publishing (Vercel, public image). Everything else here is
green or amber and proceeds without asking.

## Agents, ownership and concurrency

| Owner | Branch / worktree | Owns | Does not touch |
| --- | --- | --- | --- |
| **BE** (Sonnet, Python) | `ui-backend` | `src/robot_debug/viewer/*.py` (new modules allowed), `src/robot_debug/orchestrator.py` (stop only), `src/robot_debug/backends/*.py` (`wait` stop hook only), `src/robot_debug/cli.py`, `scripts/report_m6_experiment.py`, `tests/test_ui_*.py`, `tests/test_orchestrator*.py` additions | `web/`, `src/robot_debug/viewer/app/`, `src/robot_debug/viewer/web/`, docs |
| **FE** (Sonnet, TypeScript) | `ui-frontend` | `web/**`, `src/robot_debug/viewer/app/**` (build output), `.github/workflows/test.yml` (new front-end job only), `.gitattributes` additions for the bundle | Python files, docs |
| **Coordinator** (Opus) | `main` | Integration and merges, the old `viewer/web/` removal, packaging data, docs (README, quickstart, runbook, STATE, ADR notes), browser verification, the live-run gate | — |

BE and FE run in parallel against the API contract below; the FE agent
develops against a mock server built from the contract (fixtures under
`web/src/mocks/`). The coordinator merges BE first, then FE, then wires and
verifies. Agents commit on their branch (Conventional Commits, atomic, no AI
co-author trailers, no "Generated with" lines) and never push or merge.

Never put real Nebius ids (`e00…`, `aijob-…`, `project-…`), local user paths
or secrets in fixtures, tests or committed files: the repository is public.
Use obviously fake values.

## API contract (version 1)

JSON over the existing server. All read endpoints work in local mode; the
static export writes the same shapes to files. Every response carries
`Cache-Control: no-store` and `X-Content-Type-Options: nosniff` as now.

### Session

`GET /api/session` (static: `data/session.json`)

```json
{"api_version": 1, "mode": "local", "controls": true, "token": "<random>", "version": "<package version>"}
```

Static: `{"api_version": 1, "mode": "static", "controls": false, "token": null, "version": "..."}`.
`controls` is false when the server is bound to a non-loopback address.

### Library (the sidebar)

`GET /api/library` (static: `data/library.json`) returns `{"items": [LibraryItem], "warnings": [string]}`.

```ts
type Kind = "scenario" | "audit" | "paraphrase" | "occlusion";
type Verdict = "reproduces" | "no_failure" | "stopped" | "failed" | "incomplete";
interface LibraryItem {
  id: string;            // "d-<case_id>" registered diagnosis, "r-<run folder>" finished run with no case, "m-<case_id>" the M4 case
  fault_code: string;    // "FL-S-AFB5"; letter S/A/L/M by kind; hex from case_id (or sha256 of the run folder name); 6 hex digits if 4 collide
  kind: Kind;
  name: string;          // spec name or case label
  verdict: Verdict;
  verdict_text: string;  // one plain sentence
  attention: boolean;    // amber: stopped, controls failed, budget stop, sign-in, capacity
  suite: string | null; task_id: number | null; instruction: string | null;
  created: string | null;  // ISO 8601 UTC from the run-folder stamp
  case_id: string | null; run: string | null;  // run folder name, local mode only (null in static)
}
```

Sources: registered diagnoses (`case_register.list_diagnoses`); run folders
under the runs root that finished (`steps.json` run status `completed` or
`stopped`), are not `replay` mode and have no registered case (for example a
paraphrase run that found no failure); the M4 case store (`case_store`).
Verdicts: a scenario case that is entity-minimal or reduced → `reproduces`;
an audit with any family threshold → `reproduces`, else `no_failure`; stop
reason `no_reproducible_failure` → `no_failure`; `nominal_controls_failed`,
`budget_exhausted` (without a verified selection), capacity, sign-in →
`stopped` with `attention: true`; an orchestrator failure → `failed`.

### Case detail

`GET /api/library/{id}` (static: `data/library/{id}.json`) returns `LibraryItem` plus:

```ts
interface Detail extends LibraryItem {
  sentence: string | null;                 // the one-sentence result
  stop_reason: string | null; stop_text: string | null;   // plain-language mapping (see below)
  checkpoint: {id: string, revision: string, pinned: boolean} | null;
  videos: {role: string, label: string, url: string | null, outcome: string | null}[];
  scenario?: {
    failing_start: number | null;
    imported: {file_sha256: string, state_sha256: string} | null;
    reference_start: number | null;
    entity_minimal: boolean | null; reduced: boolean | null;
    minimal_cause: {entity: string, part: "position" | "rotation" | "joints", fraction: number, magnitude: string}[];
      // magnitude e.g. "2.9 cm", "6 joints, up to 2.6°" from case.differences scaled by fraction
    differences_count: number;
    hypothesis: {ranked: string[], measured_verdict: string | null, verdict_text: string | null,
                 entities: {entity: string, label: string, necessary: boolean | null, sufficient: boolean | null}[]} | null;
    reruns: {index: number, phase: string, role: string, selection: Record<string, Record<string, number>> | null,
             outcomes: string[], decision: string}[];
  };
  audit?: {
    start_index: number | null;
    nominal: {failures: number, attempts: number} | null;
    families: {family: string, label: string, threshold_severity: number | null, stop_reason: string,
               levels: {severity: number, failures: number, attempts: number}[]}[];
  };
  paraphrase?: {
    original: string | null;
    control: string[];                      // outcomes of the unmodified wording
    paraphrases: {text: string, outcomes: string[], failures: number, meaning: string | null}[];
    minimal_edit: {text: string, edits: string[]} | null;
  };
  occlusion?: {
    perturbation: Record<string, unknown>;
    lineage: {rectangle: {x: number, y: number, width: number, height: number}, edge: string, delta: number}[];
    episodes: {episode_id: string, stage: string, role: string, outcome: string, url: string | null}[];
  };
  explanation: {
    status: string; model: string | null; disclaimer: string | null;
    hypotheses: {text: string, evidence_ids: string[]}[];
    observations: {text: string, evidence_ids: string[]}[];
    limitations: string[];
  } | null;
  research: {related: string | null, sources: {title: string, url: string}[]} | null;   // M4 only
  history: {
    steps: {key: string, label: string, status: string, state: string | null, partial: boolean, cost_usd: number | null}[];
    jobs: number; spent_usd: number | null; cap_usd: number | null; hourly_usd: number | null;
    elapsed_seconds: number | null; max_hours: number | null;
  } | null;
  replays: {run: string | null, verdict: string, verdict_text: string, created: string | null, cost_usd: number | null}[];
  report_markdown: string | null;
  files: {name: string, url: string}[];
  replayable: boolean;                       // scenario case with replay inputs
}
```

Public projection rules (local and static alike): never include Job ids,
project, subnet, registry or bucket names, access keys, absolute paths, or
`backend-state.json` content; `public_value` from `viewer/server.py` is the
model. Replays are runs in `replay` mode whose `replay-result.json` names the
case id.

Stop-reason text (BE keeps the table in one module; FE shows `stop_text`):
`budget_exhausted` "Stopped at the candidate budget; this is the smallest
cause found so far.", `nominal_controls_failed` "The unperturbed policy did
not pass reliably, so no disturbance can be judged.",
`no_reproducible_failure` "No failure repeated 4 of 5 times.", `no_reference`
"No nearby benchmark start passed reliably.", `import_invalid` "The imported
start file was not valid.", `import_mismatch` "The imported start did not
match the task's scene.", `no_faithful_failure` "The imported start did not
fail reliably.", `original_mismatch` "The original wording did not match the
task.", `capacity_unavailable` "No GPU became available after six
submissions.", `spend_cap` "The next Job could exceed the spend cap.",
`max_hours` "The hour limit was reached.", `stopped_by_user` "Stopped from
the control panel or `faultline stop`.", `backend_error` "The cloud call
failed; resume to re-attach.", `auth_expired` "Your Nebius sign-in expired.
Sign in, then resume."; anything else: "Stopped: <reason>."

### Runs

`GET /api/runs/active` → `{"runs": [RunSummary]}`; `GET /api/runs/{run}/progress` → `Progress`.

```ts
interface RunSummary { run: string; name: string; mode: string; status: "running" | "stopping";
  step: string | null; spent_usd: number | null; cap_usd: number | null; attention: boolean; }
interface Progress extends RunSummary {
  status: "running" | "stopping" | "completed" | "stopped" | "failed" | "interrupted";
  stop_reason: string | null; stop_text: string | null;
  steps: {key: string, label: string, status: string, state: string | null, attempts: number, capacity_waits: number}[];
  job: {name: string, phase: "submitting" | "waiting_for_gpu" | "running" | "downloading" | "settled" | null} | null;
  spent_usd: number; reserved_usd: number; cap_usd: number; elapsed_seconds: number; max_hours: number;
  log_tail: string[];          // last 40 lines of the run log, redacted with backends.redact
  library_id: string | null;   // once the case is registered
  resumable: boolean; stoppable: boolean;
}
```

A run is active when its `process.json` (written by the CLI, below) names a
live process. Progress is read from `steps.json`, `ledger.json` and the run
log; it never calls the cloud.

### Environment

`GET /api/environment` →

```json
{"checks": [{"key": "nebius_cli", "ok": true, "detail": "signed in"},
            {"key": "token_factory_key", "ok": false, "detail": "NEBIUS_API_KEY not found in .env", "fix": "..."}]}
```

Checks: `nebius` CLI on PATH (or WSL), `nebius iam whoami` succeeds (cached
60 s, run with a 20 s timeout), Docker present (for image builds only),
`.env` holds `NEBIUS_API_KEY` (presence only), a local spec template exists
with `backend.image` and `hf_token_secret` filled (reports names, never ids).

### Controls (POST, local mode only)

Every POST needs header `X-Faultline-Token: <session token>`, an `Origin`
equal to `http://127.0.0.1:<port>` or `http://localhost:<port>` (absent
Origin is refused), and a `Host` of the same; otherwise 403. JSON bodies up
to 2 MB; errors are `{"error": "<plain sentence>", "errors": [{"path": "...", "message": "..."}]}`.

| Endpoint | Body | Response |
| --- | --- | --- |
| `/api/specs/template` (GET, no token) | `?mode=scenario-start|scenario-screen|scenario-import|audit|paraphrase|replay` | `{"yaml": "..."}`, from `configs/specs/*.yaml` with the local template's backend block when one exists |
| `/api/specs/validate` | `{"yaml": "..."}` | `{"ok": bool, "errors": [...], "summary": {...}}` |
| `/api/specs/dry-run` | `{"yaml": "...", "import_file": {"name": "...", "content": "<json text>"}?}` | `{"plan_hash": "...", "jobs": [{"name","deadline_seconds","worst_case_usd"}], "worst_case_total_usd", "cap_usd", "max_hours", "lines": [...]}` |
| `/api/runs` | `{"yaml", "plan_hash", "import_file"?, "no_llm"?}` | `202 {"run": "<folder>", "library_id": null}` or 409 when a run is active, 412 when the plan hash does not match a fresh dry run |
| `/api/runs/{run}/stop` | `{}` | `202 {"status": "stopping"}` |
| `/api/runs/{run}/resume` | `{}` | `202 {"run": ...}` (409 when active) |
| `/api/library/{id}/replay` | `{"yaml", "plan_hash", "expect"?}` | `202 {"run": ...}` |

The server writes each submitted spec (and import file) to
`artifacts/specs-ui/<UTC stamp>-<name>/` and launches
`python -m robot_debug.cli diagnose <spec> --env-file .env --runs-root <runs> --run-dir-file <launch file>`
(or `replay`, `--resume`) detached, with output to `<launch dir>/run.log`
(then also linked from the run folder). One active run at a time.

## Backend tasks (agent BE)

Use test-driven development; keep each commit green
(`PYTHONPATH=src python -B -m unittest discover -s tests`).

1. **fix(report): state the audited suite, task and start.** Replace the
   hard-coded scope line in `scripts/report_m6_experiment.py` with the run's
   suite, task, start and seed; test with a Spatial and a Goal summary.
2. **feat(cli): record the running process and its run folder.** At the
   start of `diagnose` and `replay`, write `process.json`
   (`{"pid", "started_at", "command": "diagnose"|"replay"}`) into the run
   folder and delete it on exit (finally); add hidden
   `--run-dir-file PATH` which receives the run folder path as soon as it
   exists. Tests with a fake orchestrator.
3. **feat(cli): stop a run safely.** `faultline stop RUN_DIR` writes
   `stop-request.json`. `Backend.wait` gains an optional
   `should_stop: Callable[[], bool]`; Nebius and local backends check it
   each poll, send the cancel once (as the watchdog does), keep polling to a
   terminal state within the cancel grace and return a result with reason
   `stopped_by_user`. The orchestrator passes `should_stop`, checks it
   before each submit and during capacity pauses, and on a stop settles the
   attempt at measured time (worst case only when no time is known), marks
   it `cancelled` and raises `StopRun("stopped_by_user")`. `--resume`
   deletes `stop-request.json` and continues on a fresh attempt name. Tests:
   stop while waiting, while paused, before submit; resume afterwards; ledger
   arithmetic.
4. **feat(ui): process and run discovery.** New `viewer/processes.py`:
   liveness of a pid on Windows (`OpenProcess` + `GetExitCodeProcess` via
   `ctypes`) and POSIX (`os.kill(pid, 0)`), guarded by `started_at` against
   reuse; active-run listing; progress parsing (`Progress` above) from
   `steps.json`, `ledger.json` and the log, with `phase` derived from the
   last attempt's state; capacity waits counted. Tests with synthetic
   folders.
5. **feat(ui): the library read model.** New `viewer/library.py`:
   `LibraryItem` and `Detail` from the three sources; fault codes;
   minimal-cause magnitudes (`position_cm × fraction` to one decimal; robot
   joints as "N joints, up to X°"; rotation in degrees); audit levels from
   the run's M6 summary when the run folder exists (else families only);
   paraphrase rows from `paraphrases.json` and the language summary;
   explanation flattening; replays; history; stop-reason texts; public
   projection. Tests with fixtures copied in shape (fake ids) from the
   current case files of each kind.
6. **feat(ui): the M4 case and the evidence catalog.** The occlusion case in
   the library (episodes with media URLs, lineage, research). Cache
   `ArtifactCatalog.snapshot()` keyed on the newest modification time under
   the artifact root, one scan at a time (a lock; concurrent callers wait for
   the same result); `GET /api/evidence` serves it. Test that two concurrent
   requests scan once.
7. **feat(ui): session and control security.** Session token
   (`secrets.token_urlsafe(32)`) per server start; POST guard (token,
   Origin, Host); controls disabled on non-loopback binds; body size limit.
   Tests for each refusal.
8. **feat(ui): spec validation, templates and dry run.** Validate with
   `spec.load`/`Spec` from text (temp file under the specs-ui folder);
   templates from `configs/specs/`; dry run through
   `orchestrator.dry_run_lines` with a fake-free path that never touches
   the cloud; `plan_hash` = sha256 of the canonical YAML, import-file hash
   and the dry-run lines. Tests: errors are paths and messages; hash
   changes when the spec changes.
9. **feat(ui): launch, stop, resume and replay.** `viewer/launcher.py`:
   detached start (`subprocess.Popen` with `CREATE_NEW_PROCESS_GROUP |
   DETACHED_PROCESS` on Windows, `start_new_session=True` on POSIX, stdin
   closed, stdout and stderr to `run.log`), the one-run lock, plan-hash
   check, run-folder discovery through `--run-dir-file`; stop writes the
   request through the CLI function; resume and replay launch the
   corresponding commands. Tests with a fake `Popen`.
10. **feat(ui): environment checks** as specified, with injectable command
    runners. Tests for each check, including that the key's value is never
    returned.
11. **feat(ui): serve the app.** Static files from `viewer/app/` with an
    `index.html` fallback for non-API, non-media paths; `/assets/*` cached
    immutably; new routes wired into the handler; `faultline ui` subcommand
    (`--artifacts`, `--runs-root`, `--port`, `--host`, `--open`) and
    `faultline-viewer` pointing at it. Keep the existing `/api/runs`,
    `/api/cases*`, `/api/diagnoses*` endpoints working until the coordinator
    removes the old pages.
12. **feat(cli): export a static gallery.** `faultline export --out DIR
    [--case ID ...] [--artifacts ...]` copies `viewer/app/`, writes
    `data/session.json`, `data/library.json`, `data/library/<id>.json` with
    `run: null` and no local-only fields, copies each case's videos to
    `media/` and rewrites URLs, and writes `vercel.json`
    (`{"rewrites": [{"source": "/((?!assets/|data/|media/).*)", "destination": "/index.html"}]}`).
    Refuses an output folder inside `src/` or one that is not empty without
    `--force`. Tests on a fixture library.

## Front-end tasks (agent FE)

Stack: Vite 5, React 18, TypeScript (strict), React Router 6 (browser
routes), Vitest + Testing Library + jsdom. No UI framework or CSS framework:
plain CSS with custom properties (tokens) in `web/src/styles/`. Fonts:
Barlow, Barlow Condensed, DM Mono as WOFF2 under `web/public/fonts/` from
their official OFL releases (`@fontsource` packages are acceptable as the
source), with the licence text alongside. Pin exact versions; commit
`package-lock.json`; add `.nvmrc` (`24`).

1. **build(web): scaffold the app and the committed bundle.** `web/`
   project; `vite.config.ts` builds to `../src/robot_debug/viewer/app/`
   with `emptyOutDir`, hashed assets under `assets/`, and a dev proxy for
   `/api` and `/media` to `127.0.0.1:8765`; scripts `dev`, `build`,
   `test`, `typecheck`, `lint` (tsc only). CI job `web`: Node 24,
   `npm ci`, `npm run typecheck`, `npm test -- --run`, `npm run build`,
   then `git diff --exit-code -- src/robot_debug/viewer/app`. Mark the
   bundle `linguist-generated` in `.gitattributes`.
2. **feat(web): tokens, type and the shell.** Light (control-room grey) and
   dark themes from tokens; `prefers-color-scheme` plus a toggle stored in
   `localStorage` (wrapped in try/catch). Alarm-first colour rule: neutral
   everywhere, `--alarm` red only for `reproduces` and Stop, `--attention`
   amber for `attention`/stopped states; status always has an icon and a
   word. The workspace layout: sidebar (New diagnosis, Running, Cases grouped
   by kind with fault codes, Setup, Run your own, All evidence) and main
   area; collapses to a drawer under 760 px. A `ReadoutHeader` component
   (dark panel, DM Mono, phosphor green text, the only decorative colour).
3. **feat(web): API client and mock data.** `web/src/api/` with typed
   functions for every endpoint, session handling (fallback to
   `data/session.json`, static data paths), the token header on POSTs, and
   an error type carrying the server's sentence and field errors. Fixtures
   in `web/src/mocks/` for every kind and state (fake ids), served by a
   small Vite dev middleware when `VITE_MOCK=1`.
4. **feat(web): case pages.** Route `/case/:id`. Readout header (fault code,
   verdict, kind, suite and task, instruction), result sentence, then by
   kind: scenario (minimal-cause table, linked video trio with play all,
   pause, restart, speed and sync, hypothesis next to the measured verdict,
   collapsible reruns table), audit (severity ladder per family: a row per
   level with failures/attempts as segmented bars and the threshold marked),
   paraphrase (control wording and paraphrase table with outcomes and the
   meaning check, minimal edit), occlusion (the episode player and the
   rectangle lineage). Common: How it was made (step timeline with cost),
   Nemotron's reading (hypotheses, observations, limitations, evidence ids,
   "review required" label, model), research (M4), replays, the report
   (render Markdown safely with a small dependency such as `marked` +
   `DOMPurify`, or a minimal renderer for headings, lists, tables and code),
   files. Empty states for missing parts.
5. **feat(web): New diagnosis.** Route `/new`. Step 1: three choices (with
   the scenario sub-choice start / range / file). Step 2: form fields
   (suite, task with its instruction text from a static table of LIBERO task
   instructions kept in `web/src/data/tasks.ts`, start or range, file
   picker reading the JSON as text, families as checkboxes for audit, spend
   cap, hour limit, Nemotron toggle) generating YAML from the template;
   an "Edit YAML" panel (textarea) that becomes the source of truth once
   edited; inline errors from `/api/specs/validate` (debounced). Step 3:
   dry-run table, environment status, total worst case against the cap, and
   "Start diagnosis" (posts with the plan hash), then navigate to the run
   page. Disabled controls are avoided: buttons stay enabled and explain why
   they cannot proceed.
6. **feat(web): live run page.** Route `/run/:run`. Polls progress every
   5 s (never overlapping requests; pauses when the tab is hidden), step
   timeline, Job phase with capacity waits, spend bar (spent, reserved,
   cap), time against the limit, log tail, Stop (confirm dialog: "Stop this
   run? The current Job is cancelled and charged for the time it ran. You
   can resume later.") and Resume; plain-language problems from
   `stop_text`; when `library_id` appears, offer and then navigate to the
   case. Running items in the sidebar poll `/api/runs/active` every 10 s.
7. **feat(web): replay.** On replayable cases: a panel with the replay
   template (checkpoint override and expect fields), dry run, confirm, then
   the run page; replay history listed on the case.
8. **feat(web): setup, guide, evidence and home.** `/setup` (environment
   checks with fixes), `/guide` (the quickstart as a page, written in
   `web/src/content/guide.tsx` from `docs/setup/diagnose.md`), `/evidence`
   (the old episode catalog as a list with a video and outcome per episode,
   local only), `/` (local: the latest case and any active run; static: an
   intro panel explaining Faultline's loop and the cases). Static mode hides
   every control and local-only route.
9. **test(web): accessibility and states.** Keyboard order, focus
   management on route change, `aria-live` for progress, contrast checked
   for both themes (document the measured ratios in a test or comment),
   reduced motion.

## Integration (coordinator)

1. Merge `ui-backend`, run the Python suite; merge `ui-frontend`, run the
   web checks.
2. Package data: `"robot_debug.viewer" = ["app/**/*"]` (and fonts), remove
   `viewer/web/` and the old-page routes and their tests, keeping the data
   APIs the new app uses.
3. Browser verification in the preview pane against the real `artifacts/`
   and `demo/root`: every case kind, the M4 case, All evidence (load time),
   New diagnosis through dry run (no Job), Setup, light and dark, phone
   width, static export served locally.
4. Regenerate `demo/` so it opens in the new UI; update README, quickstart
   (`faultline ui`), runbook, STATE, ADR 0033 implementation notes,
   `NOTICE.md` (fonts and front-end dependencies).
5. Live gate: ask the project owner for go and a cap, then one paraphrase run started,
   watched, and finished from the UI; record cost in FEEDBACK if material.

## Review checkpoints

- After both branches: an independent review agent checks the control
  surface (token, origin, host, loopback, one-run lock, stop safety and
  ledger arithmetic, public projection in the export: no ids or paths) and
  the front end against the spec; the coordinator triages findings.
- Before the live gate: a summary for the project owner with screenshots.
