# Fixed-Area Position-Grid Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and locally validate a bounded driver that searches eight new positions for the accepted 25%-area agent-view occlusion, confirms the first apparent failure, and checks it against fresh matched nominal controls.

**Architecture:** Preserve the completed severity-search driver and its evidence. Add explicit-position support to its YAML writer, then build a separate position-grid entry point that reuses the proven evaluator, evidence-classification, atomic-summary, and output-safety helpers. The existing viewer gains coordinate labels; cloud execution stays behind a separate user-approved spending gate.

**Tech Stack:** Python 3.8-compatible standard library, existing `vla-eval` CLI, GR00T N1.7, LIBERO/MuJoCo, YAML emitted as text, JSON/JSONL/SQLite/MP4 evidence, dependency-free HTML/CSS/JavaScript viewer, `unittest`, Nebius L40S only after approval.

---

## Accepted boundary

The governing design is
[`../specs/2026-09-15-position-grid-search-design.md`](../specs/2026-09-15-position-grid-search-design.md)
and [`../../decisions/0004-fixed-area-position-grid.md`](../../decisions/0004-fixed-area-position-grid.md).
Keep task 0, episode 0, both seeds at 7, square side 0.50,
opaque black appearance, agent view only, one sequential worker, five exact
replays, and the 4/5 reproducibility rule unchanged.

This plan does not add adaptive search, a heatmap, a new perturbation family,
another task, parallel workers, or failure reduction. It does not authorize
Nebius spending.

## Autonomy and execution boundary

| Work | Level | Rule |
| --- | --- | --- |
| Local driver/config implementation and tests | Green | Smaller implementation model proceeds and commits. |
| Exact preregistered order, sentinel, and conditional controls | Amber | Implement as specified; explain evidence at the checkpoint. |
| Viewer coordinate labels | Green | Keep to existing MVP workbench; no heatmap. |
| Cloud preflight and run | Red | Stop until Jethro approves a fresh cap after live-rate verification. |
| Any model/task/failure-rule/perturbation change | Red | Return to Jethro before dependent work. |

The automatic implementation handoff uses `gpt-5.6-terra` at medium reasoning
when available. The stronger-model coordinator owns integration, final review,
the learning checkpoint, Git history, and any later Nebius lifecycle.

## Dependency and concurrency map

```text
Task 1: explicit-position YAML support
    -> Task 2: position-grid driver
        -> Task 4: integrated local verification and docs

Task 3: viewer coordinate labels --------------------^

Task 5: independent evidence/spec review -> learning checkpoint
    -> RED GATE: live price + new cap
        -> Task 6: one-owner cloud execution and interpretation
```

| Owner | Files | Expected output |
| --- | --- | --- |
| Smaller-model driver builder | `scripts/run_failure_search.py`, `scripts/run_position_grid_search.py`, `tests/test_position_grid_search.py`, relevant `tests/test_session.py` cases | Tested local grid driver with legacy severity behavior preserved. |
| Smaller-model viewer builder, parallel after Task 1 | `src/robot_debug/viewer/web/app.js`, `tests/test_viewer_server.py`, `tests/test_viewer_catalog.py` | Coordinates distinguish equal-area runs without changing the viewer schema. |
| Integration owner | Plans, experiment record, main-plan status, commits, cloud lifecycle | Conflict resolution, full verification, evidence synthesis. |
| Read-only reviewer | Diff, tests, frozen design, later raw artifacts | Spec-compliance report; no overlapping edits. |

Only the integration owner may merge, change the experiment contract, start or
stop Nebius compute, alter a security rule, copy cloud artifacts, or publish.

### Task 1: Add explicit position to the proven config writer

**Files:**
- Modify: `scripts/run_failure_search.py`
- Modify: `tests/test_session.py`

- [x] **Step 1: Write failing compatibility and coordinate tests**

Extend the direct `_write_config` coverage with one explicit placement and one
invalid partial placement. Also require the safe-directory helper to support a
new logical session name without changing its legacy default:

