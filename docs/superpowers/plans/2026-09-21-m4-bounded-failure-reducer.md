# M4 Bounded Failure Reducer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the proven upper-right occlusion failure into a smaller, certified, replayable rectangle without exceeding a fixed episode and cloud budget.

**Architecture:** A pure reducer kernel generates nested edge-strip candidates and applies an adaptive four-of-five gate. A thin session driver reuses the existing evaluator and evidence loader, persists after every attempt, and exports lineage plus a replay manifest for the existing viewer. Local fake-evaluator tests must pass before the single OpenAI-owned Nebius session is proposed.

**Tech Stack:** Python 3.11 standard library, existing YAML-by-template evaluator configuration, `unittest`, GR00T N1.7 with LIBERO Object, existing JSON/JSONL artifacts and local viewer.

**Design:** `docs/superpowers/specs/2026-09-21-m4-bounded-failure-reducer-design.md`

---

## Fixed decisions and review gates

- **Accepted direction:** bounded greedy edge stripping, not binary search or an exhaustive rectangle grid.
- **Failure gate:** accept at four `policy_failure` results; reject at two valid non-failures; maximum five valid attempts per case.
- **Geometry:** parent `(0.50, 0.00, 0.50, 0.50)`; edge order `left, bottom, right, top`; strip sizes `0.125`, then `0.0625`.
- **First-session ceiling:** 23 valid episodes: 1 sentinel, at most 5 parent attempts, 12 candidate attempts, and 5 matched nominal controls.
- **Red checkpoint before paid execution:** Jethro approves the live dollar cap after price, balance, quota, instance state, and estimated duration are refreshed. This plan authorizes no provisioning.
- **Red checkpoint before DeepSeek execution:** Jethro explicitly authorizes sending the isolated kernel task to the configured `deepseek` profile. Scoping it here is not execution authorization.

## File map and exclusive ownership

| Owner | Files | Responsibility |
| --- | --- | --- |
| OpenAI coordinator | `docs/codex-handoff/**`, `docs/decisions/0005-bounded-failure-reduction.md`, `PROJECT_PLAN.md`, Git integration | Red decisions, handoff creation, reviews, merge, cloud lifecycle, evidence interpretation |
| DeepSeek Flash, isolated worktree | `src/robot_debug/reduce.py`, `tests/test_reduce.py` | Pure rectangle/candidate/gate kernel only; no subprocess, network, artifacts, or credentials |
| Terra, isolated worktree after kernel integration | `scripts/run_failure_search.py`, `scripts/run_failure_reduction.py`, `tests/test_failure_search_driver.py`, `tests/test_failure_reduction.py` | Rectangle config compatibility and resumable evaluator integration |
| Luna, after schema freeze | `src/robot_debug/viewer/web/app.js`, `src/robot_debug/viewer/web/styles.css`, `tests/test_viewer_server.py`, `docs/experiments/m4-reducer.md` | Minimal reduction-lineage presentation, usage documentation, focused regression checks |

Workers run sequentially where one consumes another's interface. No worker may
edit outside its owned paths. The OpenAI coordinator alone applies or merges
changes and resolves conflicts.

## Dependency and concurrency map

```text
Task 1 decision record + handoff refresh (OpenAI)
    ├── Task 2 pure kernel (DeepSeek, only after explicit authorization)
    └── Task 3 rectangular config contract (Terra)
             [Tasks 2 and 3 may run concurrently in separate worktrees]
                    ↓ OpenAI review and integration
              Task 4 session driver (Terra)
                    ↓ schema frozen
              Task 5 viewer/docs (Luna)
                    ↓ OpenAI full local verification
              Task 6 dry run + learning checkpoint
                    ↓ fresh user cap approval
              Task 7 one Nebius session (OpenAI only)
                    ↓ human interpretation
              Task 8 evidence/roadmap commit (OpenAI; Luna may draft prose)
```

If DeepSeek is not explicitly authorized or is unavailable, Terra implements
Task 2 from the same test contract. Do not invoke a different external model or
silently change the owner.

### Task 1: Freeze decisions and prepare isolated handoffs

