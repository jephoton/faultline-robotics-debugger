# M3 Reusable Launcher Implementation Plan

> **For agentic workers:** Use subagent-driven-development with test-driven-development for each implementation unit. Root integrates; agents never run real Nebius, SSH or resource deletion. Steps use checkboxes.

**Goal:** Build one reusable launcher that persists across chat interruptions, safely executes the existing comparison, and supports read-only reattachment.

**Architecture:** An OS-owned workstation controller becomes ready before the sole VM start and delegates the unchanged paired experiment to the existing guest runner. Durable intent records prevent automatic duplicate mutations; the existing exact-VM watchdog remains independent. Recovery after controller death is stop/copy/cleanup-only.

**Tech Stack:** Python standard library, unittest, Windows Task Scheduler, existing WSL Nebius CLI and SSH/scp, existing guest Python/Bash and portfolio code. No new cloud service or Python dependency.

**Authority:** Jethro approved the [design](../specs/2026-10-01-m3-reusable-launcher-design.md) and asked to execute local implementation. The prior cloud cap is exhausted. Real scheduled-controller release, billable provisioning/start and resource deletion require a fresh separately approved run record and preflight. Local fake tasks may be registered and removed against their exact test name only.

## Owners, concurrency and review

**Independent review gate:** Task 1 proceeds independently. Before controller
integration, settle storage cleanup after controller death: the stop-only
watchdog cannot guarantee the snapshot/disk deadline. Root asked Jethro to
choose a separately prearmed exact-temporary-resource cleanup task versus
explicit manual recovery risk. Neither is silently assumed approved. A
confirmed watchdog stop is evidence, not a guarantee that every future stop
succeeds; exhausted retries report unconfirmed stop. Human emergency exact-ID
stop remains allowed; controller observes it and closes admission.

Historical `status` inspection validates record shape/digest without requiring
accessible key/bundle files or current hashes of those inputs. Mutating
prepare/release validates their existence, trust and hashes separately. The
`require_future=False` loader mode must support this distinction.

Root owns this plan, integration, user checkpoints and any future external lifecycle. Reuse the clean attached M3 worktree on a new `codex/` branch based on this committed plan; do not alter main code during agent execution. Terra is preferred but is not exposed by the subagent API: use available `gpt-6-luna` for isolated record work, and balanced `gpt-6-sol` for multi-file controller/adapter work. Root's active model is not changed.

One builder owns code/tests at a time. A read-only contract reviewer analyzes fault cases alongside Task 1, then checks each task against the approved spec. Only after spec review passes, a separate code-quality reviewer checks implementation/tests. Both reviews must pass before dependent tasks. Fresh builders receive full task text, previous accepted interfaces and evidence. No overlapping writes or agent cloud credentials.

Dependency map: Task 1 records → Task 2 controller → Task 4 host wiring; Task 3 guest scripts follows accepted record contract and precedes Task 4 integration. Task 5 depends on all code. Root documentation/integration Task 6 follows independent review. Reviewer contract analysis can run alongside implementation; reviewers never alter state. Stop at new red decisions, not routine fixes.

## Frozen scope and file ownership

New files:

- `src/robot_debug/cloud_run_record.py`: immutable input validation, integrity digests, durable events/status and exclusive run lease.
- `src/robot_debug/cloud_run_controller.py`: injectable phase machine, bounded recovery and deadline accounting.
- `src/robot_debug/cloud_run_backend.py`: validated Nebius/SSH/transfer operations plus physically separate fake backend. This helper keeps command construction out of the phase machine.
- `scripts/run_cloud_comparison.py`: prepare/arm/release/status/recover CLI and hidden scheduled-task registration.
- `scripts/cloud_guest/preflight.sh`, `model-launch.sh`, `launch-pair.sh`, `run-pair.sh`, `validate-mode.py`: sanitized reusable working scripts.
- `tests/test_cloud_run_record.py`, `tests/test_cloud_run_controller.py`, `tests/test_cloud_run_backend.py`, `tests/test_cloud_run_cli.py`, `tests/test_cloud_guest.py`.
- `docs/setup/reusable-cloud-launcher.md`: verified commands and limitation/recovery guide.

