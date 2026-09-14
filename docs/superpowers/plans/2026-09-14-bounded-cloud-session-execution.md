# Bounded Cloud Session Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate and execute the accepted 20-episode nominal baseline, centered-occlusion sweep, and five-replay confirmation on the existing Nebius L40S VM within the user-approved US$2 all-in cap for the aborted boot plus one retry.

**Architecture:** Repair one discovered mismatch between the generated YAML and the pinned evaluator contract, then perform a read-only provider preflight. A single execution owner controls VM lifecycle, the monotonic deadlines, SSH, the evaluator, artifact copying, and shutdown. Independent agents may inspect the upstream contract and validate copied evidence, but they do not mutate the cloud session.

**Tech Stack:** Python 3.8-compatible standard library, AllenAI VLA Evaluation Harness at `35f1200eb15608aa898f727a3722f7eef889c6cd`, NVIDIA GR00T N1.7, LIBERO/MuJoCo, Docker, Nebius CLI on Ubuntu under WSL2, one Nebius L40S VM, OpenSSH, JSON/JSONL/SQLite/MP4 artifacts, local read-only viewer.

---

## Scope and accepted decisions

The experiment design is already accepted. Keep task 0, nominal episode
indices 0–19, the 16/20 nominal gate, the centered opaque-black square side
sequence `0.25, 0.30, 0.35, 0.40, 0.45, 0.50`, episode 0 with both seeds set
to 7, five exact replays, the 4/5 reproducibility gate, one sequential worker,
a 26-minute new-launch cutoff, a 30-minute hard stop, and a US$2 aggregate
maximum covering the already-aborted boot plus exactly one retry. Do not add a
third billable session.

The session can produce at most 31 episodes. Infrastructure errors and invalid
evidence do not count as policy failures. If the nominal gate fails, if model
readiness takes more than eight minutes from VM start, or if the live maximum
including applicable tax exceeds the remaining US$2 aggregate boundary, stop
without expanding the experiment.

## Evidence discovered while writing this plan

The pinned upstream `LIBEROBenchmark.__init__` accepts `suite`, `seed`,
`num_steps_wait`, `send_wrist_image`, `send_state`, `absolute_action`,
`max_steps`, `env_seed`, and `quat_no_antipodal`. It does not accept
`task_ids` or `episode_indices`. The pinned orchestrator truncates the task
list using top-level `max_tasks`, then creates episode indices with
`range(episodes_per_task)`. Therefore:

- top-level `max_tasks: 1` selects LIBERO task 0;
- top-level `episodes_per_task: 20` produces episode indices 0–19;
- top-level `episodes_per_task: 1` produces episode index 0; and
- `task_ids` and `episode_indices` must be removed from `params` before the
  driver is used on the VM.

This is a compatibility repair within the accepted experiment, not a change to
the task or search method.

Official operational references:

- CLI installation: <https://docs.nebius.com/cli/install>
- CLI profiles: <https://docs.nebius.com/cli/configure>
- VM lookup: <https://docs.nebius.com/cli/reference/compute/instance/get-by-name>
- VM start: <https://docs.nebius.com/cli/reference/compute/instance/start>
- VM stop: <https://docs.nebius.com/cli/reference/compute/instance/stop>
- Capacity advice: <https://docs.nebius.com/cli/reference/capacity/resource-advice/list>
- Quota listing: <https://docs.nebius.com/cli/reference/quotas/quota-allowance/list>
- Compute pricing: <https://docs.nebius.com/compute/resources/pricing>

## Dependency and ownership map

```text
Task 1: repair generated config ──┐
                                 ├── Task 3: freeze preflight evidence
Task 2: restore/read cloud CLI ───┘                 │
                                                   ▼
                                      Task 4: single-owner cloud run
                                                   │
                         ┌─────────────────────────┴────────────────────┐
                         ▼                                              ▼
              Task 5A: raw evidence review                 Task 5B: viewer review
                         └─────────────────────────┬────────────────────┘
                                                   ▼
                                      Task 6: report and next decision
```

