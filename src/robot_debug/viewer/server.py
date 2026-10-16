"""Read-only HTTP server for locally collected Faultline evidence."""

from __future__ import annotations

import argparse
import json
import logging
import math
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Optional, Sequence, Type
from urllib.parse import unquote, urlsplit

from robot_debug.viewer.api import Api, FileResponse, TextResponse
from robot_debug.viewer.catalog import ArtifactCatalog
from robot_debug.viewer.environment import Environment
from robot_debug.viewer.evidence import CachedArtifactCatalog, evidence_payload
from robot_debug.viewer.launcher import Launcher
from robot_debug.viewer.library import Library
from robot_debug.viewer.routes import register_routes
from robot_debug.viewer.security import MAX_BODY_BYTES, ControlGuard
from robot_debug.viewer.specs import SpecService
from robot_debug.case_io import SanitizedCaseValidationError
from robot_debug.case_store import inspect_case, list_cases
from robot_debug.explanation_store import read_case_reports
from robot_debug.case_register import list_diagnoses, read_diagnosis


CASE_ID = re.compile(r"[0-9a-f]{64}\Z")
DISCARD_LIMIT_BYTES = 1024 * 1024
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"     # /assets/* files carry a content hash in their name
APP_TYPES = {".woff2": "font/woff2", ".svg": "image/svg+xml", ".map": "application/json", ".ico": "image/x-icon",
             ".webmanifest": "application/manifest+json", ".txt": "text/plain; charset=utf-8"}
NOT_APP_ROUTES = ("/api/", "/media/", "/data/", "/assets/")

ResearchReader = Callable[[Path, str], Mapping[str, Any]]


def default_research_reader(workspace: Path, case_id: str) -> Mapping[str, Any]:
    """Read stored research records; imported lazily so the viewer starts without it."""
    try:
        from robot_debug.research_store import read_case_research
    except ImportError as error:
        raise OSError("research records are unavailable") from error
    return read_case_research(workspace, case_id)


def public_value(value: Any) -> Any:
    if isinstance(value, str) and (re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("/", "\\\\"))):
        return "[local path omitted]"
    return value


def finite_number(value: Any, minimum: float = 0) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value)) and value >= minimum
    except (OverflowError, ValueError, TypeError):
        return False


def public_measurements(measurements: dict) -> dict:
    result = {}
    for key in ("source_reported_elapsed_seconds", "physical_episode_count", "valid_episode_count", "cost"):
        value = measurements.get(key)
        result[key] = value if (value is None or finite_number(value)) else None
    return result


