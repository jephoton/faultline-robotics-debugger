# Artifact Observability Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only local web viewer that makes nominal, perturbed, failed, and infrastructure-error robot episodes visually inspectable and demo-ready.

**Architecture:** A dependency-free Python HTTP service scans existing ignored artifact directories on every API request, normalizes harness aggregate JSON and JSONL traces into a stable viewer contract, and safely serves episode media. A vanilla HTML/CSS/JavaScript forensic workbench consumes that API, compares two videos with linked playback, displays perturbation and provenance data, and renders the episode timeline without modifying experiment artifacts.

**Tech Stack:** Python 3.8+ standard library, dataclasses, `http.server`, JSON/JSONL, HTML5 video, vanilla JavaScript, CSS custom properties, Canvas 2D, and standard-library `unittest`.

**Status:** Proposed for user review. Do not implement until Jethro approves this plan.

---

## Product and architecture decision

The recommended visual direction is an **industrial forensic workbench**: a
dark graphite field, high-contrast evidence surfaces, amber perturbation
annotations, green/red outcome signals, monospaced provenance, and one cyan
linked-playback indicator. It should feel like a robotics investigation tool,
not a generic analytics dashboard.

Three implementation approaches were considered:

1. **Python standard-library service plus vanilla web UI — selected.** It adds
   no runtime dependencies, works offline during a demo, is easy for a smaller
   model to understand, and creates a clean seam between artifact parsing and
   presentation. Hand-written DOM state is acceptable at this deliberately
   small scope.
2. **Streamlit.** It would produce a first screen quickly, but synchronized
   video comparison and deliberate visual composition are awkward, and the
   result would resemble a generic data app.
3. **FastAPI plus React/Vite.** It offers stronger scaling and component
   ergonomics, but introduces two package ecosystems, a build step, and more
   failure surface than this read-only viewer currently warrants.

The selected approach is reversible: `ArtifactCatalog` exposes plain JSON, so
a later React, Streamlit, or hosted frontend can consume the same contract.
This first plan explicitly excludes cloud authentication, remote command
execution, live model control, experiment mutation, database editing, and
video annotation authoring. “Observability” here means automatically noticing
new or growing **local** artifacts; cloud runs become visible after their
artifacts are copied or synchronized locally.

On this workstation, WSL's system Python has neither `pip` nor NumPy. Use the
Codex bundled interpreter for full regression tests, and re-resolve it with
`load_workspace_dependencies` if its cache path changes:

```powershell
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
```

## Acceptance criteria

- Starting one Python command opens a local viewer backed by `artifacts/`.
- Nominal, occluded, task-failure, timeout, and infrastructure-error outcomes
  are visually distinct and never collapsed into one failure category.
- A user can select a primary episode and a comparison episode, play/pause
  them together, change linked playback speed, and re-align their timestamps.
- The screen shows task, outcome, steps, elapsed time, seeds, available model-
  server/harness identity, exact perturbation parameters, and failure detail.
  Missing model/checkpoint revisions are labelled unavailable, not inferred.
- The step timeline is derived from JSONL and marks reward/success/done events.
- New local aggregate files appear within three seconds without restarting the
  server; a malformed or incomplete run appears as a non-fatal warning.
- Artifact files are never written by the viewer, and path traversal cannot
  serve files outside the configured artifact root.
- The UI works at a 1440×900 demo resolution and remains usable at 768 px wide.
- The current nominal baseline and valid occlusion MP4s can be compared in one
  screen without internet access.

## File responsibilities

| Path | Responsibility |
| --- | --- |
| `src/robot_debug/viewer/__init__.py` | Viewer package marker and public version |
| `src/robot_debug/viewer/catalog.py` | Read-only artifact discovery, normalization, trace parsing, and safe media resolution |
| `src/robot_debug/viewer/server.py` | CLI, JSON endpoints, static assets, media streaming, and cache policy |
| `src/robot_debug/viewer/web/index.html` | Accessible semantic application shell |
| `src/robot_debug/viewer/web/styles.css` | Industrial visual system, layout, responsiveness, and reduced-motion behavior |
| `src/robot_debug/viewer/web/app.js` | Polling, selection, comparison, linked playback, timeline rendering, and errors |
| `tests/test_viewer_catalog.py` | Aggregate classification, discovery, trace, malformed-file, and path-containment tests |
| `tests/test_viewer_server.py` | API/static/media integration tests against a temporary server |
| `pyproject.toml` | Package static web assets and expose `robot-debug-viewer` command |
| `README.md` | Local launch and demo instructions |

### Task 1: Normalize experiment artifacts with TDD

**Files:**
- Create: `src/robot_debug/viewer/__init__.py`
- Create: `src/robot_debug/viewer/catalog.py`
- Create: `tests/test_viewer_catalog.py`

- [ ] **Step 1: Write aggregate and trace fixtures inside the test file**

Use `tempfile.TemporaryDirectory` and this helper; do not depend on the real,
ignored artifact directories in automated tests:

