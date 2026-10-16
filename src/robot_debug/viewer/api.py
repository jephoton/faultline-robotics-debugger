"""The control-panel API: routing and the guard in front of every change (ADR 0033).

``server.py`` keeps the HTTP plumbing and the original read-only endpoints; the routes of API version 1 live
behind this class. A route is a ``(method, regular expression)`` pair and a function of a :class:`Request` that
returns ``(status, payload)`` or a :class:`FileResponse`. Every POST goes through
:meth:`robot_debug.viewer.security.ControlGuard.check` before its body is even read.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Pattern, Tuple, Union
from urllib.parse import parse_qs

from robot_debug.viewer.security import ApiError, ControlGuard


LEGACY_LOCAL_ONLY = ("/api/runs", "/api/evidence", "/api/reduction")       # the episode catalog: local only
LEGACY_LOCAL_PREFIXES = ("/api/episodes/",)


class Request(NamedTuple):
    params: Dict[str, str]                  # named groups of the route pattern
    query: Dict[str, List[str]]
    body: Dict[str, Any]
    headers: Mapping[str, str]

    def first(self, name: str) -> Optional[str]:
        values = self.query.get(name)
        return values[0] if values else None


class FileResponse(NamedTuple):
    path: Path
    content_type: str


class TextResponse(NamedTuple):
    text: str
    content_type: str


Response = Union[Tuple[int, Any], FileResponse, TextResponse]
Handler = Callable[[Request], Response]


def package_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("faultline")
        except PackageNotFoundError:
            return "0.0.0+source"
    except ImportError:                       # pragma: no cover - Python 3.11 always has importlib.metadata
        return "0.0.0+source"


class Api:
    """The routes of the control panel, each served only after the checks that apply to it."""

    def __init__(self, guard: ControlGuard, *, version: Optional[str] = None) -> None:
        self.guard = guard
        self.version = version or package_version()
        self._routes: Dict[str, List[Tuple[Pattern[str], Handler]]] = {"GET": [], "POST": []}
        self._local_only: List[Pattern[str]] = []
        self.add_route("GET", r"/api/session", lambda request: (200, self.guard.session(request.headers, self.version)))

    def add_route(self, method: str, pattern: str, handler: Handler, *, local_only: bool = False) -> None:
        """``local_only`` reads exist only behind a loopback bind (they show this machine's runs and setup)."""

        compiled = re.compile(pattern + r"\Z")
        self._routes[method].append((compiled, handler))
        if local_only:
            self._local_only.append(compiled)

    def read_refusal(self, path: str, headers: Mapping[str, str]) -> Optional[Tuple[int, Any]]:
        """The refusal of a GET before it is routed, or ``None``. Every ``/api/`` and ``/media/`` read must reach
        the server by its own name (so a DNS-rebinding page reads nothing); the session answer is shaped by the
        Host itself and is exempt. Local-only reads are 404 when controls are off."""

        if path == "/api/session" or not path.startswith(("/api/", "/media/")):
            return None
        if not self.guard.read_host_ok(headers):
            return 403, ApiError(403, "This request did not reach the viewer by its own address.").payload()
        if not self.guard.controls and (path in LEGACY_LOCAL_ONLY or path.startswith(LEGACY_LOCAL_PREFIXES)
                                        or any(p.match(path) for p in self._local_only)):
            return 404, ApiError(404, "There is nothing here.").payload()
        return None

    def _match(self, method: str, path: str) -> Optional[Tuple[Dict[str, str], Handler]]:
        for pattern, handler in self._routes[method]:
            found = pattern.match(path)
            if found is not None:
                return found.groupdict(), handler
        return None

    @staticmethod
    def _query(query_string: str) -> Dict[str, List[str]]:
        return parse_qs(query_string, keep_blank_values=True, max_num_fields=50)

    # -- the two entry points the server calls ------------------------------------------------------

    def handle_get(self, path: str, query_string: str, headers: Mapping[str, str]) -> Optional[Response]:
        """The response of a GET route of this API, or ``None`` when the path is not one of its routes."""

        refusal = self.read_refusal(path, headers)
        if refusal is not None:
            return refusal
        matched = self._match("GET", path)
        if matched is None:
            return None
        params, handler = matched
        try:
            return handler(Request(params, self._query(query_string), {}, headers))
        except ApiError as error:
            return error.status, error.payload()
        except (KeyError, FileNotFoundError):
            return 404, ApiError(404, "There is nothing here.").payload()
        except Exception:                           # noqa: BLE001 - the page gets a sentence, the console the traceback
            logging.getLogger("robot_debug.viewer").exception("GET %s failed", path)
            return 500, ApiError(500, "Something went wrong in the viewer; its console has the details.").payload()

    def handle_post(self, path: str, query_string: str, headers: Mapping[str, str],
                    read: Callable[[int], bytes]) -> Tuple[int, Any]:
        """Check, read and route one POST. A refusal never reads the body and never says which check failed
        beyond a plain sentence."""

        refusal = self.guard.check(headers)
        if refusal is not None:
            return refusal.status, ApiError(refusal.status, refusal.message).payload()
        try:
            length = self.guard.body_length(headers)
            body = self.guard.parse_body(read(length) if length else b"")
            matched = self._match("POST", path)
            if matched is None:
                raise ApiError(404, "There is nothing at this address.")
            params, handler = matched
            response = handler(Request(params, self._query(query_string), body, headers))
        except ApiError as error:
            return error.status, error.payload()
        except TimeoutError:                        # the client declared a body and stopped sending it
            return 408, ApiError(408, "The request body did not arrive in time.").payload()
        except Exception:                           # noqa: BLE001 - never a traceback in a response
            logging.getLogger("robot_debug.viewer").exception("POST %s failed", path)
            return 500, ApiError(500, "Something went wrong in the viewer; its console has the details.").payload()
        if isinstance(response, (FileResponse, TextResponse)):
            raise TypeError("a POST route returns JSON")
        return response
