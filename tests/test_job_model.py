from __future__ import annotations

import os
import ctypes
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import textwrap
import unittest
from unittest import mock

from robot_debug.job_model import ModelProcess
from robot_debug.job_process import InfrastructureError


class ModelProcessValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.logs = self.root / "logs"
        self.models = []

    def tearDown(self) -> None:
        for model in reversed(self.models):
            model.close()
        self._temporary.cleanup()

    def model(self, **overrides: object) -> ModelProcess:
        values = dict(
            argv=[sys.executable, "-c", "pass"], cwd=self.root,
            env=dict(os.environ), log_root=self.logs, port=8000,
        )
        values.update(overrides)
        model = ModelProcess(**values)  # type: ignore[arg-type]
        self.models.append(model)
        return model

    def test_constructor_copies_environment_and_does_not_create_logs(self) -> None:
        env = {"SAFE": "value"}
        model = self.model(env=env)
        env["SAFE"] = "changed"
        self.assertFalse(self.logs.exists())
        self.assertEqual(model._env["SAFE"], "value")

    def test_close_before_start_is_safe_and_prevents_later_start(self) -> None:
        model = self.model()
        model.close()
        model.close()
        with self.assertRaises(InfrastructureError):
            model.start()

    def test_rejects_invalid_argv_cwd_env_and_port(self) -> None:
        cases = (
            {"argv": []}, {"argv": "python"}, {"argv": [sys.executable, "a\0b"]},
            {"argv": ["relative-exe"]}, {"cwd": self.root / "missing"},
            {"env": {"A": 1}}, {"port": True}, {"port": 0}, {"port": 65536},
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises((TypeError, ValueError)):
                self.model(**values)

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_start_close_and_repeat_close_own_real_process_group(self) -> None:
        marker = self.root / "started"
        model = self.model(argv=[sys.executable, "-c", "import pathlib,time; pathlib.Path(%r).write_text('ok'); time.sleep(60)" % str(marker)])
        model.start()
        process_group = model._process.pid
        deadline = time.monotonic() + 2
        try:
            while not marker.exists() and time.monotonic() < deadline:
                model.check_alive()
                time.sleep(0.01)
            model.check_alive()
            self.assertTrue(marker.exists())
        finally:
            model.close()
        model.close()
        with self.assertRaises(ProcessLookupError):
            os.killpg(process_group, 0)

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_check_alive_rejects_zero_exit_and_start_is_single_use(self) -> None:
        model = self.model()
        model.start()
        model._process.wait(timeout=2)
        with self.assertRaises(InfrastructureError):
            model.check_alive()
        model.close()
        with self.assertRaises(InfrastructureError):
            model.start()

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_nonzero_exit_is_not_alive_and_close_remains_safe(self) -> None:
        model = self.model(argv=[sys.executable, "-c", "raise SystemExit(9)"])
        model.start()
        self.assertEqual(model._process.wait(timeout=2), 9)
        with self.assertRaises(InfrastructureError):
            model.check_alive()
        model.close()

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_spawn_failure_is_single_use_and_close_is_safe(self) -> None:
        model = self.model(argv=[str(self.root / "missing-executable")])
        with self.assertRaises(InfrastructureError):
            model.start()
        self.assertTrue(model._stdout.closed)
        self.assertTrue(model._stderr.closed)
        model.close()
        with self.assertRaises(InfrastructureError):
            model.start()

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_failed_cleanup_keeps_ownership_and_can_be_retried(self) -> None:
        model = self.model()
        model.start()
        with mock.patch("robot_debug.job_model.close_owned_process_group", side_effect=InfrastructureError("uncertain")):
            with self.assertRaises(InfrastructureError):
                model.close()
        self.assertFalse(model._stdout.closed)
        model.close()
        self.assertTrue(model._stdout.closed)

    @unittest.skipUnless(sys.platform == "linux", "requires Linux subreaper support")
    def test_close_kills_term_ignoring_orphan_after_leader_exits(self) -> None:
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        child_marker = self.root / "child.pid"
        ready_marker = self.root / "child.ready"
        child_source = (
            "import pathlib,signal,time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "pathlib.Path(%r).write_text('ready'); time.sleep(60)"
        ) % str(ready_marker)
        source = textwrap.dedent(
            """\
            import pathlib,subprocess,sys,time
            child = subprocess.Popen([sys.executable, '-c', %r])
            pathlib.Path(%r).write_text(str(child.pid))
            ready = pathlib.Path(%r)
            deadline = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            """
        ) % (child_source, str(child_marker), str(ready_marker))
        model = self.model(argv=[sys.executable, "-c", source])
        try:
            model.start()
            deadline = time.monotonic() + 2
            while not child_marker.exists() and time.monotonic() < deadline:
                model.check_alive()
                time.sleep(0.01)
            self.assertTrue(child_marker.exists())
            model._process.wait(timeout=2)
            self.assertTrue(ready_marker.exists())
            child_pid = int(child_marker.read_text())
            started = time.monotonic()
            model.close()
            self.assertGreaterEqual(time.monotonic() - started, 4.5)
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            model.close()
            self.assertEqual(libc.prctl(36, previous.value, 0, 0, 0), 0)


@unittest.skipUnless(os.name == "posix", "requires POSIX model process groups")
class ModelReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(1)
        self.port = self.listener.getsockname()[1]
        self.thread = None
        self.models = []

    def tearDown(self) -> None:
        for model in reversed(self.models):
            model.close()
        self.listener.close()
        if self.thread:
            self.thread.join(timeout=2)
            self.assertFalse(self.thread.is_alive())
        self._temporary.cleanup()

    def model(self, **overrides: object) -> ModelProcess:
        values = dict(
            argv=[sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=self.root,
            env=dict(os.environ),
            log_root=self.root / "logs",
            port=self.port,
        )
        values.update(overrides)
        model = ModelProcess(**values)  # type: ignore[arg-type]
        self.models.append(model)
        return model

    def _serve_response(self, response: bytes, *, delay: float = 0, drip: float = 0) -> None:
        self.listener.settimeout(1)

        def serve() -> None:
            try:
                conn, _ = self.listener.accept()
                with conn:
                    conn.recv(4096)
                    if delay:
                        time.sleep(delay)
                    if drip:
                        for byte in response:
                            conn.sendall(bytes((byte,)))
                            time.sleep(drip)
                    else:
                        conn.sendall(response)
            except (OSError, socket.timeout):
                pass

        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()

    def test_accepts_real_websocket_upgrade(self) -> None:
        def serve() -> None:
            try:
                conn, _ = self.listener.accept()
                with conn:
                    request = b""
                    while b"\r\n\r\n" not in request:
                        request += conn.recv(4096)
                    key = next(
                        line.split(b":", 1)[1].strip()
                        for line in request.split(b"\r\n")
                        if line.lower().startswith(b"sec-websocket-key:")
                    )
                    import base64
                    import hashlib
                    accept = base64.b64encode(
                        hashlib.sha1(
                            key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                        ).digest()
                    )
                    conn.sendall(
                        b"HTTP/1.1 101 Switching Protocols\r\n"
                        b"Upgrade: WebSocket\r\n"
                        b"Connection: keep-alive, Upgrade\r\n"
                        b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
                    )
            except (OSError, socket.timeout):
                pass
        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        model = self.model()
        model.start()
        try:
            model.wait_ready(deadline=time.monotonic() + 2)
        finally:
            model.close()

    def test_rejects_http_200_until_deadline(self) -> None:
        self._serve_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        model = self.model()
        model.start()
        try:
            with self.assertRaises(InfrastructureError):
                model.wait_ready(deadline=time.monotonic() + 0.25)
        finally:
            model.close()

    def test_rejects_bad_or_duplicate_accept_header(self) -> None:
        for response in (
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: wrong\r\n\r\n",
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n",
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: a\r\nsec-websocket-accept: b\r\n\r\n",
        ):
            with self.subTest(response=response):
                self._serve_response(response)
                model = self.model()
                model.start()
                try:
                    with self.assertRaises(InfrastructureError):
                        model.wait_ready(deadline=time.monotonic() + 0.15)
                finally:
                    model.close()
                if self.thread:
                    self.thread.join(timeout=2)
                    self.assertFalse(self.thread.is_alive())
                    self.thread = None

    def test_rejects_truncated_and_oversized_headers(self) -> None:
        for response in (b"HTTP/1.1 101 Switching Protocols\r\n", b"X" * (16 * 1024 + 1)):
            with self.subTest(length=len(response)):
                self._serve_response(response)
                model = self.model()
                model.start()
                try:
                    with self.assertRaises(InfrastructureError):
                        model.wait_ready(deadline=time.monotonic() + 0.15)
                finally:
                    model.close()
                if self.thread:
                    self.thread.join(timeout=2)
                    self.assertFalse(self.thread.is_alive())
                    self.thread = None

    def test_slow_drip_cannot_extend_absolute_deadline(self) -> None:
        self._serve_response(b"HTTP/1.1 101 Switching Protocols\r\n" + b"X-Test: " + b"a" * 500 + b"\r\n\r\n", drip=0.01)
        model = self.model()
        model.start()
        started = time.monotonic()
        try:
            with self.assertRaises(InfrastructureError):
                model.wait_ready(deadline=started + 0.2)
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            model.close()

    def test_delayed_response_cannot_extend_absolute_deadline(self) -> None:
        self._serve_response(b"HTTP/1.1 200 OK\r\n\r\n", delay=0.4)
        model = self.model()
        model.start()
        started = time.monotonic()
        try:
            with self.assertRaises(InfrastructureError):
                model.wait_ready(deadline=started + 0.2)
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            model.close()

    def test_refused_port_retries_only_until_deadline(self) -> None:
        self.listener.close()
        model = self.model()
        model.start()
        started = time.monotonic()
        try:
            with self.assertRaises(InfrastructureError):
                model.wait_ready(deadline=started + 0.2)
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            model.close()

    def test_expired_deadline_fails_immediately(self) -> None:
        model = self.model()
        model.start()
        try:
            with self.assertRaises(InfrastructureError):
                model.wait_ready(deadline=time.monotonic() - 1)
        finally:
            model.close()

    def test_rejects_nonfinite_or_non_numeric_deadline(self) -> None:
        model = self.model()
        for index, deadline in enumerate(
            (True, float("nan"), float("inf"), "later", 10 ** 10000)
        ):
            with self.subTest(case=index), self.assertRaises(ValueError):
                model.wait_ready(deadline=deadline)  # type: ignore[arg-type]

    def test_dead_model_fails_readiness_immediately(self) -> None:
        model = self.model(argv=[sys.executable, "-c", "raise SystemExit(0)"])
        model.start()
        model._process.wait(timeout=2)
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(InfrastructureError, "exited"):
                model.wait_ready(deadline=time.monotonic() + 1)
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            model.close()


if __name__ == "__main__":
    unittest.main()