```python
def write_episode(
    root: Path,
    run_name: str,
    *,
    success: bool,
    failure_reason: Optional[str] = None,
) -> Path:
    run = root / run_name
    episode_dir = run / "episodes" / "libero-object"
    episode_dir.mkdir(parents=True)
    episode = {
        "episode_id": 0,
        "episode_idx": 0,
        "task_id": 0,
        "name": "pick up the object",
        "suite": "libero_object",
        "metrics": {"success": success},
        "steps": 12,
        "elapsed_sec": 2.5,
    }
    if failure_reason is not None:
        episode["failure_reason"] = failure_reason
        episode["failure_detail"] = "diagnostic detail"
    aggregate = {
        "benchmark": "libero-object",
        "harness_version": "0.5.0",
        "created_at": "2026-09-13T00:00:00+00:00",
        "eval_id": "eval-" + run_name,
        "tasks": [{"task": episode["name"], "episodes": [episode]}],
        "config": {
            "params": {
                "seed": 7,
                "env_seed": 7,
                "agentview_occlusion": {"enabled": True, "width": 0.25},
            }
        },
        "server_info": {"harness_version": "0.5.1", "model_server": "LeRobotModelServer"},
    }
    (run / "libero-object_aggregate.json").write_text(json.dumps(aggregate), encoding="utf-8")
    stem = "task0000_ep0000_success" if success else "task0000_ep0000_error"
    (episode_dir / (stem + ".mp4")).write_bytes(b"video")
    (episode_dir / (stem + ".jsonl")).write_text(
        '{"step": 0, "reward": 0.0, "done": false, "success": false}\n'
        '{"step": 11, "reward": 1.0, "done": true, "success": true}\n',
        encoding="utf-8",
    )
    return run
```

Test these behaviors explicitly:

```python
def test_catalog_classifies_success_and_exposes_perturbation(self):
    write_episode(self.root, "valid", success=True)
    episode = ArtifactCatalog(self.root).list_episodes()[0]
    self.assertEqual(episode.outcome, "success")
    self.assertEqual(episode.perturbation["width"], 0.25)

def test_catalog_separates_infrastructure_error_from_task_failure(self):
    write_episode(self.root, "infra", success=False, failure_reason="exception")
    episode = ArtifactCatalog(self.root).list_episodes()[0]
    self.assertEqual(episode.outcome, "infrastructure_error")

def test_trace_is_parsed_as_json_lines(self):
    write_episode(self.root, "valid", success=True)
    episode = ArtifactCatalog(self.root).list_episodes()[0]
    trace = ArtifactCatalog(self.root).load_trace(episode.episode_id)
    self.assertEqual([point["step"] for point in trace["points"]], [0, 11])
```

Also test task failure (false success without `failure_reason`), timeout,
deterministic newest-first ordering, missing video/trace returning `None`, a
malformed aggregate becoming a warning rather than aborting the scan, and
media traversal such as `../secret.txt` raising `ValueError`.

- [ ] **Step 2: Run the focused tests and verify the missing module failure**

```powershell
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest tests.test_viewer_catalog -v
```

Expected: import fails because `robot_debug.viewer.catalog` does not exist.

- [ ] **Step 3: Implement the viewer data contract and catalog**

Use this public shape in `catalog.py`:

```python
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence


@dataclass(frozen=True)
class EpisodeView:
    episode_id: str
    run_name: str
    benchmark: str
    created_at: str
    instruction: str
    outcome: str
    steps: int
    elapsed_seconds: float
    task_id: int
    episode_index: int
    seed: Optional[int]
    env_seed: Optional[int]
    perturbation: Mapping[str, Any]
    provenance: Mapping[str, Any]
    failure_detail: Optional[str]
    video_path: Optional[str]
    trace_path: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CatalogSnapshot:
    episodes: Sequence[EpisodeView]
    warnings: Sequence[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episodes": [episode.to_dict() for episode in self.episodes],
            "warnings": list(self.warnings),
        }
```

Implement `ArtifactCatalog` with these methods:

