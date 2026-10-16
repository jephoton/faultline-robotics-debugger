"""Who may start, stop and replay runs through the local server (ADR 0033).

The control panel can start billable runs, so a request that changes anything is accepted only when all of
these hold, and each refusal is a plain sentence that reveals nothing about the others:

* the server is bound to a loopback address (otherwise controls are off altogether, whatever the request);
* ``Host`` is exactly ``127.0.0.1:<port>`` or ``localhost:<port>`` (a DNS-rebinding page arrives with its own
  host name);
* ``Origin`` is present and exactly ``http://127.0.0.1:<port>`` or ``http://localhost:<port>`` (another web
  page, or a request with no Origin at all, is refused);
* ``X-Faultline-Token`` carries the per-start session token issued by ``GET /api/session``;
* the JSON body is at most 2 MB.

No CORS header is ever sent, so a page on another origin cannot read ``/api/session`` either. The token is
random for each server start, compared in constant time and never written to a log or an error message.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
from typing import Any, Dict, Mapping, NamedTuple, Optional

TOKEN_HEADER = "X-Faultline-Token"
MAX_BODY_BYTES = 2 * 1024 * 1024
LOOPBACK_NAMES = ("127.0.0.1", "localhost")


class Refusal(NamedTuple):
    status: int
    message: str


class ApiError(Exception):
    """A request the server refuses with a plain sentence (and, for a spec, the field errors)."""

    def __init__(self, status: int, message: str, errors: Optional[list] = None) -> None:
        super().__init__(message)
        self.status, self.message, self.errors = status, message, list(errors or [])

    def payload(self) -> Dict[str, Any]:
        return {"error": self.message, "errors": self.errors}


def is_loopback(host: str) -> bool:
    """Whether a bind address is the loopback interface (``localhost``, 127.0.0.0/8 or ``::1``)."""

    if not isinstance(host, str) or not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


class ControlGuard:
    """Decides whether a request may use the controls, and issues the session token."""

    def __init__(self, host: str, port: int, token: Optional[str] = None) -> None:
        self.host, self.port = host, int(port)
        self.token = token or secrets.token_urlsafe(32)
        self.controls = is_loopback(host)

    # -- the names this server answers to ------------------------------------------------------

    @property
    def hosts(self) -> tuple:
        return tuple("{}:{}".format(name, self.port) for name in LOOPBACK_NAMES)

    @property
    def origins(self) -> tuple:
        return tuple("http://" + host for host in self.hosts)

    def host_ok(self, headers: Mapping[str, str]) -> bool:
        return headers.get("Host") in self.hosts

    # -- the session --------------------------------------------------------------------------------

    def session(self, headers: Mapping[str, str], version: str) -> Dict[str, Any]:
        """``GET /api/session``: the token goes only to a page that reached the server by its own loopback name."""

        enabled = self.controls and self.host_ok(headers)
        return {"api_version": 1, "mode": "local", "controls": enabled,
                "token": self.token if enabled else None, "version": version}

    # -- the checks ------------------------------------------------------------------------------------

    def check(self, headers: Mapping[str, str]) -> Optional[Refusal]:
        """``None`` when the headers of a control request pass every check, else the refusal."""

        if not self.controls:
            return Refusal(403, "Controls are only available when the viewer is bound to localhost.")
        if not self.host_ok(headers):
            return Refusal(403, "This request did not reach the viewer by its localhost address.")
        if headers.get("Origin") not in self.origins:
            return Refusal(403, "This request did not come from the viewer page.")
        supplied = headers.get(TOKEN_HEADER) or ""
        if not hmac.compare_digest(supplied.encode("utf-8"), self.token.encode("utf-8")):
            return Refusal(403, "The session token is missing or no longer valid; reload the page.")
        return None

    @staticmethod
    def body_length(headers: Mapping[str, str]) -> int:
        """The declared body size; raises :class:`ApiError` for a missing, malformed or oversize length."""

        if headers.get("Transfer-Encoding"):
            raise ApiError(411, "The request must declare its length.")
        raw = headers.get("Content-Length")
        if raw is None:
            return 0
        if not raw.isdigit():
            raise ApiError(400, "The request length is not valid.")
        length = int(raw)
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "The request is larger than 2 MB.")
        return length

    @staticmethod
    def parse_body(data: bytes) -> Dict[str, Any]:
        if not data.strip():
            return {}
        try:
            value = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise ApiError(400, "The request body is not valid JSON.") from None
        if not isinstance(value, dict):
            raise ApiError(400, "The request body must be a JSON object.")
        return value