| Work | Owner | Files/resources | Output |
| --- | --- | --- | --- |
| Config repair | Implementation agent in an isolated worktree | `scripts/run_failure_search.py`, `tests/test_session.py` | Reviewed Conventional Commit |
| Upstream contract review | Read-only reviewer | Pinned upstream source and generated YAML | Contract checklist; no edits |
| CLI/provider preflight | Primary integration owner | WSL Nebius profile; read-only provider APIs | Sanitized preflight evidence |
| Live session | Primary integration owner only | Existing `robot-debug-pilot`, SSH, GPU, session timer | Stopped VM plus copied artifacts |
| Evidence validation | Read-only reviewer | Copied JSON/config/log artifacts | Independent counts and discrepancies |
| Viewer validation | Read-only reviewer | Local artifact viewer | Display acceptance report |
| Git integration/reporting | Primary integration owner | `main`, experiment record, main plan | Tested commits; no push |

Autonomy classification:

- **Green:** Tasks 1–3, local tests, read-only provider checks, evidence
  parsing, documentation, and viewer inspection.
- **Amber:** Task 4 is authorized inside the accepted experiment and US$2
  aggregate cap (the aborted boot plus this one retry).
  The primary owner may execute it after every preflight gate passes.
- **Red:** any new VM, second worker, different model/simulator, new
  perturbation family, changed failure/reproducibility definition, larger
  search range, cap increase, deletion, public push, or submission claim.

### Task 1: Repair the generated evaluator contract

**Files:**
- Modify: `scripts/run_failure_search.py`
- Modify: `tests/test_session.py`

- [ ] **Step 1: Create an isolated worktree**

From the repository root, verify `.worktrees/` remains ignored, then create the
feature worktree:

```powershell
git check-ignore .worktrees
git worktree add .worktrees/fix-upstream-episode-contract -b fix/upstream-episode-contract
```

Expected: the worktree starts from current local `main`, and both checkouts are
clean.

- [ ] **Step 2: Change the config tests first**

In `tests/test_session.py`, replace assertions that require invalid constructor
parameters with assertions for the pinned orchestrator contract:

```python
self.assertIn("episodes_per_task: 20", nominal_config)
self.assertIn("max_tasks: 1", nominal_config)
self.assertNotIn("task_ids:", nominal_config)
self.assertNotIn("episode_indices:", nominal_config)

for side in run_failure_search.SWEEP_SIDES:
    config = (session_dir / "configs" / "sweep-{:.2f}.yaml".format(side)).read_text(
        encoding="utf-8"
    )
    self.assertIn("episodes_per_task: 1", config)
    self.assertIn("max_tasks: 1", config)
    self.assertNotIn("task_ids:", config)
    self.assertNotIn("episode_indices:", config)
```

Keep the existing assertions for `seed`, `env_seed`, rectangle geometry,
colour, opacity, returned episode indices, and exact replay equivalence.

- [ ] **Step 3: Run the focused test and observe failure**

```powershell
$python311 = "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.11.exe"
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $python311 -B -m unittest tests.test_session.SessionDriverTests.test_no_failure_path_runs_nominal_then_all_sweep_severities -v
```

Expected: failure because the generated YAML still contains `task_ids` and
`episode_indices`.

- [ ] **Step 4: Remove the unsupported parameters**

In `_write_config`, keep only benchmark constructor parameters in `params`:

```python
params = [
    "      suite: libero_object",
    "      seed: 7",
    "      env_seed: 7",
    "      num_steps_wait: 10",
]
```

Keep `episodes_per_task: len(episode_indices)` and `max_tasks: 1` at the
top-level benchmark configuration. Keep the expected episode-index validation
after each aggregate; it proves the upstream orchestrator produced the planned
indices.

- [ ] **Step 5: Verify the pinned source contract**

Use a temporary clone outside the repository and inspect the exact commit:

```powershell
$auditRoot = Join-Path $env:TEMP ('vla-contract-' + [guid]::NewGuid().ToString('N'))
git clone --quiet --filter=blob:none --no-checkout https://github.com/allenai/vla-evaluation-harness.git $auditRoot
git -C $auditRoot checkout --quiet 35f1200eb15608aa898f727a3722f7eef889c6cd
Select-String -Path "$auditRoot\src\vla_eval\orchestrator.py" -Pattern 'range\(cfg\.episodes_per_task\)|tasks = tasks\[: cfg\.max_tasks\]'
Select-String -Path "$auditRoot\src\vla_eval\benchmarks\libero\benchmark.py" -Pattern 'def __init__|episode_idx = task.get'
```

Expected: the orchestrator creates `0..episodes_per_task-1`, `max_tasks`
truncates the task list, and LIBERO reads `episode_idx` from the task supplied
by the orchestrator.