```python
class ArtifactCatalog:
    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root.resolve()

    def snapshot(self) -> CatalogSnapshot:
        episodes = []
        warnings = []
        for aggregate_path in sorted(self.artifact_root.rglob("*_aggregate.json")):
            try:
                relative = aggregate_path.resolve().relative_to(self.artifact_root).as_posix()
                aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
                benchmark = aggregate["benchmark"]
                params = aggregate.get("config", {}).get("params", {})
                server = aggregate.get("server_info", {})
                for task in aggregate["tasks"]:
                    for raw in task["episodes"]:
                        task_id = int(raw["task_id"])
                        episode_index = int(raw.get("episode_idx", raw.get("episode_id", 0)))
                        identity = "{}:{}:{}".format(relative, task_id, episode_index)
                        episode_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
                        media_dir = aggregate_path.parent / "episodes" / benchmark
                        stem = "task{:04d}_ep{:04d}_*".format(task_id, episode_index)
                        video = next(iter(sorted(media_dir.glob(stem + ".mp4"))), None)
                        trace = next(iter(sorted(media_dir.glob(stem + ".jsonl"))), None)
                        reason = raw.get("failure_reason")
                        if reason == "exception":
                            outcome = "infrastructure_error"
                        elif raw.get("metrics", {}).get("success") is True:
                            outcome = "success"
                        elif reason == "timeout":
                            outcome = "episode_timeout"
                        else:
                            outcome = "task_failure"
                        episodes.append(EpisodeView(
                            episode_id=episode_id,
                            run_name=aggregate_path.parent.name,
                            benchmark=benchmark,
                            created_at=aggregate.get("created_at", ""),
                            instruction=raw.get("name", task.get("task", "Unknown task")),
                            outcome=outcome,
                            steps=int(raw.get("steps", 0)),
                            elapsed_seconds=float(raw.get("elapsed_sec", 0)),
                            task_id=task_id,
                            episode_index=episode_index,
                            seed=params.get("seed"),
                            env_seed=params.get("env_seed"),
                            perturbation=params.get("agentview_occlusion", {"enabled": False}),
                            provenance={
                                "simulator_harness": aggregate.get("harness_version"),
                                "server_harness": server.get("harness_version"),
                                "model_server": server.get("model_server"),
                                "benchmark_class": aggregate.get("config", {}).get("benchmark"),
                                "eval_id": aggregate.get("eval_id"),
                                "checkpoint_revision": None,
                            },
                            failure_detail=raw.get("failure_detail"),
                            video_path=video.relative_to(self.artifact_root).as_posix() if video else None,
                            trace_path=trace.relative_to(self.artifact_root).as_posix() if trace else None,
                        ))
            except (OSError, ValueError, KeyError, TypeError) as error:
                warnings.append("{}: {}".format(aggregate_path.name, type(error).__name__))
        episodes.sort(key=lambda item: (item.created_at, item.episode_id), reverse=True)
        return CatalogSnapshot(episodes=episodes, warnings=warnings)

    def list_episodes(self) -> Sequence[EpisodeView]:
        return self.snapshot().episodes

    def get_episode(self, episode_id: str) -> EpisodeView:
        for episode in self.list_episodes():
            if episode.episode_id == episode_id:
                return episode
        raise KeyError(episode_id)

    def load_trace(self, episode_id: str) -> Dict[str, Any]:
        episode = self.get_episode(episode_id)
        if episode.trace_path is None:
            return {"points": [], "warnings": ["Trace not recorded"]}
        lines = self._resolve_path(episode.trace_path).read_text(encoding="utf-8").splitlines()
        points = []
        warnings = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                point = json.loads(line)
                if not isinstance(point, dict) or "step" not in point:
                    raise ValueError("trace point requires step")
                points.append(point)
            except ValueError:
                if index == len(lines) - 1:
                    warnings.append("Incomplete final trace line; earlier points retained")
                else:
                    raise ValueError("Invalid trace line {}".format(index + 1))
        return {"points": points, "warnings": warnings}

    def _resolve_path(self, relative_path: str) -> Path:
        candidate = (self.artifact_root / relative_path).resolve()
        try:
            candidate.relative_to(self.artifact_root)
        except ValueError:
            raise ValueError("media path escapes artifact root")
        if not candidate.is_file():
            raise FileNotFoundError(relative_path)
        return candidate

    def resolve_media(self, relative_path: str) -> Path:
        candidate = self._resolve_path(relative_path)
        if candidate.suffix.lower() not in {".mp4", ".webm", ".png", ".jpg", ".jpeg"}:
            raise ValueError("file type is not public viewer media")
        return candidate
```

Generate stable episode IDs with the first 16 hex characters of SHA-256 over
`<aggregate-relative-path>:<task-id>:<episode-index>`. Store media and trace
paths relative to `artifact_root`, using forward slashes. Find files beneath
`episodes/<benchmark>/` by the harness stem
`task{task_id:04d}_ep{episode_index:04d}_*.{mp4,jsonl}`.

Classify outcomes in this order:

```python
if raw_episode.get("failure_reason") == "exception":
    outcome = "infrastructure_error"
elif raw_episode.get("metrics", {}).get("success") is True:
    outcome = "success"
elif raw_episode.get("failure_reason") == "timeout":
    outcome = "episode_timeout"
else:
    outcome = "task_failure"
```

Set `perturbation` to `config.params.agentview_occlusion` when present and to
`{"enabled": False}` otherwise. Provenance must contain simulator and server
harness versions, model-server name, benchmark import path, and aggregate
`eval_id`; do not infer model revisions absent from the aggregate.

- [ ] **Step 4: Run focused and full tests**

```powershell
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest tests.test_viewer_catalog -v
& $workspacePython -B -m unittest discover -s tests -v
```

Expected: catalog tests and all existing tests pass.

- [ ] **Step 5: Commit the catalog boundary**

```bash
git add src/robot_debug/viewer/__init__.py src/robot_debug/viewer/catalog.py tests/test_viewer_catalog.py
git commit -m "feat(viewer): index experiment artifacts"
```

### Task 2: Serve JSON and media safely with TDD

**Files:**
- Create: `src/robot_debug/viewer/server.py`
- Create: `tests/test_viewer_server.py`

- [ ] **Step 1: Write HTTP integration tests**

Start `ThreadingHTTPServer(("127.0.0.1", 0), handler)` in a daemon test thread,
using the Task 1 fixture. Test:

```python
def test_runs_endpoint_returns_normalized_snapshot(self):
    status, headers, body = self.get("/api/runs")
    payload = json.loads(body)
    self.assertEqual(status, 200)
    self.assertEqual(payload["episodes"][0]["outcome"], "success")
    self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")

def test_trace_endpoint_returns_points(self):
    episode_id = self.catalog.list_episodes()[0].episode_id
    status, _, body = self.get("/api/episodes/{}/trace".format(episode_id))
    self.assertEqual(status, 200)
    self.assertEqual(len(json.loads(body)["points"]), 2)

def test_media_endpoint_rejects_traversal(self):
    status, _, _ = self.get("/media/%2e%2e/secret.txt")
    self.assertIn(status, (400, 404))
```