```python
def test_config_writer_accepts_explicit_position_without_changing_size(self):
    path = self.root / "grid.yaml"
    run_failure_search._write_config(
        config_path=path,
        output_dir=self.root / "out",
        project_root=self.project,
        stage_name="grid-x000-y050",
        episode_indices=(0,),
        side=0.50,
        x=0.00,
        y=0.50,
    )
    text = path.read_text(encoding="utf-8")
    self.assertIn("x: 0.000000", text)
    self.assertIn("y: 0.500000", text)
    self.assertIn("width: 0.500000", text)
    self.assertIn("height: 0.500000", text)

def test_config_writer_rejects_partial_or_out_of_bounds_position(self):
    common = dict(
        config_path=self.root / "bad.yaml",
        output_dir=self.root / "out",
        project_root=self.project,
        stage_name="bad",
        episode_indices=(0,),
        side=0.50,
    )
    with self.assertRaisesRegex(ValueError, "x and y"):
        run_failure_search._write_config(**common, x=0.00, y=None)
    with self.assertRaisesRegex(ValueError, "image bounds"):
        run_failure_search._write_config(**common, x=0.51, y=0.00)
    with self.assertRaisesRegex(ValueError, "finite number"):
        run_failure_search._write_config(**common, x=True, y=0.00)

def test_prepare_session_directory_accepts_distinct_safe_name(self):
    session = run_failure_search._prepare_session_directory(
        self.results, session_directory_name="position-grid-search"
    )
    self.assertEqual(session, (self.results / "position-grid-search").resolve())
    with self.assertRaisesRegex(ValueError, "single directory name"):
        run_failure_search._prepare_session_directory(
            self.results, session_directory_name="../escape"
        )
```

- [x] **Step 2: Run the focused tests and confirm the new calls fail**

```powershell
$workspacePython = 'python'
$env:PYTHONPATH=(Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest tests.test_session -v
```

Expected: the new tests fail because `_write_config` has no `x` or `y`
parameters; existing tests remain passing.

- [x] **Step 3: Implement bounded explicit coordinates**

Change the signature to accept `x: Optional[float] = None` and
`y: Optional[float] = None`. Preserve centered behavior for every existing
caller and validate explicit coordinates before writing YAML:

```python
if side is None:
    if x is not None or y is not None:
        raise ValueError("x and y require an enabled occlusion")
elif (x is None) != (y is None):
    raise ValueError("x and y must be provided together")
else:
    resolved_x = (1.0 - side) / 2.0 if x is None else float(x)
    resolved_y = (1.0 - side) / 2.0 if y is None else float(y)
    if not all(math.isfinite(value) for value in (side, resolved_x, resolved_y)):
        raise ValueError("occlusion geometry must be finite")
    if side <= 0 or resolved_x < 0 or resolved_y < 0:
        raise ValueError("occlusion geometry must be positive and non-negative")
    if resolved_x + side > 1 or resolved_y + side > 1:
        raise ValueError("occlusion rectangle must fit inside image bounds")
```

Reject booleans and non-numeric `side`, `x`, or `y` before calling
`math.isfinite`. Import `math`, and emit `resolved_x` / `resolved_y` instead of
the calculated center offset. Do not change `run_session`, its constants, its
summary, or its default CLI behavior.

Change `_prepare_session_directory` to accept the keyword-only argument
`session_directory_name: str = SESSION_DIRECTORY_NAME`. Before creating
anything, require a string that is nonempty, not absolute, not `.` or `..`, and
has exactly one `Path(...).parts` element; then construct the child with that
value. Existing `run_session`
continues to call it without the new argument, preserving the completed session
path.

- [x] **Step 4: Run the focused and full suites**

```powershell
& $workspacePython -B -m unittest tests.test_session -v
& $workspacePython -B -m unittest discover -s tests -q
```

Expected: all tests pass; the historical centered configs remain byte-equivalent
apart from no intentional text changes.

- [x] **Step 5: Commit the compatibility increment**

```powershell
git add -- scripts/run_failure_search.py tests/test_session.py
git commit -m "feat(search): support explicit occlusion positions"
```

### Task 2: Implement the separate bounded grid driver

**Files:**
- Create: `scripts/run_position_grid_search.py`
- Create: `tests/test_position_grid_search.py`

- [x] **Step 1: Write the driver contract tests**

Use a local fake command runner and monotonic clock, following the aggregate
fixtures in `tests/test_session.py` without importing that test module. Cover:

```python
EXPECTED_GRID = [
    ("grid-x000-y050", 0.00, 0.50),
    ("grid-x050-y050", 0.50, 0.50),
    ("grid-x000-y000", 0.00, 0.00),
    ("grid-x050-y000", 0.50, 0.00),
    ("grid-x025-y050", 0.25, 0.50),
    ("grid-x000-y025", 0.00, 0.25),
    ("grid-x050-y025", 0.50, 0.25),
    ("grid-x025-y000", 0.25, 0.00),
]
```

Required cases and assertions:

- sentinel success plus eight successes produces nine commands and
  `no_policy_failure_in_grid`;
- the stage order exactly matches `nominal-sentinel` plus `EXPECTED_GRID`;
- each grid YAML contains its exact `x`, `y`, width 0.50, height 0.50, seeds,
  task limit, and one episode;
- a failure at the second cell stops discovery, writes five exact replay
  configs, accepts four failures of five, then runs five nominal controls;
- four or five successful controls produce
  `reproducible_failure_with_nominal_controls`; fewer produce
  `reproducible_failure_nominal_controls_failed`;
- a non-reproducible candidate stops without matched controls;
- a sentinel failure, infrastructure error, wrong episode index, launch cutoff,
  nonempty output directory, and symlinked output directory each stop with the
  specified durable classification.

Also assert the summary's `planned.grid_positions`, `completed.positions_attempted`,
`first_apparent_failure`, `replay_outcomes`, `control_outcomes`, `reproducible`,
`nominal_controls_passed`, elapsed time, and exact perturbation mapping.
Add cutoff, infrastructure, and wrong-index cases during both replay and matched
control phases; assert that incomplete outcome lists never reach a 4/5 gate.

- [x] **Step 2: Run the new tests and confirm import failure**

```powershell
& $workspacePython -B -m unittest tests.test_position_grid_search -v
```

Expected: FAIL because `scripts/run_position_grid_search.py` does not exist.

- [x] **Step 3: Define immutable positions and the public entry point**

Create the new script with these public constants and value type. Insert the
script directory into `sys.path` before importing `run_failure_search as base`,
because importlib-based tests do not automatically add `scripts/`:

```python
SESSION_DIRECTORY_NAME = "position-grid-search"
GRID_SIDE = 0.50
EPISODE_INDEX = 0
REPLAYS_PER_FAILURE = 5
MATCHED_NOMINAL_CONTROLS = 5

@dataclass(frozen=True)
class GridPoint:
    stage: str
    x: float
    y: float

GRID_POINTS = (
    GridPoint("grid-x000-y050", 0.00, 0.50),
    GridPoint("grid-x050-y050", 0.50, 0.50),
    GridPoint("grid-x000-y000", 0.00, 0.00),
    GridPoint("grid-x050-y000", 0.50, 0.00),
    GridPoint("grid-x025-y050", 0.25, 0.50),
    GridPoint("grid-x000-y025", 0.00, 0.25),
    GridPoint("grid-x050-y025", 0.50, 0.25),
    GridPoint("grid-x025-y000", 0.25, 0.00),
)
```

Expose `run_session(...)` with the same injected `command_runner` and
`monotonic_clock` shape as the completed driver. Use a fresh
`position-grid-search` directory by calling
`base._prepare_session_directory(..., session_directory_name=SESSION_DIRECTORY_NAME)`.
Reuse `base.StageResult`, evaluator-command resolution, aggregate loading,
explicit-position YAML writer, atomic JSON, and safe-directory behavior; do not
edit or overwrite a completed session.

Use this exact summary shape; JSON tuples become arrays and absent decisions are
`null`:

```python
summary = {
    "planned": {
        "episode_index": 0,
        "seed": 7,
        "env_seed": 7,
        "grid_side": 0.5,
        "grid_area_fraction": 0.25,
        "grid_positions": [
            {"stage": point.stage, "x": point.x, "y": point.y}
            for point in GRID_POINTS
        ],
        "replays_per_failure": 5,
        "matched_nominal_controls": 5,
        "launch_cutoff_seconds": launch_cutoff_seconds,
    },
    "completed": {
        "stages": [],
        "sentinel_outcome": None,
        "positions_attempted": [],
        "replay_outcomes": [],
        "control_outcomes": [],
    },
    "outcomes": [],
    "first_apparent_failure": None,
    "reproducible": None,
    "nominal_controls_passed": None,
    "elapsed_seconds": 0.0,
    "stop_reason": None,
}
```

`positions_attempted` is a list of coordinate stage-name strings appended after
each launched grid stage records durable evidence. Replay stages are
`replay-1` through `replay-5`; controls are `nominal-control-1` through
`nominal-control-5`. `first_apparent_failure` is either `null` or
`{"stage": str, "x": float, "y": float, "width": 0.5, "height": 0.5}`.
Every stage and outcome carries `perturbation`: nominal uses
`{"enabled": false}`; perturbed stages use
`{"enabled": true, "x": float, "y": float, "width": 0.5, "height": 0.5,
"color": [0, 0, 0], "opacity": 1.0}`. A stage also retains
`planned_episode_indices`, `completed_episodes`, `status`,
`infrastructure_error`, `invalid_evidence`, and `returncode` as in the completed
driver.