**Owner:** OpenAI coordinator  
**Autonomy:** Amber for documentation; red gate for DeepSeek execution  
**Files:**
- Create: `docs/decisions/0005-bounded-failure-reduction.md`
- Create only if DeepSeek is authorized: `docs/codex-handoff/tasks/2026-09-21-reducer-kernel.md`
- Modify: `docs/codex-handoff/STATE.md`

- [ ] **Step 1: Record the accepted decision**

Write ADR 0005 with status `Accepted`, the three alternatives from the design,
the exact geometry/gate/budget, and the claim boundary. Include this decision:

```markdown
We will use deterministic greedy edge stripping with deltas 0.125 then 0.0625.
A rectangle is accepted after four policy failures and rejected after two valid
non-failures, with at most five attempts. The session stops after 12 candidate
attempts even if a gate is incomplete. The output is budget-local, not globally
minimal or causal.
```

- [ ] **Step 2: Refresh the living handoff pack**

Update `STATE.md` with the accepted M4 contract and list M4 as planned, not
implemented. Verify stable architecture and commands in `PROJECT.md` and
`RUNBOOK.md`; change them only if stale.

- [ ] **Step 3: If authorized, create the required DeepSeek handoff**

Create an isolated worktree using the worktree skill, record its exact path,
branch, and starting commit, then write the required 15-section task document.
Its allowed files are exactly:

```text
src/robot_debug/reduce.py
tests/test_reduce.py
```

Its verification command is:

```powershell
py -3.11 -m unittest tests.test_reduce -v
```

Expected: all reducer tests pass. Forbid network access, cloud commands,
artifact reads/writes, dependency changes, Git publishing, and edits elsewhere.
Stop after two repetitions of the same failure.

- [ ] **Step 4: Commit the decision material**

```powershell
git add docs/decisions/0005-bounded-failure-reduction.md docs/codex-handoff/STATE.md
git commit -m "docs(reducer): accept bounded reduction contract"
```

Add the task handoff document to the same commit only if it contains the real
starting commit and worktree path.

### Task 2: Implement the pure reduction kernel

**Owner:** DeepSeek Flash if explicitly authorized; otherwise Terra  
**Autonomy:** Green inside the frozen contract  
**Files:**
- Create: `src/robot_debug/reduce.py`
- Create: `tests/test_reduce.py`

- [ ] **Step 1: Write geometry tests that fail because the module is absent**

```python
from src.robot_debug.reduce import Rect, candidates

def test_candidates_are_nested_and_ordered(self):
    parent = Rect(x=0.5, y=0.0, width=0.5, height=0.5)
    actual = candidates(parent, delta=0.125)
    self.assertEqual([item.edge for item in actual],
                     ["left", "bottom", "right", "top"])
    self.assertEqual(actual[0].rect, Rect(0.625, 0.0, 0.375, 0.5))
    self.assertEqual(actual[1].rect, Rect(0.5, 0.0, 0.5, 0.375))
    self.assertTrue(all(item.rect.area < parent.area for item in actual))

def test_rect_rejects_out_of_bounds_or_empty_geometry(self):
    for values in ((-.1, 0, .5, .5), (.5, 0, 0, .5), (.8, 0, .3, .5)):
        with self.subTest(values=values), self.assertRaises(ValueError):
            Rect(*values)
```

- [ ] **Step 2: Run the focused test and confirm the expected failure**

```powershell
py -3.11 -m unittest tests.test_reduce -v
```

Expected: import failure for `src.robot_debug.reduce`.

- [ ] **Step 3: Implement immutable geometry and candidates**

Use these public types and signatures exactly:

```python
@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("rectangle values must be finite")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("rectangle dimensions must be positive")
        if self.x < 0 or self.y < 0 or self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("rectangle must remain within normalized image bounds")

    @property
    def area(self) -> float:
        return self.width * self.height

@dataclass(frozen=True)
class Candidate:
    edge: Literal["left", "bottom", "right", "top"]
    rect: Rect

def candidates(parent: Rect, *, delta: float) -> Tuple[Candidate, ...]:
    if not math.isfinite(delta) or delta <= 0:
        raise ValueError("delta must be finite and positive")
    proposed = (
        ("left", Rect(parent.x + delta, parent.y, parent.width - delta, parent.height))
        if parent.width > delta else None,
        ("bottom", Rect(parent.x, parent.y, parent.width, parent.height - delta))
        if parent.height > delta else None,
        ("right", Rect(parent.x, parent.y, parent.width - delta, parent.height))
        if parent.width > delta else None,
        ("top", Rect(parent.x, parent.y + delta, parent.width, parent.height - delta))
        if parent.height > delta else None,
    )
    return tuple(Candidate(item[0], item[1]) for item in proposed if item is not None)
```

Validate finite numbers, positive dimensions/delta, bounds, and strict area
reduction. Omit an edge candidate when removal would leave a non-positive
dimension.

- [ ] **Step 4: Write adaptive-gate tests**

```python
from src.robot_debug.reduce import GateDecision, classify_attempts

def test_gate_passes_at_four_failures(self):
    self.assertEqual(
        classify_attempts(["policy_failure"] * 4), GateDecision.PASS)

def test_gate_rejects_at_two_valid_non_failures(self):
    self.assertEqual(
        classify_attempts(["policy_failure", "success", "success"]),
        GateDecision.REJECT)

def test_gate_is_pending_before_either_boundary(self):
    self.assertEqual(
        classify_attempts(["policy_failure", "success"]),
        GateDecision.PENDING)

def test_gate_rejects_invalid_outcomes(self):
    with self.assertRaises(ValueError):
        classify_attempts(["infrastructure_error"])
```

- [ ] **Step 5: Implement the gate**

```python
class GateDecision(str, Enum):
    PENDING = "pending"
    PASS = "pass"
    REJECT = "reject"

def classify_attempts(outcomes: Sequence[str]) -> GateDecision:
    if len(outcomes) > 5:
        raise ValueError("a repeatability gate permits at most five attempts")
    if any(item not in {"policy_failure", "success"}
           for item in outcomes):
        raise ValueError("only valid policy outcomes may enter the gate")
    failures = outcomes.count("policy_failure")
    non_failures = len(outcomes) - failures
    if failures >= 4:
        return GateDecision.PASS
    if non_failures >= 2:
        return GateDecision.REJECT
    return GateDecision.PENDING
```

- [ ] **Step 6: Run and commit**

```powershell
py -3.11 -m unittest tests.test_reduce -v
git add src/robot_debug/reduce.py tests/test_reduce.py
git commit -m "feat(reducer): add deterministic reduction kernel"
```

Expected: all focused tests pass.

### Task 3: Generalize evaluator configuration to rectangles

**Owner:** Terra  
**Autonomy:** Green; backward compatibility is mandatory  
**Files:**
- Modify: `scripts/run_failure_search.py:315`
- Create: `tests/test_failure_search_driver.py`

- [ ] **Step 1: Add failing compatibility and rectangle tests**

Add tests that assert the old `side=0.5` call still writes equal width and
height, and this new call writes an asymmetric rectangle:

```python
driver._write_config(
    config_path=path,
    output_dir=output,
    project_root=project,
    stage_name="reduce-left",
    episode_indices=(0,),
    side=None,
    x=0.625,
    y=0.0,
    width=0.375,
    height=0.5,
)
self.assertIn("x: 0.625000", path.read_text())
self.assertIn("width: 0.375000", path.read_text())
self.assertIn("height: 0.500000", path.read_text())
```

Also assert `side` mixed with `width`/`height`, only one dimension, or an
out-of-bounds rectangle raises `ValueError`.

- [ ] **Step 2: Run the tests and observe signature failures**

```powershell
py -3.11 -m unittest tests.test_failure_search_driver -v
```

Expected: new rectangle calls fail because `_write_config` lacks the arguments.

- [ ] **Step 3: Extend the function without changing old callers**

Use this signature:

```python
def _write_config(
    *, config_path: Path, output_dir: Path, project_root: Path,
    stage_name: str, episode_indices: Sequence[int],
    side: Optional[float] = None, x: Optional[float] = None,
    y: Optional[float] = None, width: Optional[float] = None,
    height: Optional[float] = None,
) -> None:
```

Resolve dimensions with one exclusive form:

```python
if side is not None and (width is not None or height is not None):
    raise ValueError("use side or width/height, not both")
if (width is None) != (height is None):
    raise ValueError("width and height must be supplied together")
if side is not None:
    width = height = side
enabled = width is not None
```

Retain nominal behavior when all geometry is absent and center square callers
when `side` is supplied without `x,y`. Require explicit `x,y` for a rectangular
form and validate bounds using `x + width` and `y + height`.

- [ ] **Step 4: Run all affected tests and commit**

```powershell
py -3.11 -m unittest tests.test_failure_search_driver tests.test_position_grid_search -v
git add scripts/run_failure_search.py tests/test_failure_search_driver.py
git commit -m "feat(runner): support rectangular occlusion configs"
```

Expected: old square tests and new rectangle tests pass.

### Task 4: Build the resumable reduction session driver

**Owner:** Terra  
**Autonomy:** Amber; follow the frozen sequence exactly  
**Files:**
- Create: `scripts/run_failure_reduction.py`
- Create: `tests/test_failure_reduction.py`

- [ ] **Step 1: Test the pure planned sequence with a fake evaluator**

Create a test harness following `tests/test_position_grid_search.py`: temporary
project/upstream/result roots, deterministic clock, and a command runner that
writes one aggregate result per launch. Cover this path:

```text
nominal sentinel -> success
parent -> policy_failure x4 -> pass
left candidate -> success x2 -> reject
bottom candidate -> policy_failure x4 -> accept
nominal controls -> success x5
```

Assert the final rectangle is `(0.5, 0.0, 0.5, 0.375)`, the left rejection is
retained, the accepted lineage names `bottom`, and every transition was saved.

- [ ] **Step 2: Run and verify the missing-driver failure**

```powershell
py -3.11 -m unittest tests.test_failure_reduction -v
```

Expected: import failure for `scripts/run_failure_reduction.py`.

- [ ] **Step 3: Implement the session constants and public entry point**

```python
SESSION_DIRECTORY_NAME = "failure-reduction"
PARENT_RECT = Rect(0.5, 0.0, 0.5, 0.5)
DELTAS = (0.125, 0.0625)
PARENT_ATTEMPT_BUDGET = 5
CANDIDATE_ATTEMPT_BUDGET = 12
NOMINAL_CONTROLS = 5
TOTAL_VALID_EPISODE_LIMIT = 23

def run_session(
    *, upstream_root: Path | str, project_root: Path | str,
    results_root: Path | str, launch_cutoff_seconds: float = 1320,
    command_runner: Callable = subprocess.run,
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    session = ReductionSession(
        upstream_root=Path(upstream_root).resolve(),
        project_root=Path(project_root).resolve(),
        results_root=Path(results_root).resolve(),
        launch_cutoff_seconds=launch_cutoff_seconds,
        command_runner=command_runner,
        monotonic_clock=monotonic_clock,
    )
    return session.run()
```

Define `ReductionSession` in the same file with one method per transition:
`run_sentinel`, `run_gate`, `run_candidates`, `run_controls`, `save`, and
`run`. Each method returns or records a concrete gate/stop decision; none may
silently catch evaluator or evidence-validation errors.

Use the established `_prepare_session_directory`, `_write_config`,
`_load_stage_results`, `should_launch_next`, and `_atomic_write_json` helpers.
Write `session_summary.json` after every launch and decision.

- [ ] **Step 4: Implement explicit stop reasons and budgets**

The driver must emit only these terminal reasons:

```python
STOP_REASONS = {
    "nominal_sentinel_failed",
    "parent_not_reproducible",
    "candidate_budget_exhausted",
    "local_minimum_reached",
    "reduced_failure_with_nominal_controls",
    "reduced_failure_nominal_controls_failed",
    "launch_cutoff_reached",
    "infrastructure_error",
    "invalid_evidence",
}
```

