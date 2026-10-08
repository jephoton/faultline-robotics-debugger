# Serverless Evidence Foundation Implementation Plan

> **For agentic workers:** Use subagent-driven-development for this bounded
> Task 2 increment. Root integrates after independent spec and quality reviews.

**Goal:** Establish validated runtime configuration and safe closed-file export
before assembling the model/evaluator lifecycle in the existing migration plan.

**Architecture:** Pure configuration validation plus local filesystem export.
The caller must explicitly confirm cleanup before export; this is not itself
proof that a simulator was closed. A manifest is written last and labels either
complete or partial evidence. No subprocess, model download or cloud call.

**Tech Stack:** Python standard library, unittest, SHA256, JSON, local fixtures.

## Ownership, scope and concurrency

This implements green/amber details of the already approved October 6 migration,
not a new deployment choice. Root owns this plan, integration and provider state.
One smaller builder (`gpt-5.6-sol`, medium) owns only new
`src/robot_debug/job_runtime.py` and `tests/test_job_runtime.py` in a clean
attached worktree. Existing Task 1 and Task 3 reviewers remain read-only.
Map: configuration/export builder || image inspection -> spec -> quality ->
root integration. No existing driver, artifact or interpretation is modified.
No paid work, package publication, model prompt change or external replay.

## Public contracts

```python
validate_workload_config(config) -> dict
# Exactly these fields, ordinary JSON types only; return a fresh normalized dict:
{"schema_version": 1, "mode": "pilot", "run_id": "pilot-example",
 "deadline_seconds": 1800}
# Modes: pilot/search/grid/reduce. Deadline finite, >0 and <=3000, not bool.
# Run ID: 1..63 lower-case ASCII alphanumeric, interior hyphens only.

export_closed_evidence(source_root, destination_root, *, status,
                       cleanup_confirmed, secret_values=()) -> dict
# status exactly complete or partial; cleanup_confirmed exactly True.
# Destination must be fresh, source must be an existing ordinary directory.
# Return the same JSON-compatible manifest written to destination/manifest.json:
{"schema_version": 1, "status": "complete", "files": [
    {"path": "episode.mp4", "size_bytes": 3,
     "sha256": "...actual SHA256 of file..."}]}
```

Runtime roots/environment/model pins will be provided by the subsequent
orchestration increment, not arbitrary user-supplied command/environment fields.
These four configuration fields contain no credentials. Reject missing/extra
fields and malformed values with generic diagnostics, not raw input echo.

## Task 1 — configuration and export (green)

- [ ] Write failing tests for all four modes; missing/extra keys, string
  subclasses, bool schema/deadline, NaN/infinity, unsafe run IDs and >3000 bounds.
- [ ] Write export fixtures before implementation. A minimal successful fixture:

```python
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    source = root / "source"
    source.mkdir()
    (source / "episode.mp4").write_bytes(b"mp4")
    report = export_closed_evidence(source, root / "output",
                                   status="complete", cleanup_confirmed=True)
    assert report["files"][0]["sha256"] == hashlib.sha256(b"mp4").hexdigest()
    assert json.loads((root / "output" / "manifest.json").read_text()) == report
```

- [ ] Reject false/unknown cleanup, invalid status, symlinked source/destination
  ancestors or children, source/destination overlap, existing destination,
  special files, control characters/unsafe relative paths, and existing source
  completion-manifest names. Reject credential files (`.env*`, key/pem/token
  names), unsupported extensions and SQLite `-wal`/`-shm` companions.
  Allow ordinary `.json`, `.jsonl`, `.mp4`, `.sqlite`, `.yaml`, `.yml`, `.txt`
  and `.log` evidence files, not weights, executable code or archives.
- [ ] Enforce <=1 GiB total source bytes before creating the destination.
  Scan for explicitly supplied nonempty ordinary-string secret values in file
  bytes; reject matches without echoing the value. This detects supplied secrets,
  not all unknown or transformed credentials. Do not read environment secrets.
- [ ] Copy into exclusive unique per-file staging paths and replace only
  those newly created destination paths. Hash copied bytes, compare with source,
  and confirm source size/hash stayed stable. Sort manifest paths deterministically.
  Publish `manifest.json` exclusively only after every file is verified.
- [ ] Inject a copy failure via a patched private copy seam: confirm the
  exception propagates and no final manifest exists. Keep explicitly partial
  copied files for recovery; never remove or overwrite prior evidence.
- [ ] Test partial-status manifest, byte tampering, secret matching, source
  mutation during copy, existing destinations, SQLite companions and POSIX
  symlink cases. No subprocess or network call in these tests.
- [ ] Run red then green with `PYTHONPATH=src` and
  `C:/Windows/py.exe -3.11 -B -m unittest tests.test_job_runtime -v`.
  Run the same suite under WSL for symlink fixtures. Run `git diff --check`.
- [ ] Commit only owned files as
  `feat(jobs): validate workloads and export closed evidence`.

## Review and completion

- [ ] Independent spec reviewer verifies exact contracts/guard ordering and
  failure-without-manifest behavior; no orchestration-ready claim.
- [ ] Independent quality/security reviewer checks containment, TOCTOU checks,
  bounded memory use, secret handling, failure recovery and actual fixture tests.
- [ ] Root reruns focused and complete tests, cherry-picks reviewed commits,
  updates migration progress and handoff, then pushes only verified integration.

This foundation does not complete Task 2 or M5. Model-group startup/handshake,
whole-workload deadline/TERM handling, sequential driver/pilot dispatch,
actual version provenance and the CLI remain in the October 6 plan. Image and
live Job acceptance retain their gates. Local manifests are not robot replay
validation and do not claim globally minimal failures.