- [x] **Step 4: Implement the finite-state sequence**

The implementation must follow this state machine literally:

```python
sentinel = launch("nominal-sentinel", point=None)
if sentinel is None:
    return summary
if sentinel.infrastructure_error is not None:
    save("nominal_sentinel_infrastructure_error")
    return summary
if sentinel.invalid_evidence is not None:
    save("nominal_sentinel_invalid_evidence")
    return summary
sentinel_result = sentinel.results[0]
summary["completed"]["sentinel_outcome"] = sentinel_result.outcome
save()
if sentinel_result.outcome == "infrastructure_error":
    save("nominal_sentinel_infrastructure_error")
    return summary
if sentinel_result.outcome != "success":
    save("nominal_sentinel_failed")
    return summary

candidate = None
for point in GRID_POINTS:
    result = launch(point.stage, point=point)
    if result is None:
        return summary
    summary["completed"]["positions_attempted"].append(point.stage)
    save()
    if result.infrastructure_error is not None:
        save("grid_infrastructure_error")
        return summary
    if result.invalid_evidence is not None:
        save("grid_invalid_evidence")
        return summary
    episode = result.results[0]
    if episode.outcome == "infrastructure_error":
        save("grid_infrastructure_error")
        return summary
    if episode.outcome == "policy_failure":
        candidate = point
        summary["first_apparent_failure"] = {
            "stage": point.stage,
            "x": point.x,
            "y": point.y,
            "width": GRID_SIDE,
            "height": GRID_SIDE,
        }
        save()
        break

if candidate is None:
    save("no_policy_failure_in_grid")
    return summary

for index in range(1, 6):
    replay_stage = launch("replay-{}".format(index), point=candidate)
    if replay_stage is None:
        return summary
    if replay_stage.infrastructure_error is not None:
        save("replay_infrastructure_error")
        return summary
    if replay_stage.invalid_evidence is not None:
        save("replay_invalid_evidence")
        return summary
    replay_result = replay_stage.results[0]
    if replay_result.outcome == "infrastructure_error":
        save("replay_infrastructure_error")
        return summary
    summary["completed"]["replay_outcomes"].append(replay_result.outcome)
    save()
summary["reproducible"] = is_reproducible(
    summary["completed"]["replay_outcomes"]
)
if not summary["reproducible"]:
    save("policy_failure_not_reproducible")
    return summary

for index in range(1, 6):
    control_stage = launch("nominal-control-{}".format(index), point=None)
    if control_stage is None:
        return summary
    if control_stage.infrastructure_error is not None:
        save("control_infrastructure_error")
        return summary
    if control_stage.invalid_evidence is not None:
        save("control_invalid_evidence")
        return summary
    control_result = control_stage.results[0]
    if control_result.outcome == "infrastructure_error":
        save("control_infrastructure_error")
        return summary
    summary["completed"]["control_outcomes"].append(control_result.outcome)
    save()
summary["nominal_controls_passed"] = (
    summary["completed"]["control_outcomes"].count("success") >= 4
)
save(
    "reproducible_failure_with_nominal_controls"
    if summary["nominal_controls_passed"]
    else "reproducible_failure_nominal_controls_failed"
)
return summary
```

Every `launch` first checks `should_launch_next`. It writes the summary after
each stage, records command exceptions/nonzero exits/aggregate errors as
infrastructure evidence, validates that the returned episode is index 0, and
never counts invalid or infrastructure evidence in the 4/5 gates. Replays call
the same config writer with the candidate's exact `x`, `y`, and side. Nominal
controls pass `side=None`, `x=None`, and `y=None`.

- [x] **Step 5: Add the credential-free CLI**

```python
parser.add_argument("--upstream-root", required=True, type=Path)
parser.add_argument("--project-root", required=True, type=Path)
parser.add_argument("--results-root", required=True, type=Path)
parser.add_argument("--launch-cutoff-seconds", type=float, default=1320)
```

The 22-minute launch cutoff leaves four minutes inside a possible future
26-minute VM ceiling. It is a launch gate, not a cloud authorization or a
substitute for the external stop watchdog.

- [x] **Step 6: Run new, legacy, source-tree, and full tests**

```powershell
& $workspacePython -B -m unittest tests.test_position_grid_search -v
& $workspacePython -B -m unittest tests.test_session -v
& $workspacePython -B scripts/run_position_grid_search.py --help
& $workspacePython -B -m unittest discover -s tests -q
```

