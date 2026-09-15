# First Failure Search Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one bounded Nebius session that measures nominal variability, searches a centered-occlusion severity boundary, and confirms the first apparent failure without exceeding US$1 of new session cost.

**Architecture:** Add a small, credential-free Python experiment driver that runs the existing `vla-eval` CLI on the already prepared cloud VM, generates one-run YAML files, classifies aggregate JSON, and stops launching work at a monotonic deadline. Cloud lifecycle and artifact copying remain explicit operator steps so secrets and provider control do not enter the experiment code.

**Tech Stack:** Python 3.8 standard library, existing `vla-eval` CLI, YAML templates emitted as text, GR00T N1.7 LIBERO Object checkpoint, LIBERO/MuJoCo, Nebius L40S VM, JSON/JSONL/MP4 artifacts.

**Execution status (September 15):** Complete on the accepted no-failure branch. The reviewed driver ran on one Nebius L40S: 20/20 nominal episodes and all six centered-square severities succeeded, so no confirmation replay was launched. Independent raw-evidence and viewer checks passed, the VM is stopped, and the temporary SSH rule is absent. The next perturbation-search choice is a new red decision rather than an unapproved extension of this plan.

---

## Accepted experiment design

This plan makes the previously accepted combined session executable. Do not
redesign these choices during implementation unless observed harness behavior
requires a change:

Before changing code, create and switch to `feat/first-failure-search` from the
current local `main`. Keep `main` as the reviewed integration point.

| Decision | Value | Reason |
| --- | --- | --- |
| Task | LIBERO Object task 0, alphabet soup into basket | Working nominal and transformed episodes already exist |
| Nominal sample | Episode indices 0–19 | Twenty distinct LIBERO initial states; seed alone does not select an initial state |
| Nominal gate | At least 16 successes among 20 valid episodes | Existing accepted engineering gate |
| Sweep state | Episode index 0, `seed=7`, `env_seed=7` | Holds task and initial state fixed while changing severity |
| Centered square sides | `0.25, 0.30, 0.35, 0.40, 0.45, 0.50` | Areas are 6.25%, 9%, 12.25%, 16%, 20.25%, and 25% |
| Appearance | Opaque black; wrist image, state, physics, and success predicate unchanged | Same accepted perturbation family as the smoke run |
| First apparent failure | First completed sweep episode with `success=false`; exceptions are infrastructure errors | Prevents setup failures from becoming policy claims |
| Confirmation | Five fresh runs of the exact failing configuration | Measures outcome-level repeatability |
| Reproducible gate | At least four policy failures among five valid replays | Pragmatic hackathon gate, not a statistical guarantee |
| Session ceiling | 30 minutes from VM start, with no new experiment launched after minute 26 | At US$1.7468/hour plus about US$0.0195/hour disk, this remains below US$1 with margin |

If the 20-episode nominal batch contains any infrastructure error or fails the
16/20 gate, preserve its evidence and stop before interpreting the perturbation
sweep. If no severity through 25% fails, record that bounded negative result;
do not expand the search space inside this session.

## Cost calculation

The last verified estimate was US$1.7468 per running hour plus approximately
US$0.0195 per disk-hour. Thirty minutes therefore costs approximately:

```text
0.5 × (1.7468 + 0.0195) = 0.88315 USD
```

The provider billing view remains authoritative. Recheck live price, balance,
capacity, and VM state before starting. The 30-minute ceiling begins when the
VM start operation is issued, not when the model becomes ready.

### Task 1: Implement aggregate classification and the session driver

**Files:**
- Create: `src/robot_debug/session.py`
- Create: `scripts/run_failure_search.py`
- Create: `tests/test_session.py`

- [ ] **Step 1: Write failing tests for aggregate classification**

Test real-shaped dictionaries for `success`, `policy_failure`, and
`infrastructure_error`. Require exceptions to win over a false success metric:

```python
def test_exception_is_not_a_policy_failure(self):
    aggregate = aggregate_with_episode(
        success=False,
        failure_reason="exception",
        failure_detail="model server disconnected",
    )
    result = classify_aggregate(aggregate)
    self.assertEqual(result.outcome, "infrastructure_error")

def test_completed_unsuccessful_episode_is_policy_failure(self):
    result = classify_aggregate(aggregate_with_episode(success=False))
    self.assertEqual(result.outcome, "policy_failure")
```