- [ ] **Step 6: Run both supported local runtimes**

```powershell
$python311 = "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.11.exe"
$bundledPython = 'C:\Users\Jethro\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $python311 -B -m unittest discover -s tests -v
& $bundledPython -B -m unittest discover -s tests -v
git diff --check
```

Expected: all current tests and the revised contract assertions pass in both
runtimes.

- [ ] **Step 7: Commit and review**

```powershell
git add scripts/run_failure_search.py tests/test_session.py
git commit -m "fix(search): align episode selection with harness"
```

Have a read-only agent compare the generated nominal/sweep/replay configs with
the pinned `EvalConfig`, orchestrator, and `LIBEROBenchmark` signatures. The
primary owner integrates the reviewed commit into `main`.

### Task 2: Restore authenticated Nebius CLI access without spending credit

**Files:**
- No repository files
- Local-only: WSL CLI installation and profile

- [ ] **Step 1: Verify the WSL surface**

```powershell
$wsl = "$env:WINDIR\System32\wsl.exe"
& $wsl --status
& $wsl --list --verbose
& $wsl -d Ubuntu -- bash --noprofile --norc -c 'command -v nebius || true; nebius version 2>/dev/null || true'
```

Expected: Ubuntu runs under WSL2. Current evidence says `nebius` is absent
from its `PATH`.

- [ ] **Step 2: Install the current official CLI if still absent**

Download the official installer into a fresh temporary directory, verify its
origin and inspect its first lines, then run it:

```powershell
& $wsl -d Ubuntu -- bash --noprofile --norc -c '
set -euo pipefail
install_dir=$(mktemp -d)
curl -fL --proto "=https" --tlsv1.2 \
  https://storage.eu-north1.nebius.cloud/cli/install.sh \
  -o "$install_dir/install.sh"
test -s "$install_dir/install.sh"
head -n 20 "$install_dir/install.sh"
bash "$install_dir/install.sh"
command -v nebius || test -x "$HOME/.nebius/bin/nebius"
'
```

If the installer reports another binary location, use that exact location for
the rest of the session and record only the version, not config contents.

- [ ] **Step 3: Check the existing profile**

```powershell
& $wsl -d Ubuntu -- bash -lc 'nebius version; nebius profile list; nebius config get parent-id >/dev/null'
```

Expected: a default profile exists and has a parent project. If authentication
has expired or no profile exists, pause only this dependency and ask Jethro to
run `nebius profile create` interactively in Ubuntu. Resume after
`nebius config get parent-id` succeeds; never request a token in chat.

### Task 3: Freeze the read-only preflight

**Files:**
- Modify: `docs/experiments/first-failure-search.md`

- [ ] **Step 1: Collect sanitized provider evidence**

Run inside Ubuntu. Keep raw JSON in a new temporary directory outside Git and
do not print IDs or addresses into committed output:

```bash
set -euo pipefail
NB_PROJECT_ID="$(nebius config get parent-id)"
NB_PREFLIGHT_DIR="$(mktemp -d)"
nebius compute instance get-by-name \
  --parent-id "$NB_PROJECT_ID" \
  --name robot-debug-pilot \
  --format json > "$NB_PREFLIGHT_DIR/instance.json"
nebius compute platform list \
  --parent-id "$NB_PROJECT_ID" \
  --all --format json > "$NB_PREFLIGHT_DIR/platforms.json"
nebius quotas quota-allowance list \
  --parent-id "$NB_PROJECT_ID" \
  --all --format json > "$NB_PREFLIGHT_DIR/quotas.json"
```

Capacity advice requires the tenant parent rather than the project parent:

```bash
nebius capacity resource-advice list --help
NB_TENANT_ID="$(nebius config get tenant-id)"
[ -n "$NB_TENANT_ID" ] || { echo 'Active profile has no tenant context' >&2; exit 1; }
nebius capacity resource-advice list \
  --parent-id "$NB_TENANT_ID" \
  --all --format json > "$NB_PREFLIGHT_DIR/capacity.json"
```

Acceptance evidence:

- exactly one instance named `robot-debug-pilot` exists and is stopped;
- its platform/preset remains `gpu-l40s-a` / `1gpu-16vcpu-64gb`;
- project quota has room for the existing one-GPU VM and its 200 GiB disk;
- capacity advice reports at least one on-demand slot for that combination;
- no replacement instance is needed.

