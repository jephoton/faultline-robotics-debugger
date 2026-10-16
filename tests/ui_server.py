"""A real server on a free local port for the control-panel tests (not a test module itself)."""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from robot_debug.viewer import server as viewer_server


class RunningServer:
    """``create_server`` on port 0 in a thread; ``request`` sends exactly the headers it is given."""

    def __init__(self, artifact_root: Path, host: str = "127.0.0.1", **options: Any) -> None:
        self.server = viewer_server.create_server(Path(artifact_root), host, 0, **options)
        self.port = self.server.server_address[1]
        self.guard = self.server.api.guard
        self.api = self.server.api
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)

    # -- requests ---------------------------------------------------------------------------------------

    @property
    def origin(self) -> str:
        return "http://127.0.0.1:{}".format(self.port)

    def session(self) -> Dict[str, Any]:
        status, _headers, body = self.request("GET", "/api/session")
        assert status == 200, status
        return json.loads(body)

    def good_headers(self, token: Optional[str] = None) -> Dict[str, str]:
        return {"Origin": self.origin, "X-Faultline-Token": token or self.guard.token,
                "Content-Type": "application/json"}

    def request(self, method: str, path: str, body: Any = None, headers: Optional[Mapping[str, str]] = None,
                host: Optional[str] = None, raw: Optional[bytes] = None):
        """``(status, response headers, response body bytes)``; ``Host`` defaults to the server's own name."""

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            sent = dict(headers or {})
            data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            connection.putheader("Host", host if host is not None else "127.0.0.1:{}".format(self.port))
            for name, value in sent.items():
                connection.putheader(name, value)
            if data is not None:
                connection.putheader("Content-Length", str(len(data)))
            connection.endheaders(data)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def post(self, path: str, body: Any = None, headers: Optional[Mapping[str, str]] = None, **kwargs):
        merged = self.good_headers()
        merged.update(headers or {})
        return self.request("POST", path, body, merged, **kwargs)

    def post_json(self, path: str, body: Any = None, **kwargs):
        status, headers, data = self.post(path, body, **kwargs)
        return status, json.loads(data)


def temporary_root() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory()