Root updates `PROJECT_PLAN.md`, `docs/codex-handoff/STATE.md`, `docs/dev-log.md`, and `FEEDBACK.md` only for observed tool behavior. No provider feedback from simulations. Existing policy/simulator/config/report/viewer/watchdog code is outside scope. Existing private scripts are reference data, not safe to copy verbatim: remove infrastructure/session/user identifiers before tracking.

## Task 1 — Strict run records and local persistence (green)

**Owner:** smaller builder. **Files:** `cloud_run_record.py`, `test_cloud_run_record.py` only.

- [ ] Write failing unittest cases for a valid synthetic record, rejected unknown/secret fields, wrong schema, bool/nonfinite numeric values, malformed IDs/hashes, overlapping protected targets, contained paths, future UTC deadlines, immutable digest, lease collision and interrupted atomic writes.
- [ ] Implement `RecordError(ValueError)`, frozen `CloudRunRecord`, `load_record(path, *, control_root, now_utc, require_future=True)`, and `RunStore(run_dir)` with methods `create(record_digest)`, `append(event, **safe_fields)`, `snapshot(payload)`, `read_status()`, `acquire_lease(owner_id)`, `release_lease(owner_id)`.
- [ ] Record JSON has exactly these top-level keys: `schema_version`, `run_label`, `project_id`, `temporary`, `protected`, `approval`, `deadlines`, `paths`, `pins`, `ssh`, `preflight`. Each nested object rejects unknown keys. No arbitrary command/script field or secret-bearing value is accepted.

```json
{
  "schema_version": 1,
  "run_label": "local-example",
  "project_id": "project-example",
  "temporary": {"instance_id": "computeinstance-clone", "disk_id": "computedisk-clone", "snapshot_id": "computedisksnapshot-clone", "ssh_rule_id": "vpcsecurityrule-clone"},
  "protected": {"instance_id": "computeinstance-original", "disk_id": "computedisk-original"},
  "approval": {"reference": "local-test-only", "max_total_usd": 8.0, "max_starts": 1, "max_runtime_seconds": 5400, "temporary_cleanup": true},
  "deadlines": {"start_not_after_utc": "2030-01-01T00:10:00Z", "stop_request_utc": "2030-01-01T01:27:00Z", "stop_confirm_by_utc": "2030-01-01T01:30:00Z", "storage_cleanup_utc": "2030-01-01T03:00:00Z"},
  "paths": {"run_dir": "ABSOLUTE_LOCAL_RUN_DIR", "source_bundle": "ABSOLUTE_LOCAL_BUNDLE", "manifest": "ABSOLUTE_LOCAL_MANIFEST", "known_hosts": "ABSOLUTE_LOCAL_KNOWN_HOSTS", "ssh_identity_file": "ABSOLUTE_LOCAL_KEY_PATH", "guest_session": "/home/robot/local-example", "wsl_cli": "/home/local/.nebius/bin/nebius"},
  "pins": {"source_sha": "1111111111111111111111111111111111111111", "bundle_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "manifest_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "upstream_sha": "35f1200eb15608aa898f727a3722f7eef889c6cd", "checkpoint_id": "nvidia/gr00t17-lerobot-libero_object-640", "checkpoint_revision": "1499db357f6ca3762b56c2e8c00b530eb9a09444", "simulator_digest": "sha256:d0c45bc5a3720d569180e6b8dd92510da895f16c3cc509ccc76e4b4ffbb9e0f0"},
  "ssh": {"user": "robot", "host_key_sha256": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "port": 22},
  "preflight": {"checked_at_utc": "2030-01-01T00:00:00Z", "balance_usd": 10.0, "pending_usd": 0.0, "estimated_total_usd": 7.55, "hourly_rate_usd": 4.5, "expiry_checked": true, "quota_checked": true, "capacity_checked": true, "billing_checked": true}
}
```

The example is a synthetic fixture, not approval or usable credentials. Tests replace symbolic local paths with temporary absolute paths; no example account or VM is queried. Identity path stores a location only; do not read or log key contents. Input paths for bundle/manifest must be existing regular files under control root; known-hosts/key paths must be explicit absolute regular files, not necessarily inside control root. Reject symlink/reparse escapes for writable run paths. Require a dedicated run_dir strictly below control root, never root itself. POSIX guest session is a dedicated absolute descendant of `/home/robot/`, with safe path segments, no traversal/metacharacters. WSL CLI absolute path only.

