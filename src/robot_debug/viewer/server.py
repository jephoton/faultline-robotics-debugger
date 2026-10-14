"""Read-only HTTP server for locally collected Faultline evidence."""

from __future__ import annotations

import argparse
import json
import logging
import math
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Optional, Sequence, Type
from urllib.parse import unquote, urlsplit

from robot_debug.viewer.catalog import ArtifactCatalog
from robot_debug.case_io import SanitizedCaseValidationError
from robot_debug.case_store import inspect_case, list_cases
from robot_debug.explanation_store import read_case_reports
from robot_debug.case_register import list_diagnoses, read_diagnosis


CASE_ID = re.compile(r"[0-9a-f]{64}\Z")

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
    catalog: ArtifactCatalog, web_root: Path, case_workspace: Optional[Path] = None,
    research_reader: Optional[ResearchReader] = None, diagnoses_root: Optional[Path] = None,
) -> Type[BaseHTTPRequestHandler]:
    """Create a handler closed over a catalog and the packaged static assets.

    ``research_reader`` reads stored (never fetched) research records and
    defaults to ``robot_debug.research_store.read_case_research``.
    ``diagnoses_root`` is the folder of registered diagnoses (default
    ``<artifacts>/diagnoses``, written by ``robot_debug.case_register``).
    """
    read_research = research_reader or default_research_reader
    diagnoses = diagnoses_root or catalog.artifact_root / "diagnoses"

    class ViewerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            try:
                if path == "/api/health":
                    self.send_json(200, {"status": "ok", "read_only": True})
                elif path == "/api/runs":
                    self.send_json(200, catalog.snapshot().to_dict())
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
                elif path in {"/", "/index.html", "/styles.css", "/app.js", "/diagnoses", "/diagnoses.js"}:
                    asset_name = {"/": "index.html", "/diagnoses": "diagnoses.html"}.get(path, path[1:])
                    asset = web_root / asset_name
                    if not asset.is_file():
                        raise FileNotFoundError(path)
                    self.stream_file(asset, allow_range=False)
                else:
                    self.send_json(404, {"error": "not found"})
            except (KeyError, FileNotFoundError, SanitizedCaseValidationError):
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
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def send_media(self, relative_path: str) -> None:
            self.stream_file(catalog.resolve_media(relative_path), allow_range=True)

        def stream_file(self, path: Path, allow_range: bool) -> None:
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
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if suffix == ".js":
                content_type = "text/javascript"
            if suffix in {".html", ".css", ".js"}:
                content_type += "; charset=utf-8"
            self.send_response(status)
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

        def log_message(self, message: str, *args: Any) -> None:
            logging.getLogger("robot_debug.viewer").info(message, *args)

    return ViewerHandler


def create_server(
    artifact_root: Path, host: str = "127.0.0.1", port: int = 8765,
    case_workspace: Optional[Path] = None, research_reader: Optional[ResearchReader] = None,
    diagnoses_root: Optional[Path] = None,
) -> ThreadingHTTPServer:
    catalog = ArtifactCatalog(artifact_root)
    web_root = Path(__file__).with_name("web")
    return ThreadingHTTPServer(
        (host, port), make_handler(catalog, web_root, case_workspace, research_reader, diagnoses_root))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only robot episode evidence viewer")
    parser.add_argument("--artifacts", default="artifacts")
    parser.add_argument("--cases")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    server = create_server(Path(args.artifacts), args.host, args.port, Path(args.cases) if args.cases else None)
    print("Faultline Viewer: http://{}:{}".format(*server.server_address))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