Also cover `/api/health`, unknown episode IDs, byte-range media
requests returning `206`, correct `Content-Range`, and `Cache-Control: no-store`
on JSON so active local runs refresh.

- [ ] **Step 2: Run tests and verify the missing server failure**

```powershell
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest tests.test_viewer_server -v
```

Expected: import fails because `robot_debug.viewer.server` does not exist.

- [ ] **Step 3: Implement the server factory and CLI**

Expose these functions so tests do not spawn subprocesses:

```python
import argparse
import json
import logging
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Type
from urllib.parse import unquote, urlsplit

from robot_debug.viewer.catalog import ArtifactCatalog


def make_handler(catalog: ArtifactCatalog, web_root: Path) -> Type[BaseHTTPRequestHandler]:
    class ViewerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            try:
                if path == "/api/health":
                    self.send_json(200, {"status": "ok", "read_only": True})
                elif path == "/api/runs":
                    self.send_json(200, catalog.snapshot().to_dict())
                elif path.startswith("/api/episodes/") and path.endswith("/trace"):
                    episode_id = path[len("/api/episodes/"):-len("/trace")]
                    self.send_json(200, catalog.load_trace(episode_id))
                elif path.startswith("/media/"):
                    self.send_media(unquote(path[len("/media/"):]))
                elif path in {"/", "/index.html", "/styles.css", "/app.js"}:
                    asset = web_root / ("index.html" if path == "/" else path[1:])
                    if not asset.is_file():
                        raise FileNotFoundError(path)
                    self.stream_file(asset, allow_range=False)
                else:
                    self.send_json(404, {"error": "not found"})
            except (KeyError, FileNotFoundError):
                self.send_json(404, {"error": "evidence not found"})
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
            except OSError:
                self.send_json(503, {"error": "evidence temporarily unavailable"})

        def send_json(self, status: int, payload: Mapping[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_media(self, relative_path: str) -> None:
            self.stream_file(catalog.resolve_media(relative_path), allow_range=True)

        def stream_file(self, path: Path, allow_range: bool) -> None:
            size = path.stat().st_size
            start, end, status = 0, size - 1, 200
            header = self.headers.get("Range") if allow_range else None
            if header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
                if not match or not any(match.groups()):
                    self.send_range_error(size)
                    return
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                else:
                    start = max(0, size - int(last))
                if start >= size or start > end or size == 0:
                    self.send_range_error(size)
                    return
                status = 206
            length = max(0, end - start + 1)
            self.send_response(status)
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix in {".html", ".css", ".js"}:
                content_type += "; charset=utf-8"
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes" if allow_range else "none")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if status == 206:
                self.send_header("Content-Range", "bytes {}-{}/{}".format(start, end, size))
            self.end_headers()
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = length
                while remaining:
                    block = stream.read(min(65536, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)

        def send_range_error(self, size: int) -> None:
            self.send_response(416)
            self.send_header("Content-Range", "bytes */{}".format(size))
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            logging.getLogger("robot_debug.viewer").info(format, *args)

    return ViewerHandler


def create_server(
    artifact_root: Path, host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    catalog = ArtifactCatalog(artifact_root)
    web_root = Path(__file__).with_name("web")
    return ThreadingHTTPServer((host, port), make_handler(catalog, web_root))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only robot episode evidence viewer")
    parser.add_argument("--artifacts", default="artifacts")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser
```

The CLI must parse `--artifacts`, `--host`, and `--port`, default to the safe
loopback host, print exactly one launch URL, and serve until Ctrl+C:

```python
def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    server = create_server(Path(args.artifacts), args.host, args.port)
    print("Robot Debug Viewer: http://{}:{}".format(*server.server_address))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
```

Static routing must allow only `/`, `/index.html`, `/styles.css`, and
`/app.js`. Media responses must support `bytes=start-end`, return `416` for an
invalid range, stream in 64 KiB chunks, and set the MIME type with
`mimetypes.guess_type`.

- [ ] **Step 4: Run focused and full tests**

```powershell
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest tests.test_viewer_server -v
& $workspacePython -B -m unittest discover -s tests -v
```

Expected: HTTP integration and existing tests all pass; no test binds a public
interface.

- [ ] **Step 5: Commit the read-only service**

```bash
git add src/robot_debug/viewer/server.py tests/test_viewer_server.py
git commit -m "feat(viewer): serve diagnostic evidence"
```

### Task 3: Build the forensic workbench shell

**Files:**
- Create: `src/robot_debug/viewer/web/index.html`
- Create: `src/robot_debug/viewer/web/styles.css`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add an asset-presence test before creating assets**

In `tests/test_viewer_server.py`, require `/` and `/styles.css` to
return 200 with their correct content types. Require the HTML to contain the
landmarks `header`, `nav`, `main`, `aside`, and a live status region.

- [ ] **Step 2: Run the asset tests and verify they fail with 404**

```powershell
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest tests.test_viewer_server -v
```

Expected: the new static-asset assertions fail because the web files do not
exist.

- [ ] **Step 3: Create the semantic HTML shell**

Use this hierarchy and preserve these IDs for `app.js`:

```html
<body>
  <a class="skip-link" href="#evidence">Skip to evidence</a>
  <header class="masthead">
    <div><p class="eyebrow">PHYSICAL AI / FAILURE FORENSICS</p><h1>Robot Debug Console</h1></div>
    <div id="connection-status" role="status" aria-live="polite">INDEXING</div>
  </header>
  <div class="workspace">
    <nav class="run-rail" aria-label="Experiment episodes">
      <div class="rail-controls">
        <label for="outcome-filter">Outcome</label>
        <select id="outcome-filter"><option value="all">All evidence</option></select>
      </div>
      <ol id="run-list"></ol>
    </nav>
    <main id="evidence" tabindex="-1">
      <section id="summary-strip" aria-label="Selected episode summary"></section>
      <section class="comparison-deck" aria-label="Synchronized episode comparison">
        <article class="video-channel" data-channel="primary">
          <label for="primary-select">Primary evidence</label><select id="primary-select"></select>
          <video id="primary-video" controls preload="metadata"></video>
          <p id="primary-empty">Select an episode</p>
        </article>
        <article class="video-channel" data-channel="comparison">
          <label for="comparison-select">Comparison evidence</label><select id="comparison-select"></select>
          <video id="comparison-video" controls preload="metadata"></video>
          <p id="comparison-empty">Select a comparison</p>
        </article>
      </section>
      <section class="transport" aria-label="Linked playback controls">
        <button id="play-pair" type="button">Play pair</button>
        <button id="pause-pair" type="button">Pause pair</button>
        <button id="align-pair" type="button">Align starts</button>
        <label><input id="link-playback" type="checkbox" checked>Link playback</label>
        <label for="playback-rate">Playback speed</label>
        <select id="playback-rate"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select>
        <p>Timestamp-aligned comparison; trajectories are not assumed identical.</p>
      </section>
      <section class="timeline-panel">
        <canvas id="timeline" role="img" aria-label="Episode event timeline"></canvas>
        <p id="timeline-detail">TRACE NOT RECORDED</p>
      </section>
    </main>
    <aside id="diagnostics" aria-label="Diagnostic evidence"></aside>
  </div>
  <div id="notices" role="status" aria-live="polite"></div>
  <script src="/app.js" defer></script>
</body>
```

Each video channel must include a labelled `<select>`, `<video controls
preload="metadata">`, and an explicit empty state. The transport must include
linked play/pause, “align starts,” and playback-rate controls; do not use icon-
only buttons.

- [ ] **Step 4: Implement the visual system**

Define tokens rather than scattered literals:

```css
:root {
  --ink: #eef1e8;
  --muted: #8d978f;
  --field: #090c0d;
  --panel: #111719;
  --line: #2b3536;
  --amber: #ffb000;
  --cyan: #48d8e8;
  --success: #70e09a;
  --failure: #ff5d56;
  --radius: 2px;
  --space-1: 0.375rem;
  --space-2: 0.75rem;
  --space-3: 1.25rem;
  --space-4: 2rem;
}
```

Use `ui-monospace, "Cascadia Code", "SFMono-Regular", monospace` for evidence
and `"Arial Narrow", "Roboto Condensed", sans-serif` for display text so the
demo remains offline. The desktop grid is `17rem minmax(0, 1fr) 21rem`; the
center video pair is asymmetric at `1.15fr 0.85fr`. Use thin borders, corner
registration marks, restrained scan-line texture, and no gradients or generic
rounded card grid. At 1050 px, collapse diagnostics below the videos; at
768 px, stack rail, evidence, and diagnostics. Respect
`prefers-reduced-motion: reduce`, preserve visible focus rings, and maintain at
least 4.5:1 contrast for normal text.

- [ ] **Step 5: Package web assets and run tests**

Add to `pyproject.toml`:

```toml
[tool.setuptools.package-data]
"robot_debug.viewer" = ["web/*"]
```

Run:

```powershell
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest tests.test_viewer_server -v
& $workspacePython -B -m unittest discover -s tests -v
```

Expected: static assets are served and all tests pass.

- [ ] **Step 6: Commit the visual shell**

```bash
git add pyproject.toml src/robot_debug/viewer/web/index.html src/robot_debug/viewer/web/styles.css tests/test_viewer_server.py
git commit -m "feat(viewer): add forensic workbench shell"
```

### Task 4: Add comparison, polling, and timeline behavior

**Files:**
- Create: `src/robot_debug/viewer/web/app.js`
- Modify: `src/robot_debug/viewer/web/index.html`
- Modify: `src/robot_debug/viewer/web/styles.css`

- [ ] **Step 1: Define a single explicit client state and safe rendering helpers**

Begin `app.js` with:

```javascript
const state = {
  episodes: [],
  warnings: [],
  primaryId: null,
  comparisonId: null,
  traces: new Map(),
  linked: true,
  refreshMs: 2000,
};

const byId = (id) => document.getElementById(id);
const episodeById = (id) => state.episodes.find((episode) => episode.episode_id === id);
const formatSeconds = (value) => `${Number(value).toFixed(2)} s`;

function setText(element, value) {
  element.textContent = value == null ? "—" : String(value);
}
```

Never insert artifact-derived strings with `innerHTML`. Build nodes with
`document.createElement` and assign `textContent`; only fixed application
templates may use static HTML.

