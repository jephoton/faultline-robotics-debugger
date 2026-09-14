# Viewer Demo Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the local artifact viewer as a clear hackathon-demo MVP and verify it against the existing baseline and occlusion evidence.

**Architecture:** Keep the existing Python standard-library read-only server and vanilla HTML/CSS/JavaScript client. Derive all new presentation text from the existing `/api/runs` data in the browser; do not add or change an API contract.

**Tech Stack:** Python 3.8+, `http.server`, HTML5, CSS, vanilla JavaScript, Canvas 2D, `unittest`.

---

## Starting state and boundaries

Begin after these commits on `chore/baseline-setup`:

- `9f2bab9 feat(viewer): serve diagnostic evidence`
- `74364a8 feat(viewer): add forensic workbench shell`
- `1866508 feat(viewer): compare robot episodes`

Read the approved design at
`docs/superpowers/specs/2026-09-14-viewer-demo-clarity-design.md` and the full
viewer plan at
`docs/superpowers/plans/2026-09-13-artifact-observability-viewer.md`.

Work only on the viewer. Do not start or modify Nebius resources, edit generated
files below `artifacts/`, change artifact schemas, or push commits. Preserve
unrelated changes. Use Conventional Commits.

### Task 1: Add the guided comparison hierarchy

**Files:**
- Modify: `src/robot_debug/viewer/web/index.html`
- Modify: `src/robot_debug/viewer/web/app.js`
- Test: `tests/test_viewer_server.py`

- [ ] **Step 1: Strengthen the static contract test**

In `test_static_workbench_assets_expose_semantic_landmarks`, require stable IDs
for the guide, conclusion, channel roles, and linked state:

```python
for identifier in (
    'id="demo-guide"',
    'id="comparison-conclusion"',
    'id="primary-role"',
    'id="comparison-role"',
    'id="link-state"',
):
    self.assertIn(identifier, page)
```

- [ ] **Step 2: Run the focused test and confirm it fails**

```powershell
$workspacePython = 'C:\Users\Jethro\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest tests.test_viewer_server.ViewerServerTests.test_static_workbench_assets_expose_semantic_landmarks -v
```

Expected: failure because the new IDs are absent.

- [ ] **Step 3: Add semantic guide and status elements**

In `index.html`, place this directly before `#summary-strip`:

```html
<section id="demo-guide" aria-label="Demo workflow">
  <p class="eyebrow">QUICK START</p>
  <ol>
    <li><strong>01</strong> Select reference</li>
    <li><strong>02</strong> Compare perturbation</li>
    <li><strong>03</strong> Inspect result</li>
  </ol>
</section>
<section id="comparison-conclusion" aria-live="polite">Loading experiment evidence…</section>
```

Inside each `.video-channel`, add a role paragraph above its label:

```html
<p id="primary-role" class="channel-role">PRIMARY EVIDENCE</p>
```

and:

```html
<p id="comparison-role" class="channel-role">COMPARISON EVIDENCE</p>
```

Change transport button text to `Play both`, `Pause both`, and `Restart both`.
Add `<span id="link-state">LINKED</span>` beside the link checkbox.

- [ ] **Step 4: Derive honest presentation text in JavaScript**

Add these helpers to `app.js`:

```javascript
function outcomeLabel(episode) {
  return episode ? outcomeLabels[episode.outcome] : "NO EVIDENCE";
}

function perturbationArea(episode) {
  const fault = episode && episode.perturbation;
  return fault && fault.enabled ? Number(fault.width || 0) * Number(fault.height || 0) * 100 : null;
}

function renderComparisonStory(primary, comparison) {
  const primaryArea = perturbationArea(primary);
  const comparisonArea = perturbationArea(comparison);
  const perturbedArea = primaryArea == null ? comparisonArea : primaryArea;
  const suffix = perturbedArea == null ? "" : ` at ${perturbedArea.toFixed(2)}% image occlusion`;
  setText(byId("comparison-conclusion"), primary && comparison
    ? `${outcomeLabel(primary)} → ${outcomeLabel(comparison)}${suffix}`
    : primary ? "Add a second episode to enable comparison" : "No experiment evidence found");
  setText(byId("primary-role"), primary && !primary.perturbation.enabled
    ? "REFERENCE / NOMINAL" : "PRIMARY / INVESTIGATION");
  setText(byId("comparison-role"), comparison && comparison.perturbation.enabled
    ? "INVESTIGATION / PERTURBED" : "COMPARISON / REFERENCE");
  const displayedOutcome = comparison ? comparison.outcome : primary ? primary.outcome : "";
  byId("comparison-conclusion").dataset.outcome = displayedOutcome;
}
```

Call `renderComparisonStory(primary, episodeById(state.comparisonId))` from
`render()`. Update `#link-state` from the checkbox handler. Set the initial
connection text to the existing loading message, preserve the existing empty
catalog guidance, and add `data-outcome` to run buttons so CSS can supplement
labels with color. When the displayed episode has outcome
`infrastructure_error`, append `POLICY NOT EVALUATED` to the conclusion and
diagnostics text.