- [ ] **Step 2: Verify balance, expiry, and effective price**

Use Nebius Console → Billing to record the initial-account balance and expiry,
and Billing → Payments → List prices to confirm the applicable rate. Use
Administration → Limits → Quotas as a cross-check of the CLI quota result.

The official public-rate calculation is:

```text
compute_per_hour = GPU + (16 × vCPU) + (64 × GiB RAM)
disk_per_hour = 200 × network_SSD_per_GiB_month ÷ 730
30_minute_max = 0.5 × (compute_per_hour + disk_per_hour) × applicable_tax_factor
```

Proceed only when the maximum for one 30-minute retry fits the available
balance and the user-approved US$2 aggregate cap. The two-session conservative
bound is `2 x 30_minute_max`; it must remain at or below US$2, because the
provider has not isolated the much-shorter aborted boot's cost. Credits must
remain valid through the session. Preserve exact numbers in the experiment
record; keep account, tenant, project, and payment identifiers out of Git.

- [ ] **Step 3: Verify local inputs**

```powershell
$python311 = "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.11.exe"
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $python311 -B -m unittest discover -s tests -v
git diff --check
git status --short
git check-ignore artifacts results
$sshKey = Join-Path $env:USERPROFILE '.ssh\id_ed25519'
if (-not (Test-Path -LiteralPath $sshKey -PathType Leaf)) { throw 'SSH key is unavailable' }
```

Expected: tests pass, source is clean, artifact destinations are ignored, and
the candidate SSH key exists without printing its contents.

- [ ] **Step 4: Update and commit the experiment record**

Update `docs/experiments/first-failure-search.md` with the current run commit,
CLI version, account role, verified VM state, region, platform/preset, quota
headroom, capacity, effective price, balance sufficiency, expiry sufficiency,
and the calculated maximum. Do not add IDs, addresses, or secret-bearing
output.

```powershell
git add docs/experiments/first-failure-search.md
git commit -m "docs(search): record bounded session preflight"
```

This is the final no-spend gate. If any required field is unavailable, end the
execution batch here with the VM stopped.

### Task 4: Execute the bounded session with one cloud owner

**Files/resources:**
- Generate: ignored `results/` on the VM
- Generate: ignored `artifacts/2026-09-14-first-failure-search/` locally
- Modify after the VM is stopped: `docs/experiments/first-failure-search.md`

- [ ] **Step 1: Prepare a private source transfer**

Because the reviewed commits may not be pushed, transfer them without
publishing:

```powershell
$runCommit = (git rev-parse HEAD).Trim()
$bundlePath = Join-Path (Resolve-Path 'artifacts').Path 'first-failure-search.bundle'
git bundle create $bundlePath HEAD
git bundle verify $bundlePath
```

The bundle is ignored and must contain only Git-tracked project history.

- [ ] **Step 2: Start the existing VM and establish deadlines**

Run the remaining lifecycle commands from one Ubuntu operator shell so its
variables persist. Resolve the project and existing instance from the active
profile, then record UTC epoch seconds before issuing start:

```bash
set -euo pipefail
NB_PROJECT_ID="$(nebius config get parent-id)"
NB_RUN_DIR="$(mktemp -d)"
nebius compute instance get-by-name \
  --parent-id "$NB_PROJECT_ID" \
  --name robot-debug-pilot \
  --format json > "$NB_RUN_DIR/instance-before.json"
NB_INSTANCE_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["metadata"]["id"])' "$NB_RUN_DIR/instance-before.json")"
VM_START_EPOCH="$(date -u +%s)"
VM_LAUNCH_CUTOFF_EPOCH="$((VM_START_EPOCH + 1560))"
VM_HARD_STOP_EPOCH="$((VM_START_EPOCH + 1800))"
VM_STOP_REQUEST_EPOCH="$((VM_START_EPOCH + 1740))"
nebius compute instance start --id "$NB_INSTANCE_ID" --format json > "$NB_RUN_DIR/instance-started.json"
```

Immediately create the independent hard-stop path:

```bash
(
  delay="$((VM_STOP_REQUEST_EPOCH - $(date -u +%s)))"
  if [ "$delay" -gt 0 ]; then sleep "$delay"; fi
  for attempt in 1 2 3; do
    nebius compute instance stop --id "$NB_INSTANCE_ID" --no-progress \
      --timeout 20s --retries 1 >> "$NB_RUN_DIR/hard-stop.log" 2>&1 && break
  done
) &
HARD_STOP_WATCHDOG_PID=$!
```