- [ ] **Step 2: Implement polling without destroying user selection**

```javascript
async function refreshCatalog() {
  const response = await fetch("/api/runs", { cache: "no-store" });
  if (!response.ok) throw new Error(`catalog request failed: ${response.status}`);
  const snapshot = await response.json();
  state.episodes = snapshot.episodes;
  state.warnings = snapshot.warnings;
  if (!episodeById(state.primaryId)) state.primaryId = state.episodes[0]?.episode_id ?? null;
  if (!episodeById(state.comparisonId)) {
    const primary = episodeById(state.primaryId);
    const nominal = state.episodes.find((item) =>
      item.episode_id !== state.primaryId && !item.perturbation.enabled &&
      item.instruction === primary?.instruction && item.seed === primary?.seed &&
      item.env_seed === primary?.env_seed);
    state.comparisonId = nominal?.episode_id ??
      state.episodes.find((item) => item.episode_id !== state.primaryId)?.episode_id ?? null;
  }
  render();
}

```

An updated snapshot must preserve current playback and selection when IDs
remain present. Display catalog warnings in `#notices` without hiding valid
runs. Show `NO EVIDENCE` rather than throwing when the catalog is empty.

- [ ] **Step 3: Render run navigation, metadata, and diagnostics**

Outcome badges must use these exact labels:

```javascript
const outcomeLabels = {
  success: "SUCCESS",
  task_failure: "TASK FAILURE",
  episode_timeout: "TIMEOUT",
  infrastructure_error: "INFRA ERROR",
};
```

Populate the run rail with task, run name, outcome, steps, and perturbation
area (`width * height * 100`). The summary strip shows outcome, control steps,
elapsed time, and seed. Diagnostics shows normalized rectangle coordinates,
opacity/color, provenance, video/trace availability, and escaped failure
detail. Treat disabled or absent perturbations as `NOMINAL / NO FAULT`.

Use these concrete rendering functions; style their classes in Task 3 without
changing the data contract:

```javascript
function showNonFatalError(error) {
  setText(byId("notices"), error.message || error);
}

function showFatalError(error) {
  setText(byId("connection-status"), "UNAVAILABLE");
  showNonFatalError(error);
}

function renderChannel(channel, id) {
  const select = byId(`${channel}-select`);
  const signature = state.episodes.map((item) => item.episode_id).join("|");
  if (select.dataset.signature !== signature) {
    select.replaceChildren();
    for (const item of state.episodes) {
      const option = document.createElement("option");
      option.value = item.episode_id;
      option.textContent = `${item.run_name} / ${outcomeLabels[item.outcome]}`;
      select.append(option);
    }
    select.dataset.signature = signature;
  }
  select.value = id || "";
  const episode = episodeById(id);
  const video = byId(`${channel}-video`);
  const empty = byId(`${channel}-empty`);
  if (video.dataset.episodeId !== (id || "")) {
    video.pause();
    if (episode?.video_path) video.src = `/media/${encodeURI(episode.video_path)}`;
    else video.removeAttribute("src");
    video.load();
    video.dataset.episodeId = id || "";
  }
  video.hidden = !episode?.video_path;
  empty.hidden = Boolean(episode?.video_path);
  setText(empty, episode ? "VIDEO NOT RECORDED" : "NO EVIDENCE");
}

function renderDiagnostics(episode) {
  const aside = byId("diagnostics");
  aside.replaceChildren();
  if (!episode) return;
  const title = document.createElement("h2");
  title.textContent = "Diagnostic identity";
  const detail = document.createElement("pre");
  detail.textContent = JSON.stringify({
    task: episode.instruction,
    task_id: episode.task_id,
    initial_state: episode.episode_index,
    seed: episode.seed,
    env_seed: episode.env_seed,
    perturbation: episode.perturbation.enabled ? episode.perturbation : "NOMINAL / NO FAULT",
    provenance: episode.provenance,
  }, null, 2);
  aside.append(title, detail);
  if (episode.failure_detail) {
    const error = document.createElement("pre");
    error.className = "failure-detail";
    error.textContent = episode.failure_detail;
    aside.append(error);
  }
}

function render() {
  setText(byId("connection-status"), `READ ONLY / ${state.episodes.length} EPISODES`);
  const filter = byId("outcome-filter");
  if (filter.options.length === 1) {
    for (const [value, label] of Object.entries(outcomeLabels)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      filter.append(option);
    }
  }
  const list = byId("run-list");
  const visible = state.episodes.filter((item) => filter.value === "all" || item.outcome === filter.value);
  const signature = visible.map((item) => item.episode_id).join("|");
  if (list.dataset.signature !== signature) {
    list.replaceChildren();
    for (const episode of visible) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.episodeId = episode.episode_id;
      button.dataset.outcome = episode.outcome;
      const fault = episode.perturbation;
      const area = fault.enabled ? `${((fault.width || 0) * (fault.height || 0) * 100).toFixed(2)}% MASK` : "NOMINAL";
      button.textContent = `${outcomeLabels[episode.outcome]} · ${episode.steps} STEPS\n${episode.run_name}\n${area}`;
      button.addEventListener("click", () => { state.primaryId = episode.episode_id; render(); });
      item.append(button);
      list.append(item);
    }
    list.dataset.signature = signature;
  }
  for (const button of list.querySelectorAll("button")) {
    button.setAttribute("aria-current", button.dataset.episodeId === state.primaryId ? "true" : "false");
  }
  const primary = episodeById(state.primaryId);
  setText(byId("summary-strip"), primary ?
    `${primary.instruction} / ${outcomeLabels[primary.outcome]} / ${primary.steps} STEPS / ${formatSeconds(primary.elapsed_seconds)} / SEED ${primary.seed}` :
    "NO EVIDENCE — copy experiment artifacts into the configured directory");
  renderChannel("primary", state.primaryId);
  renderChannel("comparison", state.comparisonId);
  renderDiagnostics(primary);
  setText(byId("notices"), state.warnings.join(" · "));
  if (primary) refreshTrace(primary.episode_id).catch(showNonFatalError);
  else drawTimeline([]);
}

byId("outcome-filter").addEventListener("change", render);
for (const channel of ["primary", "comparison"]) {
  byId(`${channel}-select`).addEventListener("change", (event) => {
    state[channel === "primary" ? "primaryId" : "comparisonId"] = event.target.value;
    render();
  });
}
```