Never add an infrastructure/invalid result to a gate. If the 12-attempt budget
ends while a candidate is pending, persist decision
`inconclusive_budget_exhausted` and retain the previous certified rectangle.

- [ ] **Step 5: Add restart/resume coverage**

Interrupt the fake runner after a saved candidate attempt, rerun with the same
results root, and assert completed stages are loaded rather than relaunched.
Each stage name must be stable and geometry-derived, for example:

```text
delta-0125-left-x0625-y0000-w0375-h0500-attempt-01
```

Reject a resume when the stored plan constants or parent geometry differ from
the current executable.

- [ ] **Step 6: Add replay manifest coverage**

Assert `replay_case.json` contains:

```json
{
  "schema_version": 1,
  "task_id": 0,
  "episode_index": 0,
  "seed": 7,
  "expected_outcome": "policy_failure",
  "acceptance_rule": {"failures": 4, "attempts": 5},
  "rectangle": {"x": 0.5, "y": 0.0, "width": 0.5, "height": 0.375},
  "source_summary": "session_summary.json"
}
```

The runtime must add the exact replay command and repository revision. Do not
place credentials, absolute user-home paths, or cloud account identifiers in
the manifest.

- [ ] **Step 7: Run focused and regression tests, then commit**

```powershell
py -3.11 -m unittest tests.test_failure_reduction -v
py -3.11 -m unittest tests.test_reduce tests.test_failure_search_driver tests.test_position_grid_search -v
git add scripts/run_failure_reduction.py tests/test_failure_reduction.py
git commit -m "feat(reducer): orchestrate bounded failure reduction"
```

Expected: all focused and affected regression tests pass.

### Task 5: Expose reduction lineage in the existing viewer

**Owner:** Luna  
**Autonomy:** Green after Task 4 freezes the summary schema  
**Files:**
- Modify: `src/robot_debug/viewer/web/app.js`
- Modify: `src/robot_debug/viewer/web/styles.css`
- Modify: `tests/test_viewer_server.py`
- Create: `docs/experiments/m4-reducer.md`

- [ ] **Step 1: Add a failing fixture-backed viewer test**

Create the fixture inside the test's temporary artifact directory, not as a
tracked experiment artifact. Assert the rendered/catalog data exposes:

```text
Parent area: 25.00%
Reduced area: 18.75%
Area reduction: 25.00%
Certification: 4/5 rule passed
```

The viewer must retain equal-size primary and comparison evidence panels.

- [ ] **Step 2: Implement only the lineage presentation**

When `replay_case.json` and an accepted lineage are present, add one compact
“Reduction” block to the existing diagnostics surface. Compute display values
from recorded geometry; do not infer causality or rename ordinary position-grid
runs. Keep all existing catalog and video behavior unchanged.

- [ ] **Step 3: Document local dry-run and replay commands**

`docs/experiments/m4-reducer.md` must distinguish:

```text
1. local fake-evaluator verification (free),
2. live Nebius reduction (requires fresh cap approval),
3. replay of the exported final rectangle,
4. claim limitations and fresh-state work deferred to M6.
```

Use repository-relative placeholders such as `<repo-root>` and
`<upstream-root>`, never Jethro-specific paths.

- [ ] **Step 4: Test and commit**

```powershell
py -3.11 -m unittest tests.test_viewer_server -v
git add src/robot_debug/viewer/web/app.js src/robot_debug/viewer/web/styles.css tests/test_viewer_server.py docs/experiments/m4-reducer.md
git commit -m "feat(viewer): show failure reduction lineage"
```

Expected: focused viewer tests pass.

### Task 6: Independent integration review and free dry run

**Owner:** OpenAI coordinator  
**Autonomy:** Green local review; amber fixes within the accepted design  
**Files:** review all changed paths; no assumed edits

- [ ] **Step 1: Review each worker before integration**

For DeepSeek, inspect the complete diff and independently run its focused test.
Confirm it touched only its two authorized files and report its model, handoff
path, worktree, attempts, and limitations. Perform equivalent ownership checks
for Terra and Luna.

- [ ] **Step 2: Run the complete local suite on Python 3.11**