Also test missing tasks, multiple episodes when exactly one is expected, and a
missing `metrics.success` value. Each must raise `ValueError` instead of being
silently classified.

- [ ] **Step 2: Run the focused tests and observe failure**

```powershell
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest tests.test_session -v
```

Expected: import failure because `robot_debug.session` does not exist.

- [ ] **Step 3: Implement the minimal classification boundary**

In `src/robot_debug/session.py`, define immutable `EpisodeResult` and
`classify_aggregate`. Accept one aggregate containing exactly one task and one
episode. Return its success flag, steps, elapsed seconds, episode index,
failure reason, and one of the three outcomes above.

Keep this module independent of Nebius, SSH, and `vla-eval`; it parses evidence
only.

- [ ] **Step 4: Add failing tests for deadline and replay decisions**

Define and test pure functions with these contracts:

```python
should_launch_next(elapsed_seconds=1559, launch_cutoff_seconds=1560) is True
should_launch_next(elapsed_seconds=1560, launch_cutoff_seconds=1560) is False
is_reproducible(["policy_failure"] * 4 + ["success"], required=4) is True
is_reproducible(["policy_failure"] * 3 + ["success"] * 2, required=4) is False
```

Infrastructure errors must raise `ValueError` in `is_reproducible`; they do not
count as either success or failure.

- [ ] **Step 5: Implement the decision functions and CLI driver**

`scripts/run_failure_search.py` must:

1. accept `--upstream-root`, `--project-root`, `--results-root`, and
   `--launch-cutoff-seconds` (default `1560`);
2. start its monotonic clock immediately;
3. invoke `vla-eval run --config <generated-config>` with
   `subprocess.run(..., cwd=upstream_root, check=False)`;
4. generate configs only under the chosen results/session directory;
5. run the nominal 20-episode configuration first;
6. validate all 20 episode objects directly from the nominal aggregate, count
   successes, and stop on any infrastructure error or fewer than 16 successes;
7. run the six one-episode severities in ascending order while the launch
   cutoff permits;
8. stop the sweep at the first completed policy failure;
9. launch up to five exact replays while the cutoff permits;
10. emit `session_summary.json` after every completed stage using atomic
    replace, including planned work, completed work, outcomes, elapsed time,
    and the reason the driver stopped.

The driver must never call Nebius APIs, start/stop a VM, read credentials, or
delete previous results. Refuse to use a nonempty session directory.

- [ ] **Step 6: Test subprocess boundaries without launching the evaluator**

Inject the command runner and monotonic clock into `run_session`. Use temporary
directories and a fake runner that writes representative aggregate JSON. Cover:

- successful nominal gate followed by no sweep failure;
- first failure followed by five replays and a 4/5 reproducible result;
- nominal infrastructure error stops the session;
- repeated sweep infrastructure error is recorded and stops the session;
- cutoff prevents the next launch but still writes a summary;
- nonempty output directory is rejected.

- [ ] **Step 7: Run tests and commit**

```powershell
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest discover -s tests -v
git diff --check
git add src/robot_debug/session.py scripts/run_failure_search.py tests/test_session.py
git commit -m "feat(search): automate bounded failure session"
```

### Task 2: Prepare the cloud session without spending credit

**Files:**
- Modify: `docs/experiments/first-failure-search.md`

- [ ] **Step 1: Create an experiment record before launch**

Record the accepted table above, current Git commit, harness/container/model
revisions, expected episode maximum (`31`), exact live price, account role,
and the 30-minute stop deadline. Do not include tokens, keys, public IPs, tenant
IDs, or secret-bearing command output.

- [ ] **Step 2: Perform read-only provider checks**

Using the authenticated Nebius CLI, verify:

- selected account/profile and project are the intended account;
- `robot-debug-pilot` is stopped;
- L40S capacity and quota remain sufficient;
- live complete-VM and disk rates keep the 30-minute maximum below US$1;
- balance and credit expiry cover the session.

If any value cannot be verified, stop before VM start and report the missing
fact. Do not provision a replacement VM for this session.