The watchdog requests stop at minute 29 so the provider has one minute to
finish the transition before the accepted 30-minute ceiling.

- [ ] **Step 3: Resolve temporary SSH access and transfer the source**

Refresh instance JSON after start. Extract one public IPv4 value from fields
whose key contains `public` without printing it:

```bash
nebius compute instance get --id "$NB_INSTANCE_ID" --format json \
  > "$NB_RUN_DIR/instance-active.json"
NB_VM_HOST="$(python3 - "$NB_RUN_DIR/instance-active.json" <<'PY'
import ipaddress
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
found = []
def visit(value, public=False):
    if isinstance(value, dict):
        for key, item in value.items():
            visit(item, public or "public" in key.lower())
    elif isinstance(value, list):
        for item in value:
            visit(item, public)
    elif public and isinstance(value, str):
        try:
            # Current Nebius instance status returns the public address as an
            # IPv4 interface (for example, with a `/32` suffix).  `ip_interface`
            # also accepts a bare IPv4 address and normalizes both forms.
            address = ipaddress.ip_interface(value).ip
        except ValueError:
            return
        if address.version == 4:
            found.append(str(address))
visit(data)
unique = sorted(set(found))
if len(unique) != 1:
    raise SystemExit("expected exactly one public IPv4")
print(unique[0])
PY
)"
```

Verify SSH with the candidate key. If it is accepted, transfer the ignored Git
bundle, fetch it into the existing checkout, and detach at its recorded HEAD:

```bash
SSH_KEY=/mnt/c/Users/Jethro/.ssh/id_ed25519
ssh -o IdentitiesOnly=yes -o BatchMode=yes -i "$SSH_KEY" \
  "robot@${NB_VM_HOST}" true
scp -o IdentitiesOnly=yes -i "$SSH_KEY" \
  /mnt/c/Users/Jethro/Documents/nebius-nvidia-hackathon/artifacts/first-failure-search.bundle \
  "robot@${NB_VM_HOST}:/home/robot/first-failure-search.bundle"
ssh -o IdentitiesOnly=yes -i "$SSH_KEY" "robot@${NB_VM_HOST}" \
  'cd /home/robot/nebius-nvidia-hackathon && git fetch /home/robot/first-failure-search.bundle HEAD && git switch --detach FETCH_HEAD'
```

If the key is not authorized or the workstation `/32` changed, update only the
accepted SSH security-group rule, then retry. Keep port 8000 on loopback.

- [ ] **Step 4: Validate cached runtime before inference**

Over SSH, run:

```bash
set -euo pipefail
test "$(git -C /home/robot/vla-evaluation-harness rev-parse HEAD)" = "35f1200eb15608aa898f727a3722f7eef889c6cd"
test -x /home/robot/.venvs/vla-eval/bin/vla-eval
for model in GR00T-N1.7-3B gr00t17-lerobot-libero_object-640 Cosmos-Reason2-2B; do
  test -n "$(find /home/robot -maxdepth 7 -type d -name "models--nvidia--${model}" -print -quit 2>/dev/null)"
done
git -C /home/robot/nebius-nvidia-hackathon status --short
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
docker image inspect ghcr.io/allenai/vla-evaluation-harness/libero@sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0 >/dev/null
df -h /home/robot
hf auth whoami >/dev/null
```

If any pinned runtime component is absent, stop the VM rather than downloading
a moving replacement inside this session.

- [ ] **Step 5: Start the model server and enforce readiness**

Create a fresh timestamped VM results root and start the server on loopback:

```bash
SESSION_STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
REMOTE_RESULTS_ROOT="/home/robot/results/${SESSION_STAMP}"
ssh -o IdentitiesOnly=yes -i "$SSH_KEY" "robot@${NB_VM_HOST}" \
  bash -s -- "$REMOTE_RESULTS_ROOT" <<'SH'
set -euo pipefail
results_root=$1
mkdir -p "$results_root/operator-logs"
cd /home/robot/vla-evaluation-harness
nohup /home/robot/.venvs/vla-eval/bin/vla-eval serve \
  --config /home/robot/nebius-nvidia-hackathon/configs/model-server.yaml \
  > "$results_root/operator-logs/model-server.log" 2>&1 </dev/null &
printf '%s\n' "$!" > "$results_root/operator-logs/model-server.pid"
SH
```