IDs have their stated service prefix and safe ASCII suffix; temporary and protected instance/disk identities must differ. Exact numeric types, finite positive caps/rates, nonnegative pending, one start, runtime at most the approved recorded limit; expiry/quota/capacity/billing flags must be true. Bounds are not new spending authority. Preflight cannot be future-dated and must be at most ten minutes old for prepare/release; status/recovery can inspect expired records. Balance less pending must cover conservative total, which must not exceed cap. Require ordered stop-request/confirmation/storage deadlines and start-not-after before stop-request; controller separately checks runtime against actual start intent.

Digest canonical JSON bytes with sorted keys and compact separators; revalidate source bundle and manifest SHA256 before release. Store original immutable record separately from status, compare digest on every mutating entry point. Events are JSONL, append then flush/fsync; tolerate only a truncated final event during read, reject corruption earlier. Snapshot uses temp-file + flush/fsync + `os.replace`. Lease uses exclusive file create; duplicate acquisition refuses. No automatic stale-lease removal. Store safe event data only (phase, UTC, operation identifiers, exit classification), not unfiltered command stderr.

```python
# Acceptance interface exercised by tests (fixture is generated locally):
record = load_record(record_path, control_root=tmp_root, now_utc=now)
store = RunStore(record.paths["run_dir"])
store.create(record.digest)
store.acquire_lease("controller-example")
store.append("controller_ready", owner_id="controller-example")
store.snapshot({"phase": "waiting_release", "record_digest": record.digest})
assert store.read_status()["phase"] == "waiting_release"
```

- [ ] Run `C:/Windows/py.exe -3.11 -m unittest discover -s tests -p test_cloud_run_record.py -v` with `PYTHONPATH=src`; initially fail, then pass. Existing module conventions use unittest, not a new framework.
- [ ] Self-review and commit explicit two paths: `feat(cloud): add immutable launcher run records`. Return tests, SHA, API and concerns; wait for independent spec/quality reviews before dependencies.

## Task 2 — Injectable controller and recovery state machine (amber)

**Owner:** balanced builder after Task 1 review. **Files:** controller and its tests.

- [ ] Write fake-backend tests with an operation list and injected UTC/monotonic clock. Backend has explicit methods `verify_target`, `verify_guard`, `start_once`, `wait_running`, `prepare_guest`, `launch_pair_once`, `inspect_pair`, `copy_artifacts`, `stop`, `verify_stopped`, `delete_temporary`, `verify_cleanup`, `retire_guard`. Tests never spawn cloud tools.
- [ ] Implement `Controller(record, store, backend, *, now_utc, sleep)` with `wait_release()`, `execute()`, `recover_only()`. Store phase and intent before each side effect. Main sequence is `waiting_release → verifying → start_intent → started → guest_ready → guest_launch_intent → running → recovering → stopping → stopped → cleaning → terminal`. Failures transition to recovery; unconfirmed stop/cleanup is a terminal error retaining safety ownership, never a success.
- [ ] `wait_release` validates exact digest-bound release, not mere file existence. Before start revalidate fresh preflight/deadlines/pins, guard armed evidence, exact stopped target/ownership and no existing start intent. Record `start_intent` with actual UTC before one start call. Never repeat start on exception. Bound stop-request deadline to actual start plus approved runtime minus stop-confirm reserve; an earlier immutable deadline wins. No deadline extension.
- [ ] Establish guest backup shutdown before experiment launch. Guest setup can retry bounded reads/transfers; ambiguous side-effect acknowledgements are not retried. Write guest launch intent before submission, read back remote launch marker/PID after lost reply, and if identity cannot be proven go to stop/recovery without another launch.
- [ ] Poll/copy in short bounded steps, check remaining time before every phase. Pair gates remain 4500 seconds before sequential and 2400 before adaptive; no shrinking one mode. At guard deadline no new diagnostic work; stop/recovery only. Keep original evaluator/ledger ownership checks. Do not enter adaptive after invalid/uncertain work.
- [ ] Recovery copies while safe but stops before budget deadline; copy from stopped disk is not assumed accessible. At storage deadline obey approved exact cleanup and report unresolved/lost artifacts. A fake timeout must not hang tests. Controller death never authorizes scheduled restart; recover_only checks exclusive ownership and records stop/copy/cleanup only.