- [ ] **Step 3: Verify local inputs and commit preflight**

Confirm the driver tests pass, the worktree is clean, the dedicated SSH key is
present without printing it, and the local artifact destination is ignored by
Git. Commit only the sanitized experiment record:

```powershell
git add docs/experiments/first-failure-search.md
git commit -m "docs(search): record bounded session preflight"
```

### Task 3: Execute the bounded session

**Files:**
- Generate only: ignored cloud and local artifacts
- Modify after results: `docs/experiments/first-failure-search.md`

- [ ] **Step 1: Start one VM and establish both deadlines**

Record the start time locally before issuing the start operation. Compute a
26-minute experiment-launch cutoff and a 30-minute hard stop. Start only the
existing `robot-debug-pilot` VM. Resolve its temporary public IP after start;
do not publish it or commit it.

- [ ] **Step 2: Check the cached runtime before inference**

Over SSH, confirm the pinned harness checkout, project checkout, container
digest, model cache, free disk, and GPU visibility. Do not update packages or
pull moving tags during the bounded session. Start the existing model server on
loopback and wait for its actual readiness signal.

If readiness consumes more than 8 minutes from VM start, stop the session and
preserve logs; the remaining budget is too small for the accepted experiment.

- [ ] **Step 3: Run the driver**

Use a fresh timestamped result directory and the remaining seconds until the
26-minute launch cutoff. Keep model inference and simulation colocated. Do not
enable sharding or batching in this session: it establishes the sequential
baseline that later HPC work will compare against.

- [ ] **Step 4: Copy evidence before the hard stop**

Copy `session_summary.json`, aggregate JSON, resolved generated configs, and
logs first. Copy JSONL, SQLite, and MP4 files next while time remains. If the
30-minute deadline is near, stop compute even if large media remain on the
managed disk; the stopped disk retains them for a later bounded copy session.

- [ ] **Step 5: Stop and verify**

Stop the VM by the 30-minute deadline. Verify the instance reports stopped and
no additional compute instance was created. Record actual running duration and
provider-visible cost when available. The managed disk may remain for the next
experiment and continues to incur its documented storage charge.

### Task 4: Interpret and expose the result

**Files:**
- Modify: `docs/experiments/first-failure-search.md`
- Modify: `docs/superpowers/plans/2026-09-12-robot-debugging-startup.md`
- Read only: copied `artifacts/<session>/`

- [x] **Step 1: Validate the evidence locally**

Recompute nominal valid/success/error counts from aggregate JSON. Confirm the
severity sequence, first apparent failure, replay count, and reproducibility
gate from raw episode objects rather than trusting only `session_summary.json`.

- [x] **Step 2: Update the experiment report**

Report one of these outcomes precisely:

- baseline gate failed;
- infrastructure invalidated the session;
- no failure through 25% centered occlusion;
- apparent failure was not reproducible;
- reproducible failure found at the stated severity.

Include episode wall time, total session time, estimated and provider-visible
cost, and all relevant revision identities. Do not generalize beyond task 0,
the tested initial state(s), and centered opaque black occlusion.

- [x] **Step 3: Update the main plan and viewer**

Mark only completed gates in the main plan and set its next step from the actual
result. The local viewer indexes copied aggregates automatically; verify the new
runs appear and that infrastructure errors remain separate. Do not modify
artifacts to make them display.

- [x] **Step 4: Test and commit the evidence**

```powershell
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest discover -s tests -v
git diff --check
git add docs/experiments/first-failure-search.md docs/superpowers/plans/2026-09-12-robot-debugging-startup.md
git commit -m "docs(search): record first bounded failure search"
```

## Handoff rules

- The next model may implement Task 1 and perform every read-only Task 2 check
  immediately.
- Starting the stopped VM is already within the accepted combined-session scope
  once the preflight proves the hard maximum remains below US$1 and the active
  account is the intended one.
- Ask Jethro to renew/sign in only if the existing Nebius or Hugging Face
  authentication is actually unavailable; never request tokens in chat.
- Do not begin the later parallel/HPC comparison in this session. This session
  deliberately measures sequential behavior and discovers the case that the
  later scheduler will optimize.
- Commit small coherent units with Conventional Commits. Do not push without
  explicit instruction.