- [ ] **Step 4: Implement synchronized evidence playback**

Wire both channel selectors to `primaryId` and `comparisonId`. Set video URLs
to `/media/${encodeURI(episode.video_path)}`. Implement a re-entrancy guard:

```javascript
let synchronizing = false;

async function playLinked(source, peer) {
  if (!state.linked || synchronizing || !peer.src) return;
  synchronizing = true;
  try {
    if (Math.abs(peer.currentTime - source.currentTime) > 0.12) {
      peer.currentTime = Math.min(source.currentTime, peer.duration || source.currentTime);
    }
    await peer.play();
  } finally {
    synchronizing = false;
  }
}
```

Mirror play, pause, seeking, and playback-rate changes when linked. “Align
starts” sets both current times to zero. The primary video is the clock; a
250 ms interval corrects comparison drift only when it exceeds 120 ms. Catch
rejected `play()` promises and show a non-fatal notice because browsers may
block autoplay.

Complete the transport wiring with:

```javascript
const primaryVideo = byId("primary-video");
const comparisonVideo = byId("comparison-video");
const videos = [primaryVideo, comparisonVideo];

for (const [source, peer] of [[primaryVideo, comparisonVideo], [comparisonVideo, primaryVideo]]) {
  source.addEventListener("play", () => playLinked(source, peer).catch(showNonFatalError));
  source.addEventListener("pause", () => {
    if (state.linked && !synchronizing) peer.pause();
  });
  source.addEventListener("seeking", () => {
    if (state.linked && !synchronizing && peer.src && Math.abs(peer.currentTime - source.currentTime) > 0.12) {
      peer.currentTime = Math.min(source.currentTime, peer.duration || source.currentTime);
    }
  });
}
byId("play-pair").addEventListener("click", () => {
  Promise.all(videos.filter((video) => video.src).map((video) => video.play())).catch(showNonFatalError);
});
byId("pause-pair").addEventListener("click", () => videos.forEach((video) => video.pause()));
byId("align-pair").addEventListener("click", () => videos.forEach((video) => { video.currentTime = 0; }));
byId("link-playback").addEventListener("change", (event) => { state.linked = event.target.checked; });
byId("playback-rate").addEventListener("change", (event) => {
  videos.forEach((video) => { video.playbackRate = Number(event.target.value); });
});
window.setInterval(() => {
  if (state.linked && !primaryVideo.paused && comparisonVideo.src &&
      Math.abs(primaryVideo.currentTime - comparisonVideo.currentTime) > 0.12) {
    comparisonVideo.currentTime = Math.min(primaryVideo.currentTime, comparisonVideo.duration || primaryVideo.currentTime);
  }
}, 250);
```

- [ ] **Step 5: Fetch and draw the selected JSONL timeline**

Fetch `/api/episodes/<id>/trace` lazily and cache by episode ID. Use Canvas 2D
with device-pixel-ratio scaling. Draw one horizontal baseline, regular step
ticks, amber reward impulses, a green success marker, and red terminal/failure
marker. On pointer movement, update a text companion beneath the canvas with
nearest step, reward, done, and success values; the canvas must not be the only
way to access event data.

Implement the trace and canvas functions:

```javascript
async function refreshTrace(id) {
  const response = await fetch(`/api/episodes/${id}/trace`, { cache: "no-store" });
  if (!response.ok) throw new Error(`trace request failed: ${response.status}`);
  const trace = await response.json();
  state.traces.set(id, trace);
  if (state.primaryId === id) {
    drawTimeline(trace.points);
    if (trace.warnings.length) showNonFatalError(new Error(trace.warnings.join(" · ")));
  }
}

function drawTimeline(points) {
  const canvas = byId("timeline");
  const width = Math.max(320, canvas.clientWidth);
  const height = 96;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);
  context.strokeStyle = "#2b3536";
  context.beginPath();
  context.moveTo(12, 60);
  context.lineTo(width - 12, 60);
  context.stroke();
  if (!points.length) {
    setText(byId("timeline-detail"), "TRACE NOT RECORDED");
    return;
  }
  const maximum = Math.max(1, ...points.map((point) => Number(point.step)));
  for (const point of points) {
    const x = 12 + Number(point.step) / maximum * (width - 24);
    context.fillStyle = point.success ? "#70e09a" : point.done ? "#ff5d56" : "#ffb000";
    if (point.reward || point.done || point.success) context.fillRect(x - 2, 20, 4, 40);
    else if (Number(point.step) % 10 === 0) context.fillRect(x, 56, 1, 8);
  }
  const describe = (point) => `STEP ${point.step} / REWARD ${point.reward ?? "—"} / DONE ${Boolean(point.done)} / SUCCESS ${Boolean(point.success)}`;
  setText(byId("timeline-detail"), describe(points[points.length - 1]));
  canvas.onpointermove = (event) => {
    const target = (event.offsetX - 12) / (width - 24) * maximum;
    const nearest = points.reduce((best, point) =>
      Math.abs(Number(point.step) - target) < Math.abs(Number(best.step) - target) ? point : best);
    setText(byId("timeline-detail"), describe(nearest));
  };
}

window.addEventListener("resize", () => drawTimeline(state.traces.get(state.primaryId)?.points || []));
refreshCatalog().catch(showFatalError);
window.setInterval(() => refreshCatalog().catch(showNonFatalError), state.refreshMs);
```