Expected: all tests pass, help exits 0 without manually setting `PYTHONPATH`,
and the completed severity driver retains its original seven-stage behavior.

- [x] **Step 7: Commit the driver**

```powershell
git add -- scripts/run_position_grid_search.py tests/test_position_grid_search.py
git commit -m "feat(search): add fixed-area position grid"
```

### Task 3: Distinguish equal-area cells in the viewer

**Files:**
- Modify: `src/robot_debug/viewer/web/app.js`
- Modify: `tests/test_viewer_catalog.py`
- Modify: `tests/test_viewer_server.py`

- [x] **Step 1: Add failing coordinate-preservation and asset tests**

Extend the catalog fixture assertion so an enabled occlusion returns its exact
`x` and `y`. Extend the static-asset test to require coordinate-aware labeling
tokens in `app.js`:

```python
# In write_episode's agentview_occlusion fixture:
{"enabled": True, "x": 0.0, "y": 0.5, "width": 0.5, "height": 0.5}

self.assertEqual(episode.perturbation["x"], 0.0)
self.assertEqual(episode.perturbation["y"], 0.5)
self.assertEqual(episode.perturbation["width"], 0.5)

# In test_static_workbench_assets_expose_semantic_landmarks:
javascript = app_body.decode("utf-8")
self.assertIn("perturbationPosition", javascript)
self.assertIn("perturbationPosition(episode)", javascript)
self.assertIn("perturbationPosition(perturbed)", javascript)
self.assertIn("x=", javascript)
self.assertIn("y=", javascript)
```

- [x] **Step 2: Run focused viewer tests and verify the asset test fails**

```powershell
& $workspacePython -B -m unittest tests.test_viewer_catalog tests.test_viewer_server -v
```

Expected: existing catalog mapping passes or needs only fixture coordinates;
the new JavaScript-label assertion fails.

- [x] **Step 3: Implement one compact label helper**

Add and reuse this behavior in the run list and comparison conclusion. In the
comparison function, select the enabled member before formatting so coordinates
still appear when the primary episode is nominal:

```javascript
function perturbationPosition(episode) {
  const fault = episode && episode.perturbation;
  if (!fault || !fault.enabled) return "";
  const x = Number(fault.x);
  const y = Number(fault.y);
  return Number.isFinite(x) && Number.isFinite(y)
    ? ` · x=${x.toFixed(2)} y=${y.toFixed(2)}`
    : "";
}

const perturbed = primary && primary.perturbation.enabled ? primary
  : comparison && comparison.perturbation.enabled ? comparison : null;
```

Keep the existing area label and append the position. Do not add a heatmap,
schema migration, write API, or new dependency.

- [x] **Step 4: Run focused and full tests, then commit**

```powershell
& $workspacePython -B -m unittest tests.test_viewer_catalog tests.test_viewer_server -v
& $workspacePython -B -m unittest discover -s tests -q
git add -- src/robot_debug/viewer/web/app.js tests/test_viewer_catalog.py tests/test_viewer_server.py
git commit -m "feat(viewer): label occlusion coordinates"
```

### Task 4: Integrate and document local readiness

**Files:**
- Create: `docs/experiments/position-grid-search.md`
- Modify: `docs/superpowers/plans/2026-09-12-robot-debugging-startup.md`
- Modify: `docs/superpowers/plans/2026-09-15-position-grid-search.md`

- [x] **Step 1: Run the complete local verification**

```powershell
& $workspacePython -B -m unittest discover -s tests -v
& $workspacePython -B scripts/run_failure_search.py --help
& $workspacePython -B scripts/run_position_grid_search.py --help
git diff --check
```

Expected: zero failures, both CLIs exit 0, and no whitespace errors.

- [x] **Step 2: Treat the explicit contract suite as the fake-evidence audit**

Confirm that named tests explicitly assert one sentinel plus eight unique
coordinate stages on the no-failure path, byte-equivalent discovery/replay
geometry on the positive path, and five unoccluded controls. TemporaryDirectory
fixtures are deleted after tests, so do not claim to inspect their output after
the suite. Do not create synthetic files under the real `artifacts/` tree for
the demo.

- [x] **Step 3: Record readiness without claiming a cloud result**

Create the experiment record with status `local implementation ready; cloud
execution not authorized`. Include the frozen identity, ordered cells, all stop
reasons, 19-episode hard maximum, evidence contract, historical timing estimate,
and the required live preflight. Update the main roadmap to say the position
search is implemented but M2 remains open.