def valid_public_episode(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if not isinstance(item.get("episode_id"), str) or re.fullmatch(r"[0-9a-f]{16}", item["episode_id"]) is None:
        return False
    if any(not isinstance(item.get(key), str) or public_value(item[key]) != item[key]
           for key in ("stage", "role", "raw_outcome", "gate_outcome")):
        return False
    if any(type(item.get(key)) is not int or item[key] < 0 for key in ("task_id", "reset_index")):
        return False
    return item.get("instruction") is None or (isinstance(item["instruction"], str) and public_value(item["instruction"]) == item["instruction"])


def public_case(case: dict) -> dict:
    """Project revalidated case evidence without local source references."""
    if case.get("status") == "unavailable":
        return {"case_id": case.get("case_id"), "status": "unavailable", "reasons": case.get("reasons", [])}
    evidence = case["evidence"]
    if (not isinstance(evidence, dict) or
        not isinstance(evidence.get("episodes"), list) or
        any(not valid_public_episode(item) for item in evidence["episodes"]) or
        not isinstance(evidence.get("lineage"), list) or
        not isinstance(evidence.get("media_counts"), dict) or
        not isinstance(evidence.get("media_availability"), dict) or
        not isinstance(case.get("measurements"), dict)):
        return {"case_id": case["case_id"], "status": "unavailable", "reasons": ["case evidence metadata is invalid"]}
    policy = {key: public_value(case["policy"][key]) for key in ("model_id", "checkpoint_revision")}
    runtime = {key: public_value(case["runtime"][key]) for key in ("project_revision", "upstream_harness_revision", "simulator_image_digest")}
    redacted = [f"{group}.{key}" for group, projected, original in
                (("policy", policy, case["policy"]), ("runtime", runtime, case["runtime"]))
                for key in projected if projected[key] != original[key]]
    capabilities = dict(case["capabilities"])
    if redacted:
        replay = capabilities["replay_recipe"]
        capabilities["replay_recipe"] = {"status": "incomplete", "missing": sorted(set(replay["missing"] + redacted))}
    media_status = evidence["media_availability"].get("status")
    return {
        "schema_version": case["schema_version"], "case_id": case["case_id"],
        "task": case["task"],
        "policy": policy,
        "runtime": runtime,
        "perturbation": case["perturbation"], "protocol": case["protocol"],
        "evidence": {
            "episodes": [{key: public_value(episode.get(key)) for key in ("episode_id", "stage", "role", "task_id", "reset_index", "raw_outcome", "gate_outcome", "instruction")}
                         for episode in evidence.get("episodes", [])],
            "lineage": [{"rectangle": {key: item["rectangle"][key] for key in ("x", "y", "width", "height")},
                         "edge": item["edge"], "delta": item["delta"]}
                        for item in evidence.get("lineage", []) if isinstance(item, dict) and
                        isinstance(item.get("rectangle"), dict) and isinstance(item.get("edge"), str) and item["edge"] in {"left", "right", "top", "bottom"} and
                        all(finite_number(item["rectangle"].get(key)) for key in ("x", "y", "width", "height")) and
                        finite_number(item.get("delta")) and item["delta"] > 0],
            "media_counts": {key: value if type(value) is int and value >= 0 else 0
                             for key, value in ((key, evidence["media_counts"].get(key)) for key in ("videos", "traces"))},
            "media_availability": {"status": media_status
                                   if isinstance(media_status, str) and media_status in {"available", "unavailable", "changed"} else "unknown"},
        },
        "measurements": public_measurements(case["measurements"]), "capabilities": capabilities,
    }


def public_recipe(case: dict) -> dict:
    projected = public_case(case)
    if projected.get("status") == "unavailable":
        return {"recipe": None, "missing": ["case evidence metadata is unavailable"]}
    missing = projected["capabilities"]["replay_recipe"]["missing"]
    if missing:
        return {"recipe": None, "missing": missing}
    return {"recipe": {key: projected[key] for key in ("schema_version", "case_id", "task", "policy", "runtime", "perturbation", "protocol")}, "missing": []}


def public_diagnosis(entry: Mapping[str, Any], diagnoses_root: Path, artifact_root: Path) -> dict:
    """An index entry for the browser: summary fields, file names and a ``/media`` URL per video."""
    result = {key: value for key, value in entry.items() if key not in {"files"}}
    videos = {}
    for role, video in (entry.get("videos") or {}).items():
        url = None
        if isinstance(video, Mapping) and isinstance(video.get("file"), str):
            try:
                relative = (diagnoses_root / entry["case_id"] / video["file"]).resolve().relative_to(
                    artifact_root.resolve())
                url = "/media/" + relative.as_posix()
            except (ValueError, OSError):
                url = None
            videos[role] = dict(video, url=url)
        else:
            videos[role] = None
    result["videos"] = videos
    return result


def make_handler(
    catalog: ArtifactCatalog, case_workspace: Optional[Path] = None,
    research_reader: Optional[ResearchReader] = None, diagnoses_root: Optional[Path] = None,
    *, api: Optional[Api] = None, app_root: Optional[Path] = None,
) -> Type[BaseHTTPRequestHandler]:
    """Create a handler closed over a catalog and the built front end.

    ``research_reader`` reads stored (never fetched) research records and
    defaults to ``robot_debug.research_store.read_case_research``.
    ``diagnoses_root`` is the folder of registered diagnoses (default
    ``<artifacts>/diagnoses``, written by ``robot_debug.case_register``).
    ``api`` holds the control-panel routes (API version 1, ``robot_debug.viewer.api``); without it the handler
    is the original read-only viewer. ``app_root`` is the built front end (``viewer/app``): when it holds an
    ``index.html`` it is served for ``/`` and every app route; without a bundle ``/`` answers 503.
    """
    read_research = research_reader or default_research_reader
    diagnoses = diagnoses_root or catalog.artifact_root / "diagnoses"

    class ViewerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            path = parts.path
            try:
                refused = None if api is None else api.read_refusal(path, self.headers)
                routed = refused if refused is not None else (
                    None if api is None else api.handle_get(path, parts.query, self.headers))
                if routed is not None:
                    self.send_response_object(routed)
                elif path == "/api/health":
                    self.send_json(200, {"status": "ok", "read_only": True})
                elif path == "/api/runs":
                    self.send_json(200, catalog.snapshot().to_dict())
                elif path == "/api/evidence":
                    self.send_json(200, evidence_payload(catalog.snapshot()))
                elif path == "/api/reduction":
                    self.send_json(200, catalog.load_reduction())
                elif path == "/api/cases":
                    self.send_json(200, {"cases": [public_case(case) for case in list_cases(case_workspace or catalog.artifact_root / "cases")], "warnings": []})
                elif path.startswith("/api/cases/"):
                    parts = path.split("/")
                    if (len(parts) not in (4, 5)
                            or (len(parts) == 5 and parts[4] not in {"recipe", "explanations", "research"})
                            or CASE_ID.fullmatch(parts[3]) is None):
                        self.send_json(400, {"error": "case ID must be a full lowercase SHA-256 digest"})
                    elif len(parts) == 5 and parts[4] == "explanations":
                        self.send_json(200, read_case_reports(
                            case_workspace or catalog.artifact_root / "cases", parts[3]))
                    elif len(parts) == 5 and parts[4] == "research":
                        self.send_json(200, read_research(
                            case_workspace or catalog.artifact_root / "cases", parts[3]))
                    else:
                        case = inspect_case(case_workspace or catalog.artifact_root / "cases", parts[3])
                        self.send_json(200, public_recipe(case) if len(parts) == 5 else {"case": public_case(case)})
                elif path == "/api/diagnoses":
                    self.send_json(200, {"diagnoses": [public_diagnosis(entry, diagnoses, catalog.artifact_root)
                                                       for entry in list_diagnoses(diagnoses)], "warnings": []})
                elif path.startswith("/api/diagnoses/"):
                    entry = read_diagnosis(diagnoses, path[len("/api/diagnoses/"):])
                    self.send_json(200, {"diagnosis": public_diagnosis(entry, diagnoses, catalog.artifact_root)})
                elif path.startswith("/api/episodes/") and path.endswith("/trace"):
                    episode_id = path[len("/api/episodes/") : -len("/trace")]
                    self.send_json(200, catalog.load_trace(episode_id))
                elif path.startswith("/media/"):
                    self.send_media(unquote(path[len("/media/") :]))
                elif self.serve_app(path):
                    pass
                elif path in {"/", "/index.html"}:
                    self.send_json(503, {"error": "the front end is not built; run: npm --prefix web run build"})
                else:
                    self.send_json(404, {"error": "not found"})
            except (KeyError, FileNotFoundError, SanitizedCaseValidationError):
                self.send_json(404, {"error": "evidence not found"})
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
            except OSError:
                self.send_json(503, {"error": "evidence temporarily unavailable"})

        def do_POST(self) -> None:
            parts = urlsplit(self.path)
            if api is None:                           # the original read-only viewer has no write method at all
                self.send_error(501, "Unsupported method ('POST')")
                return
            declared = self.headers.get("Content-Length", "")
            declared = int(declared) if declared.isdigit() else 0
            consumed = [0]

            def read(count: int) -> bytes:
                data = self.rfile.read(count)
                consumed[0] += len(data)
                return data

            status, payload = api.handle_post(parts.path, parts.query, self.headers, read)
            self.close_connection = True              # never reuse a connection whose body may be half read
            if declared <= MAX_BODY_BYTES:
                self.discard(declared - consumed[0])  # a refusal does not read the body; closing on unread data resets
            self.send_json(status, payload)
            if declared > MAX_BODY_BYTES:
                self.discard(DISCARD_LIMIT_BYTES)

        def discard(self, count: int) -> None:
            """Read and drop up to ``count`` bytes the client is still sending, so closing does not reset it."""

            try:
                self.connection.settimeout(1.0)
                while count > 0:
                    block = self.rfile.read(min(65536, count))
                    if not block:
                        break
                    count -= len(block)
            except OSError:
                pass
            finally:
                try:
                    self.connection.settimeout(None)
                except OSError:
                    pass

        def serve_app(self, path: str) -> bool:
            """The built front end: a file of the bundle, else ``index.html`` for an app route (a path with no
            file extension that is not an API, media, data or asset path). ``False`` when there is no bundle or
            nothing matches, so the caller carries on."""

            if app_root is None or not (app_root / "index.html").is_file():
                return False
            if "\\" in path or ".." in path.split("/") or "\x00" in path:
                return False
            relative = unquote(path).lstrip("/")
            candidate = app_root / (relative or "index.html")
            try:
                inside = candidate.resolve().relative_to(app_root.resolve()) is not None
            except (ValueError, OSError):
                inside = False
            if inside and candidate.is_file():
                immutable = path.startswith("/assets/")
                self.stream_file(candidate, allow_range=False, content_type=APP_TYPES.get(candidate.suffix.lower()),
                                 cache_control=IMMUTABLE_CACHE if immutable else None)
                return True
            last = relative.rsplit("/", 1)[-1]
            if not path.startswith(NOT_APP_ROUTES) and "." not in last:
                self.stream_file(app_root / "index.html", allow_range=False)
                return True
            return False

        def send_response_object(self, response: Any) -> None:
            if isinstance(response, FileResponse):
                self.stream_file(response.path, allow_range=False, content_type=response.content_type)
            elif isinstance(response, TextResponse):
                body = response.text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", response.content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_security_headers()
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_json(*response)

        def send_security_headers(self, cache_control: str = "no-store") -> None:
            self.send_header("Cache-Control", cache_control)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")

        def send_json(self, status: int, payload: Mapping[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_security_headers()
            self.end_headers()
            self.wfile.write(body)

        def send_media(self, relative_path: str) -> None:
            self.stream_file(catalog.resolve_media(relative_path), allow_range=True)

        def stream_file(self, path: Path, allow_range: bool, content_type: Optional[str] = None,
                        cache_control: Optional[str] = None) -> None:
            size = path.stat().st_size
            start, end, status = 0, size - 1, 200
            range_header = self.headers.get("Range") if allow_range else None
            if range_header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
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
            suffix = path.suffix.lower()
            content_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if suffix == ".js":
                content_type = "text/javascript"
            if suffix in {".html", ".css", ".js"}:
                content_type += "; charset=utf-8"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes" if allow_range else "none")
            self.send_security_headers(cache_control or "no-store")
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

        def log_message(self, message: str, *args: Any) -> None:
            logging.getLogger("robot_debug.viewer").info(message, *args)

    return ViewerHandler


def create_server(
    artifact_root: Path, host: str = "127.0.0.1", port: int = 8765,
    case_workspace: Optional[Path] = None, research_reader: Optional[ResearchReader] = None,
    diagnoses_root: Optional[Path] = None, *, runs_root: Optional[Path] = None,
    app_root: Optional[Path] = None, specs: Optional[SpecService] = None, launcher: Optional[Launcher] = None,
    environment: Optional[Environment] = None, api_setup: Optional[Callable[[Api], None]] = None,
) -> ThreadingHTTPServer:
    """The viewer on ``host:port`` (``port`` 0 picks a free one).

    ``server.api`` is the control-panel API (the routes of ``robot_debug.viewer.routes``; controls are enabled
    only when ``host`` is a loopback address). ``specs``, ``launcher`` and ``environment`` default to the real
    services for ``artifact_root`` and ``runs_root`` (default ``<artifacts>/runs``); ``api_setup`` may add
    routes before the first request.
    """

    artifact_root = Path(artifact_root)
    runs_root = Path(runs_root) if runs_root else artifact_root / "runs"
    catalog = CachedArtifactCatalog(artifact_root)      # the scan is slow on a full artifacts folder
    app_root = Path(app_root) if app_root else Path(__file__).with_name("app")
    guard = ControlGuard(host, port)
    api = Api(guard)
    library = Library(artifact_root, runs_root=runs_root, diagnoses_root=diagnoses_root, case_workspace=case_workspace)
    specs = specs or SpecService(artifact_root)
    launcher = launcher or Launcher(artifact_root, runs_root, specs)
    environment = environment or Environment(specs, env_file=launcher.env_path())
    register_routes(api, library=library, runs_root=runs_root, specs=specs, launcher=launcher,
                    environment=environment)
    if api_setup is not None:
        api_setup(api)
    server = ThreadingHTTPServer(
        (host, port), make_handler(catalog, case_workspace, research_reader, diagnoses_root, api=api,
                                   app_root=app_root))
    guard.port = server.server_address[1]               # the real port, when 0 was asked for
    server.api = api
    server.catalog = catalog
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="faultline ui", description="The Faultline control panel")
    parser.add_argument("--artifacts", default="artifacts", help="the artifacts folder (default: artifacts)")
    parser.add_argument("--runs-root", help="the run folders (default: <artifacts>/runs)")
    parser.add_argument("--cases", help="the occlusion case workspace (default: <artifacts>/cases)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address; controls need a loopback address")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    return parser


def main(argv: Optional[Sequence[str]] = None, out: Optional[Callable[[str], None]] = None) -> int:
    out = out or print
    args = build_parser().parse_args(argv)
    server = create_server(Path(args.artifacts), args.host, args.port, Path(args.cases) if args.cases else None,
                           runs_root=Path(args.runs_root) if args.runs_root else None)
    host, port = server.server_address[:2]
    url = "http://{}:{}".format(host if host not in ("0.0.0.0", "::") else "127.0.0.1", port)
    out("Faultline Viewer: {}".format(url))
    guard = getattr(getattr(server, "api", None), "guard", None)
    if guard is not None and not guard.controls:
        out("Controls are off: the viewer is bound to {}, not to localhost. Cases are shown read-only.".format(host))
    catalog = getattr(server, "catalog", None)
    if catalog is not None:                                 # warm the evidence scan so All evidence opens quickly
        threading.Thread(target=catalog.snapshot, daemon=True).start()
    try:
        if args.open:
            webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