Poll loopback port 8000 and the remote process every five seconds. Stop if the
process exits, the port is not accepting connections eight minutes after VM
start, or the launch cutoff arrives:

```bash
READINESS_DEADLINE="$((VM_START_EPOCH + 480))"
while ! ssh -o IdentitiesOnly=yes -i "$SSH_KEY" "robot@${NB_VM_HOST}" \
  'bash -lc "exec 3<>/dev/tcp/127.0.0.1/8000"' 2>/dev/null; do
  ssh -o IdentitiesOnly=yes -i "$SSH_KEY" "robot@${NB_VM_HOST}" \
    "kill -0 \$(cat '$REMOTE_RESULTS_ROOT/operator-logs/model-server.pid')"
  now="$(date -u +%s)"
  test "$now" -lt "$READINESS_DEADLINE"
  test "$now" -lt "$VM_LAUNCH_CUTOFF_EPOCH"
  sleep 5
done
```

- [ ] **Step 6: Run the bounded driver**

Compute the remaining launch window from the original VM start time and pass
that duration to the driver:

```bash
NOW_EPOCH="$(date -u +%s)"
REMAINING_LAUNCH_SECONDS="$((VM_LAUNCH_CUTOFF_EPOCH - NOW_EPOCH))"
test "$REMAINING_LAUNCH_SECONDS" -gt 0
ssh -o IdentitiesOnly=yes -i "$SSH_KEY" "robot@${NB_VM_HOST}" \
  bash -s -- "$REMOTE_RESULTS_ROOT" "$REMAINING_LAUNCH_SECONDS" <<'SH'
set -euo pipefail
results_root=$1
remaining_seconds=$2
export PATH="/home/robot/.venvs/vla-eval/bin:$PATH"
cd /home/robot/vla-evaluation-harness
/home/robot/.venvs/vla-eval/bin/python \
  /home/robot/nebius-nvidia-hackathon/scripts/run_failure_search.py \
  --upstream-root /home/robot/vla-evaluation-harness \
  --project-root /home/robot/nebius-nvidia-hackathon \
  --results-root "$results_root" \
  --launch-cutoff-seconds "$remaining_seconds" \
  > "$results_root/operator-logs/driver.log" 2>&1
SH
```

The driver stops after the nominal gate, the first sweep failure plus replays,
all six successful severities, infrastructure evidence, or the cutoff.

- [ ] **Step 7: Copy evidence in priority order**

Create the ignored local destination and copy summary/config/aggregate/log
evidence before larger recordings:

```bash
LOCAL_ARTIFACTS=/mnt/c/Users/Jethro/Documents/nebius-nvidia-hackathon/artifacts/2026-09-14-first-failure-search
LOCAL_SESSION_ARTIFACTS="$LOCAL_ARTIFACTS/first-failure-search"
mkdir -p "$LOCAL_SESSION_ARTIFACTS"
scp -o IdentitiesOnly=yes -i "$SSH_KEY" -r \
  "robot@${NB_VM_HOST}:${REMOTE_RESULTS_ROOT}/first-failure-search/session_summary.json" \
  "robot@${NB_VM_HOST}:${REMOTE_RESULTS_ROOT}/first-failure-search/configs" \
  "$LOCAL_SESSION_ARTIFACTS/"
scp -o IdentitiesOnly=yes -i "$SSH_KEY" -r \
  "robot@${NB_VM_HOST}:${REMOTE_RESULTS_ROOT}/operator-logs" \
  "$LOCAL_ARTIFACTS/"
ssh -o IdentitiesOnly=yes -i "$SSH_KEY" "robot@${NB_VM_HOST}" \
  "cd '$REMOTE_RESULTS_ROOT' && find first-failure-search/runs -type f -name '*_aggregate.json' -print0 | tar --null -T - -czf operator-logs/aggregates.tar.gz"
scp -o IdentitiesOnly=yes -i "$SSH_KEY" \
  "robot@${NB_VM_HOST}:${REMOTE_RESULTS_ROOT}/operator-logs/aggregates.tar.gz" \
  "$LOCAL_ARTIFACTS/"
tar -xzf "$LOCAL_ARTIFACTS/aggregates.tar.gz" -C "$LOCAL_ARTIFACTS"
scp -o IdentitiesOnly=yes -i "$SSH_KEY" -r \
  "robot@${NB_VM_HOST}:${REMOTE_RESULTS_ROOT}/first-failure-search/runs" \
  "$LOCAL_SESSION_ARTIFACTS/"
```

