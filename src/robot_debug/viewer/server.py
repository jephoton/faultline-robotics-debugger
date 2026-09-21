"""Read-only HTTP server for locally collected robot-debug evidence."""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from typing import Any, Mapping, Optional, Sequence, Type
from urllib.parse import unquote, urlsplit

from robot_debug.viewer.catalog import ArtifactCatalog


def make_handler(
    catalog: ArtifactCatalog, web_root: Path
) -> Type[BaseHTTPRequestHandler]:
    """Create a handler closed over a catalog and the packaged static assets."""

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
                elif path.startswith("/api/episodes/") and path.endswith("/trace"):
                    episode_id = path[len("/api/episodes/") : -len("/trace")]
                    self.send_json(200, catalog.load_trace(episode_id))
                elif path.startswith("/media/"):
                    self.send_media(unquote(path[len("/media/") :]))
                elif path in {"/", "/index.html", "/styles.css", "/app.js"}:
                    asset_name = "index.html" if path == "/" else path[1:]
                    asset = web_root / asset_name
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


if __name__ == "__main__":
    raise SystemExit(main())