```python
# Fake-backend acceptance predicates, not a production command:
assert calls.count("start_once") <= 1
assert calls.count("launch_pair_once") <= 1
assert calls.index("verify_guard") < calls.index("start_once")
assert "retire_guard" not in calls_when_stop_unconfirmed
assert not any(c in recovery_calls for c in ("start_once", "prepare_guest", "launch_pair_once"))
```

- [ ] Inject failures before/after start intent, after remote start but before reply, before/after guest intent, mid-copy, during stop and deletion. Assert no new work, originals untouched, pending media unverified, terminal partial/error accurately reported. Enforce bounded total recovery deadline, not an unbounded `finally` loop.
- [ ] Run focused record/controller tests, commit `feat(cloud): persist comparison lifecycle ownership`; independent spec then quality reviews.

## Task 3 — Reusable guest scripts without experimental drift (green/amber)

**Owner:** fresh balanced builder after record/controller interfaces accepted. **Files:** guest script directory and guest tests only.

- [ ] Read the successful screen experiment note and ignored `artifacts/m3-control/m3-portfolio-20261001t1016/` reference scripts from primary checkout without copying IDs, logs or keys into Git. Compare commands to the prior live plan.
- [ ] Create reusable scripts parameterized by validated session path and fixed input files, with no arbitrary command field. Preserve actual model interpreter, offline cache, pinned upstream/checkpoint/image, model port and diagnostic pair arguments. Source SHA is per-run frozen; manifests immutable. Keep GPU/catalog/model verification and strict unknown-context rejection.
- [ ] `launch-pair.sh` exclusive-creates guest launch intent before launch, writes durable PID/identity, refuses duplicates. `run-pair.sh` writes phase/exit markers, preserves exit 1, invokes unchanged validator, and enforces 4500/2400 gates and no owned/unowned live evaluator uncertainty. Never rerun into existing results roots.
- [ ] Keep matched CLI: sequential-jobs then adaptive-portfolio with max-workers 2; 111 episodes, 1800 seconds, identical dollar limit derived from verified hourly rate. No new failure criterion/search family or selector/timing table edits.
- [ ] Test scripts with fake executables and synthetic summary/ledger/media trees; assert mode order, CLI arguments, gate rejection, duplicate launch refusal, nonzero exit evidence and no adaptive launch after invalid ownership. Run Bash syntax checks through WSL locally; no guest or cloud connections.
- [ ] Commit `feat(cloud): reuse guarded guest comparison scripts`; independent spec then quality review verifies pin and command drift against originals.

## Task 4 — Production backend and hidden scheduled-task CLI (amber)

**Owner:** balanced builder. **Files:** backend, CLI and corresponding tests.