If the hard stop is close, stop compute before copying large media; the managed
disk retains files for a later bounded copy.

- [ ] **Step 8: Stop and verify**

```bash
nebius compute instance stop --id "$NB_INSTANCE_ID" --format json > "$NB_RUN_DIR/instance-stopped.json"
nebius compute instance get --id "$NB_INSTANCE_ID" --format json > "$NB_RUN_DIR/instance-after.json"
nebius compute instance list --parent-id "$NB_PROJECT_ID" --all --format json > "$NB_RUN_DIR/instances-after.json"
```

Verify `robot-debug-pilot` is stopped before cancelling the watchdog, there is
still only the intended instance, and record actual running duration and
provider-visible cost.

After the provider confirms the stopped state:

```bash
kill "$HARD_STOP_WATCHDOG_PID" 2>/dev/null || true
wait "$HARD_STOP_WATCHDOG_PID" 2>/dev/null || true
```

### Task 5: Validate evidence and the viewer in parallel

**Files:**
- Read only: `artifacts/2026-09-14-first-failure-search/`
- Read only: `src/robot_debug/viewer/`

- [ ] **Step 1: Assign non-overlapping reviews**

The evidence reviewer must:

- recompute nominal episode indices, valid/error counts, and successes from raw
  aggregate episode objects;
- confirm severity order and geometry from generated configs;
- identify the first apparent failure and recount all replay outcomes;
- compare those values with `session_summary.json`; and
- report timing and missing artifacts.

The viewer reviewer must:

- launch the local viewer against `artifacts/`;
- confirm valid and infrastructure episodes appear separately;
- verify videos and traces load when present; and
- capture one local screenshot only if it improves the demo record.

Neither reviewer edits artifacts or makes experiment claims.

- [ ] **Step 2: Resolve discrepancies before reporting**

The primary owner compares both reviews with the raw evidence. Any mismatch
between summary and aggregate, wrong episode index, missing severity, or
infrastructure error invalidates the affected conclusion. Preserve the raw
files unchanged.

### Task 6: Record the result and set the next learning checkpoint

**Files:**
- Modify: `docs/experiments/first-failure-search.md`
- Modify: `docs/superpowers/plans/2026-09-12-robot-debugging-startup.md`

- [ ] **Step 1: Ask Jethro to predict or interpret the bounded outcome**

Present the raw counts, first-failure severity if one exists, replay outcomes,
wall time, and cost before turning them into a project claim. Ask what result
Jethro expected and what explanation seems plausible.

- [ ] **Step 2: Write the bounded interpretation**

Record exactly one supported outcome:

- nominal gate failed;
- infrastructure invalidated the session;
- no failure through 25% centered occlusion;
- apparent failure was not reproducible; or
- reproducible failure found at the stated severity.

Include actual episode and VM timing, effective and provider-visible cost,
revisions, missing artifacts, and the narrow task/state/perturbation scope.

- [ ] **Step 3: Update the main plan**

Mark the baseline/sweep/replay step complete only if its evidence gates passed.
Choose the next experiment from the observed result. A reduction algorithm,
parallel worker topology, or new perturbation family is a new red decision and
requires a learning checkpoint before implementation.

- [ ] **Step 4: Test and commit**

```powershell
$python311 = "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.11.exe"
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $python311 -B -m unittest discover -s tests -v
git diff --check
git add docs/experiments/first-failure-search.md docs/superpowers/plans/2026-09-12-robot-debugging-startup.md
git commit -m "docs(search): record bounded failure search"
```

Do not push or publish the result without Jethro's explicit instruction.

## Plan acceptance criteria

- Generated YAML matches the pinned evaluator contract before cloud start.
- The authenticated account, profile, project, VM state, capacity, quota,
  balance, expiry, price, and the effective US$2 aggregate maximum are
  verified.
- Only the existing one-L40S VM runs, with one execution owner.
- No new episode launches after 26 minutes and the VM is stopped by 30 minutes.
- Raw evidence is copied before interpretation and independently recounted.
- The viewer displays the new evidence without changing it.
- Commits are small, conventional, tested, local, and free of secrets.
