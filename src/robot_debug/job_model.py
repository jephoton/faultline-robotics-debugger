"""Bounded lifecycle and WebSocket readiness for one local model server."""

from __future__ import annotations

import base64
import hashlib
import math
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
from typing import Mapping, Sequence, Union
import uuid

from .job_process import InfrastructureError, close_owned_process_group


_WEBSOCKET_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_HEADERS = 16 * 1024


class ModelProcess:
    """Own one explicitly configured model server process group."""

    def __init__(
        self,
        *,
        argv: Sequence[str],
        cwd: Union[os.PathLike, str],
        env: Mapping[str, str],
        log_root: Union[os.PathLike, str],
        port: int = 8000,
    ) -> None:
        if isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence):
            raise TypeError("argv must be a sequence of strings")
        argv_copy = tuple(argv)
        if not argv_copy:
            raise ValueError("argv must not be empty")
        if any(not isinstance(item, str) for item in argv_copy):
            raise TypeError("argv must contain only strings")
        if any(not item or "\x00" in item for item in argv_copy):
            raise ValueError("argv entries must be non-empty and contain no NUL")
        if not os.path.isabs(argv_copy[0]):
            raise ValueError("argv executable must be an absolute path")
        if isinstance(cwd, bytes):
            raise TypeError("cwd must be a text path")
        self._cwd = Path(os.fspath(cwd))
        if not self._cwd.is_dir() or self._cwd.is_symlink():
            raise ValueError("cwd must be an existing ordinary directory")
        if not isinstance(env, Mapping):
            raise TypeError("env must be a mapping of strings")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in env.items()
        ):
            raise TypeError("env must be a mapping of strings")
        self._env = dict(env)
        if isinstance(log_root, bytes):
            raise TypeError("log_root must be a text path")
        log_text = os.fspath(log_root)
        if not isinstance(log_text, str) or not log_text or "\x00" in log_text:
            raise ValueError("log_root must be a non-empty text path")
        self._log_root = Path(log_text)
        if isinstance(port, bool) or not isinstance(port, int):
            raise TypeError("port must be an ordinary integer")
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        self._argv = argv_copy
        self._port = port
        self._process = None
        self._stdout = None
        self._stderr = None
        self._started = False
        self._closed = False

    @property
    def argv(self) -> list:
        """The server command line (no secrets: paths and flags only)."""

        return list(self._argv)

    def start(self) -> None:
        if os.name != "posix":
            raise InfrastructureError("model process execution requires POSIX process groups")
        if self._started or self._closed:
            raise InfrastructureError("model process can only be started once")
        self._started = True
        if self._log_root.is_symlink():
            raise InfrastructureError("model log directory must not be a symbolic link")
        try:
            self._log_root.mkdir(parents=True, exist_ok=True)
            if not self._log_root.is_dir():
                raise OSError("not a directory")
            ident = uuid.uuid4().hex
            self._stdout = (self._log_root / (ident + ".stdout.log")).open("xb")
            self._stderr = (self._log_root / (ident + ".stderr.log")).open("xb")
            self._process = subprocess.Popen(
                self._argv,
                cwd=str(self._cwd),
                env=self._env,
                shell=False,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=self._stdout,
                stderr=self._stderr,
            )
        except BaseException as error:
            self._close_logs()
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise InfrastructureError("model process could not be started") from error

    def check_alive(self) -> None:
        if self._process is None or self._closed:
            raise InfrastructureError("model process is not running")
        if self._process.poll() is not None:
            raise InfrastructureError("model process exited before readiness")

    def wait_ready(self, *, deadline: float) -> None:
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
            raise ValueError("deadline must be a finite monotonic timestamp")
        try:
            deadline = float(deadline)
        except (OverflowError, ValueError):
            raise ValueError("deadline must be a finite monotonic timestamp")
        if not math.isfinite(deadline):
            raise ValueError("deadline must be a finite monotonic timestamp")
        while True:
            self.check_alive()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InfrastructureError("model readiness deadline expired")
            try:
                self._probe(deadline)
                self.check_alive()
                if time.monotonic() >= deadline:
                    raise InfrastructureError("model readiness deadline expired")
                return
            except InfrastructureError as error:
                if str(error) in (
                    "model process is not running",
                    "model process exited before readiness",
                    "model readiness deadline expired",
                ):
                    raise
                self._retry_pause(deadline)
            except OSError:
                self._retry_pause(deadline)

    def _probe(self, deadline: float) -> None:
        key = base64.b64encode(secrets.token_bytes(16))
        request = (
            "GET / HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: {}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).format(self._port, key.decode("ascii")).encode("ascii")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(self._remaining_timeout(deadline))
            connection.connect(("127.0.0.1", self._port))
            connection.settimeout(self._remaining_timeout(deadline))
            connection.sendall(request)
            response = bytearray()
            while b"\r\n\r\n" not in response:
                if len(response) >= _MAX_HEADERS:
                    raise InfrastructureError("model readiness response headers are invalid")
                connection.settimeout(self._remaining_timeout(deadline))
                chunk = connection.recv(min(4096, _MAX_HEADERS - len(response)))
                if not chunk:
                    raise InfrastructureError("model readiness response headers are invalid")
                response.extend(chunk)
                if len(response) > _MAX_HEADERS:
                    raise InfrastructureError("model readiness response headers are invalid")
            if time.monotonic() >= deadline:
                raise InfrastructureError("model readiness deadline expired")
            self._validate_upgrade(bytes(response), key)

    def _validate_upgrade(self, response: bytes, key: bytes) -> None:
        header_block, _rest = response.split(b"\r\n\r\n", 1)
        try:
            lines = header_block.decode("iso-8859-1").split("\r\n")
            status = lines[0].split(" ", 2)
            if len(status) < 2 or status[0] != "HTTP/1.1" or status[1] != "101":
                raise ValueError
            headers = {}
            for line in lines[1:]:
                if not line or ":" not in line or line[0] in " \t":
                    raise ValueError
                name, value = line.split(":", 1)
                if not name or any(
                    not (ch.isascii() and (ch.isalnum() or ch in "!#$%&'*+-.^_`|~"))
                    for ch in name
                ):
                    raise ValueError
                lower = name.lower()
                headers.setdefault(lower, []).append(value.strip())
            for critical in ("upgrade", "connection", "sec-websocket-accept"):
                if len(headers.get(critical, ())) != 1:
                    raise ValueError
            if headers["upgrade"][0].lower() != "websocket":
                raise ValueError
            tokens = [part.strip().lower() for part in headers["connection"][0].split(",")]
            if "upgrade" not in tokens:
                raise ValueError
            expected = base64.b64encode(
                hashlib.sha1(key + _WEBSOCKET_GUID).digest()
            ).decode("ascii")
            if headers["sec-websocket-accept"][0] != expected:
                raise ValueError
        except (UnicodeError, ValueError, IndexError):
            raise InfrastructureError("model readiness response headers are invalid")

    @staticmethod
    def _remaining_timeout(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise InfrastructureError("model readiness deadline expired")
        return min(1.0, remaining)

    def _retry_pause(self, deadline: float) -> None:
        self.check_alive()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise InfrastructureError("model readiness deadline expired")
        time.sleep(min(0.1, remaining))

    def close(self) -> None:
        if self._closed:
            return
        if self._process is not None:
            close_owned_process_group(self._process, self._process.pid)
        self._closed = True
        self._close_logs()

    def _close_logs(self) -> None:
        for log in (self._stdout, self._stderr):
            if log is not None and not log.closed:
                log.close()