- [ ] Implement argparse commands `prepare`, `arm`, `release`, `status`, `recover`; private `controller` is scheduled-only. All require `--record` and `--control-root`. `--local-test --fake-scenario FILE` selects fake backend before any production tool resolution; either flag without the other rejects. Production fake scenarios and arbitrary command injection reject.
- [ ] `prepare` validates/freeze inputs and read-only exact resource/guard checks. It does not create cloud resources. `arm` schedules hidden controller with no restart policy and an exact run-scoped safe task name; returns only after durable ready handshake plus process/task liveness. `release` requires a live ready controller and armed exact guard, validates fresh preflight/pins again, then atomic exclusive digest-bound permission. It does not itself start VM. `status` reads local state only; `recover` refuses a live lease and never launches diagnostics.
- [ ] Use Windows PowerShell scheduled-task APIs with fixed script and argument arrays, `-WindowStyle Hidden` where launching helpers, explicit executable/cwd/source path, no tokens or arbitrary shell snippets. Match proven watchdog scheduled-task behavior. Check registration/readback rather than assuming `DETACHED_PROCESS` is durable. Automatic restart and startup triggers are disabled. Do not unregister a task belonging to another run.
- [ ] Production backend uses existing absolute WSL CLI invocation, timeout/noninteractive flags and JSON exact-ID readbacks. Get/stop retry bounded; start no retries. Disk/snapshot/rule ownership checked before cleanup; already-absent targets distinguished from forbidden/failed lookup. Preserve original VM/disk. Do not swallow a permission failure as `NotFound`.
- [ ] Resolve new VM IP from exact instance readback. SSH batch mode, pinned identity file and dedicated known-hosts file, `StrictHostKeyChecking=yes`; verify trusted host fingerprint, never disable checking or treat unauthenticated `ssh-keyscan` as trust. If fresh clone host key cannot be verified from a trusted channel, fail readiness and stop; root supplies verified trust at a future preflight, not a silent security exception.
- [ ] Copy only enumerated session artifacts through staged partial files; sanitize remote relative paths, reject symlinks/traversal and preserve mode/job/case paths. Verify size/SHA256 against guest inventory before atomic promotion. A live growing log is copied as an unverified snapshot until finalized; never label it a complete MP4. Bound copy rounds and total time.
- [ ] Test command argv, timeout handling, safe task naming/registration/readback, fake-mode zero production calls, duplicate arm/release, stale approval, host mismatch, remote path injection and exact cleanup. Commit `feat(cloud): add scheduled comparison launcher`; independent spec then quality reviews.

## Task 5 — Parent-exit and crash-boundary local acceptance (green)

**Owner:** fresh builder plus read-only reviewers. **Files:** tests and operational guide.

- [ ] Launch an OS-owned fake controller with temporary local fixture paths and unique task name. Exit its short-lived initiating process; assert controller reaches terminal, one fake start/launch, copied fake video/trace checksums, verified fake cleanup. Fake backend cannot invoke Nebius, WSL or SSH even on failure.
- [ ] Kill fake controller after durable start/guest launch intents. Reinvoke status and recover_only; assert no restart or new diagnostic call. Test lease/collision and terminal output under truncated event tail. Remove only exact test task after child verified ended; record cleanup evidence.
- [ ] If Windows task registration is unavailable, mark scheduled durability acceptance incomplete, not passed by mocking; still run injected backend tests. No paid start until real local scheduled fake acceptance is verified.
- [ ] Write `docs/setup/reusable-cloud-launcher.md` with tested prepare/arm/release/status/recover commands using user-neutral placeholders, explanation of one-start release, exact-run ownership and workstation sleep/auth/network limitations. Expose private status path as the progress UI, not an unimplemented viewer feature.
- [ ] Run full Windows tests and focused WSL lifecycle/guest suites; tests expected to pass with existing platform skips reported. Commit `test(cloud): verify launcher survives parent exit` and separately `docs(cloud): explain reusable launcher recovery`.

## Task 6 — Root integration and learning checkpoint (green)

- [ ] Obtain final independent spec review, then code-quality/security review of complete branch. No unresolved important findings before integration. Root verifies test counts, diff, no IDs/secrets/private logs and unchanged policy/config/report semantics.
- [ ] Update main plan, handoff and dev-log with implemented versus actually scheduled-tested status; record any discovered project bug, not fake provider feedback. Name brainstorming stays next product-facing task. Live comparison remains pending.
- [ ] Integrate reviewed commits without overwriting user work. Run fresh full tests plus `git diff --check`; commit explicit docs. Push only under existing user publication authority; verify remote SHA. Preserve worktree until no needed ignored fixture/evidence remains, then archive through native tool.
- [ ] Return what now survives interruption, demonstrated failure limits and commands; before paid execution refresh billing/capacity/prices/auth and request a new numeric cap. Do not reuse exhausted one-start authority.

## Exact recurring local checks

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p 'test_cloud_run*.py' -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -p 'test_cloud_guest.py' -v
C:/Windows/py.exe -3.11 -m unittest discover -s tests -q
git diff --check
```

Expected: new focused tests and existing suite pass; any platform skip stated. Failing tests stay with builder first; repeated uncertainty or architecture conflict escalates to root. No test invokes a production cloud command. Green/amber work proceeds through reviews without repeated user prompts; any new red scope/cost decision stops before dependent implementation.