```powershell
py -3.11 -m unittest discover -s tests -v
git diff --check
git status --short
```

Expected: all tests pass, no whitespace errors, and only intentional changes
remain. If the known WSL environment lacks NumPy, use Windows Python 3.11 for
the project suite and record that environment fact; do not misclassify it as a
reducer failure.

- [ ] **Step 3: Run the fake end-to-end reducer twice**

First run creates evidence; second run proves resume/idempotence. Verify the
catalog has no duplicate logical episodes and no missing media references in
the fixture result.

- [ ] **Step 4: Present the learning checkpoint to Jethro**

Explain the problem, the rejected binary/exhaustive alternatives, why adaptive
four-of-five saves episodes, and what result would cause a redesign. Ask Jethro
to predict which edge will be removable before revealing live evidence later.

### Task 7: Execute one bounded Nebius reducer session

**Owner:** OpenAI coordinator only  
**Autonomy:** Red until Jethro approves the fresh dollar cap  
**Files:** ignored artifacts only during execution

- [ ] **Step 1: Perform read-only preflight**

Verify the selected CLI profile/account, project, region, balance/expiry, GPU
quota/capacity, current all-in instance and disk price, existing instance state,
and absence of stale public firewall access. Ask Jethro to renew local login if
needed; never request a credential pasted into chat.

- [ ] **Step 2: Calculate and request a run-specific cap**

Use the measured evaluator/model startup time plus the 23-episode hard maximum
and teardown margin. Present the calculation and obtain explicit approval. Do
not inherit a previous experiment's cap.

- [ ] **Step 3: Start or resume exactly one worker**

Run one nominal sentinel, parent validation, no more than 12 candidate attempts,
and five controls only after an accepted reduction. Keep observability logs and
persist after every attempt. Do not start parallel workers; parallel scaling is
M3 after M4.

- [ ] **Step 4: Collect and validate artifacts before teardown**

Copy summary, replay manifest, aggregate, traces, and every generated video.
Check episode counts, geometry lineage, outcome categories, hashes/paths, and
viewer indexing. A missing or malformed aggregate invalidates the stage.

- [ ] **Step 5: Tear down and verify stopped/deleted state**

Stop/delete compute according to the existing runbook and remove any temporary
public access rule. Independently list instances, disks, and networking state;
record evidence and estimated actual cost.

### Task 8: Interpret evidence and close M4

**Owner:** OpenAI coordinator; Luna may draft strictly factual prose  
**Autonomy:** Human learning checkpoint before turning evidence into claims  
**Files:**
- Modify: `docs/experiments/m4-reducer.md`
- Modify: `PROJECT_PLAN.md`
- Modify: `docs/codex-handoff/STATE.md`

- [ ] **Step 1: Show raw evidence before the conclusion**

Present the candidate sequence, valid outcomes, budget consumption, timings,
cost, parent/final area, nominal controls, and stop reason. Ask Jethro to
interpret whether the result supports “reduced counterexample” before writing
the submission claim.

- [ ] **Step 2: Record only the supported conclusion**

If a smaller case passed and controls passed, mark M4 complete for the exact
case. If not, record M4 as a valid bounded negative/inconclusive result and do
not call the parent minimal.

- [ ] **Step 3: Update the roadmap**

Set the next material step to M3: equal-work 1/2/4-worker comparison using the
actual reduction workload. Worker topology and a new cloud cap remain separate
red decisions.

- [ ] **Step 4: Commit the evidence documentation**

```powershell
git add docs/experiments/m4-reducer.md PROJECT_PLAN.md docs/codex-handoff/STATE.md
git commit -m "docs(reducer): record bounded M4 evidence"
```

Large artifacts remain ignored and are not committed.

## Completion definition

The implementation phase is complete when the local suite passes, the replay
manifest and viewer lineage work from fake evidence, all worker diffs have been
independently reviewed, and the main branch contains small Conventional Commits.
M4 itself is complete only after an approved live session either certifies a
smaller rectangle with valid nominal controls or exhausts the declared budget
and records that bounded outcome honestly.