When no trace exists, render `TRACE NOT RECORDED`. When a trace is currently
being appended and contains invalid final JSON, retain earlier valid points
and surface one warning rather than blanking the viewer.

- [ ] **Step 6: Add the JavaScript static-asset assertion and perform checks**

Extend the HTTP asset test to require `/app.js` returning 200 with a JavaScript
content type now that the file exists.

```powershell
node --check src/robot_debug/viewer/web/app.js
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest discover -s tests -v
git diff --check
```

Expected: JavaScript syntax exits zero, all Python tests pass, and no whitespace
errors are reported. If Node is unavailable, record that limitation and use a
browser load plus console inspection during Task 5; do not claim `node --check`
ran.

- [ ] **Step 7: Commit viewer behavior**

```bash
git add src/robot_debug/viewer/web/app.js src/robot_debug/viewer/web/index.html src/robot_debug/viewer/web/styles.css
git commit -m "feat(viewer): compare robot episodes"
```

### Task 5: Package, document, and demo-test the viewer

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-09-13-artifact-observability-viewer.md`

- [ ] **Step 1: Add the console entry point**

Add:

```toml
[project.scripts]
robot-debug-viewer = "robot_debug.viewer.server:main"
```

The module invocation remains the dependency-free fallback:

```powershell
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -m robot_debug.viewer.server --artifacts artifacts --port 8765
```

- [ ] **Step 2: Document the operator and demo flow**

Add a `Viewer` section to `README.md` containing:

1. the PowerShell launch command above;
2. `http://127.0.0.1:8765` as the only default URL;
3. instructions to select the nominal baseline as primary and the global
   occlusion run as comparison;
4. an explanation that the viewer is read-only and classifies infrastructure
   errors separately;
5. a note that cloud evidence must first be copied/synchronized into
   `artifacts/`;
6. a warning not to bind `--host 0.0.0.0` on an untrusted network.

- [ ] **Step 3: Run the complete automated verification**

```powershell
$workspacePython = 'python'
$env:PYTHONPATH = (Join-Path (Resolve-Path '.').Path 'src')
& $workspacePython -B -m unittest discover -s tests -v
& $workspacePython -m robot_debug.viewer.server --help
git diff --check
```

Expected: all tests pass; help lists `--artifacts`, `--host`, and `--port`;
diff check exits zero.

- [ ] **Step 4: Run the real-artifact browser acceptance check**

Launch against `artifacts/` and verify at 1440×900 and 768 px widths:

- baseline and occlusion videos load;
- linked play, pause, seek, align, and rate controls work;
- the centered occlusion is visible in the perturbed video;
- metadata shows 137 steps for the first nominal baseline and 129 steps for
  the valid occlusion run;
- the infrastructure-error attempt is labelled `INFRA ERROR`, shows zero
  steps, and is not styled as a robot task failure;
- switching runs does not create browser-console errors;
- keyboard focus order follows rail → primary → comparison → transport →
  diagnostics, and every control has a visible focus ring;
- reduced-motion emulation disables non-essential transitions;
- no request leaves `127.0.0.1`.

Capture one screenshot for demo planning under ignored
`artifacts/viewer-demo/`; do not commit generated media.

- [ ] **Step 5: Record evidence and limitations in this plan**

Under a new `Implementation evidence` heading, record the test count, browsers
checked, screenshot path, and any unmet acceptance criterion. Do not mark an
unverified item complete.

- [ ] **Step 6: Commit documentation and packaging**

```bash
git add pyproject.toml README.md docs/superpowers/plans/2026-09-13-artifact-observability-viewer.md
git commit -m "docs(viewer): add local demo workflow"
```

## Handoff rules for the implementation model

- Work only on this viewer plan; do not start the cloud experiment sweep.
- Do not start, stop, edit, or authenticate to Nebius resources.
- Do not edit or delete anything under `artifacts/`; tests must use temporary
  directories and the viewer must stay read-only.
- Follow the red/green TDD steps and make the listed Conventional Commits.
- Stop after Task 2 for a code review checkpoint because path containment and
  HTTP range handling are the highest-risk parts.
- Stop again after Task 4 for Jethro to review the visual direction before the
  final demo pass.
- Preserve unrelated changes and do not push commits without explicit review.