- [ ] **Step 5: Run focused and full checks**

```powershell
node --check src\robot_debug\viewer\web\app.js
$workspacePython = 'C:\Users\Jethro\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest discover -s tests -v
git diff --check
```

Expected: JavaScript syntax exits zero, all 27 or more tests pass, and the diff
check is clean.

- [ ] **Step 6: Commit the interaction copy**

```powershell
git add src/robot_debug/viewer/web/index.html src/robot_debug/viewer/web/app.js tests/test_viewer_server.py
git commit -m "feat(viewer): clarify comparison workflow"
```

### Task 2: Polish the MVP visual hierarchy

**Files:**
- Modify: `src/robot_debug/viewer/web/styles.css`

- [ ] **Step 1: Style the guide and conclusion using existing tokens**

Add styles for `#demo-guide`, its three-step list, `.channel-role`,
`#comparison-conclusion`, outcome badges, `#link-state`, loading/empty states,
and the selected run. Reuse the existing color variables. Add
`--infrastructure: #b99ae8` for infrastructure errors. Do not add gradients,
external fonts, animation, icon-only controls, or a component dependency.

Use data attributes for outcome colors:

```css
[data-outcome="success"] { --outcome: var(--success); }
[data-outcome="task_failure"] { --outcome: var(--failure); }
[data-outcome="episode_timeout"] { --outcome: var(--amber); }
[data-outcome="infrastructure_error"] { --outcome: var(--infrastructure); }
#run-list button[data-outcome] { border-left: 3px solid var(--outcome); }
#comparison-conclusion[data-outcome] { border-color: var(--outcome); }
```

Keep the primary video slightly larger at desktop widths. At 768 px, stack the
guide steps, rail, videos, and diagnostics in document order. Keep visible
focus rings and the reduced-motion query.

- [ ] **Step 2: Check the stylesheet and full test suite**

```powershell
$workspacePython = 'C:\Users\Jethro\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest discover -s tests -v
git diff --check
```

Expected: all tests pass and the diff check is clean.

- [ ] **Step 3: Commit the visual polish**

```powershell
git add src/robot_debug/viewer/web/styles.css
git commit -m "style(viewer): improve demo clarity"
```

### Task 3: Package and document local operation

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`

- [ ] **Step 1: Add the console script**

Add to `pyproject.toml`:

```toml
[project.scripts]
robot-debug-viewer = "robot_debug.viewer.server:main"
```

- [ ] **Step 2: Add the operator flow to README**

Document the exact PowerShell launch command, default
`http://127.0.0.1:8765` URL, cloud-artifact synchronization prerequisite,
nominal-primary and occlusion-comparison demo sequence, read-only behavior,
and separate infrastructure-error classification. Warn against binding
`--host 0.0.0.0` on an untrusted network.

- [ ] **Step 3: Run packaging and CLI checks**

```powershell
$workspacePython = 'C:\Users\Jethro\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest discover -s tests -v
& $workspacePython -m robot_debug.viewer.server --help
git diff --check
```

Expected: all tests pass; help lists `--artifacts`, `--host`, and `--port`;
the diff check is clean.

- [ ] **Step 4: Commit packaging and documentation**

```powershell
git add pyproject.toml README.md
git commit -m "docs(viewer): add local demo workflow"
```

### Task 4: Verify the real demo and record evidence

**Files:**
- Modify: `docs/superpowers/plans/2026-09-14-viewer-demo-clarity.md`
- Generate, do not commit: `artifacts/viewer-demo/`

- [ ] **Step 1: Launch the real artifact viewer**

```powershell
$workspacePython = 'C:\Users\Jethro\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -m robot_debug.viewer.server --artifacts artifacts --port 8765
```

Use only `http://127.0.0.1:8765`.

- [ ] **Step 2: Run desktop and narrow-width browser acceptance**

At 1440×900 and 768 px verify:

- baseline and valid occlusion videos load;
- baseline reports 137 steps and valid occlusion reports 129 steps;
- the occlusion is visible in the perturbed video;
- linked play, pause, seek, restart, and playback-rate controls work;
- conclusion and channel roles update when either selector changes;
- the infrastructure attempt says `INFRA ERROR`, zero steps, and that the
  policy was not evaluated;
- run switching creates no browser-console error;
- keyboard focus and focus rings remain usable;
- no browser request leaves `127.0.0.1`.

Capture one screenshot at
`artifacts/viewer-demo/demo-clarity.png`. Do not commit it.

- [ ] **Step 3: Record exact evidence**

Append an `Implementation evidence` section to this plan with the final test
count, browser name, widths checked, screenshot path, and any unmet acceptance
criterion. Do not mark a criterion complete unless it was observed.

- [ ] **Step 4: Commit implementation evidence**

```powershell
git add docs/superpowers/plans/2026-09-14-viewer-demo-clarity.md
git commit -m "docs(viewer): record demo acceptance"
```

## Completion condition

Stop after the acceptance-evidence commit. Report the commits, test count,
screenshot path, and any limitation. Do not push; Jethro reviews the local
commits first.