- [x] **Step 4: Mark completed local checkboxes and commit**

```powershell
git add -- docs/experiments/position-grid-search.md docs/superpowers/plans/2026-09-12-robot-debugging-startup.md docs/superpowers/plans/2026-09-15-position-grid-search.md
git commit -m "docs(search): prepare bounded position session"
```

### Task 5: Independent review and learning checkpoint

**Files:** read-only review of every Task 1--4 path

- [ ] **Step 1: Run a specification-compliance review**

Give a fresh reviewer the design, plan, diff, and acceptance criteria. Require
it to report omissions, unapproved scope, legacy-driver regressions, summary
ambiguities, candidate-shopping paths, missing matched-control gates, and
credential/cost leakage. It must not edit the builder's files.

- [ ] **Step 2: Run a code-quality review after compliance passes**

Require a separate review of validation, path safety, atomic persistence,
deadline behavior, Python 3.8 compatibility, test strength, viewer escaping,
and maintainability. The implementation owner fixes findings and reruns the
complete suite before integration.

- [ ] **Step 3: Present the learning checkpoint to Jethro**

Explain:

1. The problem: map spatial sensitivity without making the obstruction larger.
2. Alternatives: larger centered squares or a new perturbation family.
3. Why this design: one variable changes, search order and costs are explicit,
   and matched controls support a stronger positive interpretation.
4. Change-of-direction evidence: no failures across the grid suggests severity
   expansion or a second family; unstable nominal controls require benchmark
   diagnosis before more perturbations.

Invite Jethro to predict which cell will fail before cloud execution. Do not
turn the prediction into a claim.

## RED GATE: Fresh Nebius authorization

Tasks 1--5 do not authorize Task 6. Before any VM start, the integration owner
must renew CLI/browser authentication if needed and recheck the account,
balance, expiry, exact L40S preset, capacity/quota, compute and disk rates,
existing VM/disk state, and temporary-public-IP procedure. Recalculate a hard
maximum from the live all-in rate and the 26-minute ceiling. Jethro must approve
that new cap explicitly.

The historical estimate is about US$0.834 including GST, not an authorization
and not a measured future charge.

### Task 6: Execute and interpret one bounded cloud session

**Files:**
- Create ignored evidence under: `artifacts/position-grid-search-1/`
- Modify after evidence exists: `docs/experiments/position-grid-search.md`
- Modify after evidence exists: `docs/superpowers/plans/2026-09-12-robot-debugging-startup.md`

- [ ] **Step 1: Preflight and arm independent cleanup**

Use one cloud owner. Save credential-free preflight evidence, create only the
temporary exact-egress SSH rule, start the existing VM, and arm a stop request
at minute 24 so shutdown completes inside the 26-minute ceiling. Never rely on
the Python launch cutoff as the VM cost watchdog.

- [ ] **Step 2: Validate the frozen runtime before driver launch**

Confirm the checked-out commit, pinned harness/container/model revisions, GPU,
model cache, HF authorization, model-server readiness, fresh empty results root,
venv evaluator path, and ignored operator-log directory. Stop on mismatch; do
not repair or redesign inside a billable experiment.

- [ ] **Step 3: Run the position driver once**

```bash
/home/robot/.venvs/vla-eval/bin/python \
  scripts/run_position_grid_search.py \
  --upstream-root /home/robot/vla-evaluation-harness \
  --project-root "$PWD" \
  --results-root /home/robot/results/position-grid-search-1 \
  --launch-cutoff-seconds 1320
```

If infrastructure invalidates this logical session, stop and amend the plan
with a distinct run identifier before any retry; never reuse the nonempty root.

- [ ] **Step 4: Collect evidence and clean up first**

Copy summary, aggregate JSON, generated YAML, and logs before media. Request VM
stop by the watchdog boundary, then independently verify `STOPPED` and zero
temporary rules. Never delay cleanup for video transfer.

- [ ] **Step 5: Recompute and expose the result**

Independently recompute the sentinel, ordered cells, first apparent failure,
five replay outcomes, five control outcomes, terminal reason, media counts,
wall time, and cost. Point the viewer at the narrow copied run root and verify
every episode and video. Record only one bounded interpretation from the design,
update M2 status, run the full suite, and commit with:

```powershell
git commit -m "docs(search): record position-grid session"
```

Do not push, publish, begin reduction, add positions, or start another session
without the next explicit boundary.
