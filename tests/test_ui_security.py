"""The session token and the guard in front of every control (ADR 0033): each refusal is tested."""

from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path

from robot_debug.viewer.api import Api
from robot_debug.viewer.security import MAX_BODY_BYTES, ApiError, ControlGuard, is_loopback
from tests.ui_server import RunningServer


class GuardUnitTests(unittest.TestCase):
    def guard(self, host="127.0.0.1", port=8765, token="T" * 43):
        return ControlGuard(host, port, token)

    def headers(self, **overrides):
        base = {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "X-Faultline-Token": "T" * 43}
        base.update(overrides)
        return {k: v for k, v in base.items() if v is not None}

    def test_loopback_addresses(self):
        for host in ("127.0.0.1", "localhost", "LOCALHOST", "::1", "[::1]", "127.0.0.2"):
            self.assertTrue(is_loopback(host), host)
        for host in ("0.0.0.0", "192.168.1.5", "::", "example.com", "", None, "10.0.0.1"):
            self.assertFalse(is_loopback(host), host)

    def test_the_names_the_server_answers_to(self):
        guard = self.guard()
        self.assertEqual(guard.hosts, ("127.0.0.1:8765", "localhost:8765"))
        self.assertEqual(guard.origins, ("http://127.0.0.1:8765", "http://localhost:8765"))

    def test_a_complete_request_passes_with_either_loopback_name(self):
        guard = self.guard()
        self.assertIsNone(guard.check(self.headers()))
        self.assertIsNone(guard.check(self.headers(Host="localhost:8765", Origin="http://localhost:8765")))

    def test_every_missing_or_wrong_part_is_refused(self):
        guard = self.guard()
        cases = {
            "no token": self.headers(**{"X-Faultline-Token": None}),
            "empty token": self.headers(**{"X-Faultline-Token": ""}),
            "wrong token": self.headers(**{"X-Faultline-Token": "x" * 43}),
            "prefix of the token": self.headers(**{"X-Faultline-Token": "T" * 42}),
            "no origin": self.headers(Origin=None),
            "null origin": self.headers(Origin="null"),
            "other site": self.headers(Origin="http://evil.example"),
            "same host other port": self.headers(Origin="http://127.0.0.1:9999"),
            "https": self.headers(Origin="https://127.0.0.1:8765"),
            "trailing slash": self.headers(Origin="http://127.0.0.1:8765/"),
            "origin with a path": self.headers(Origin="http://127.0.0.1:8765/x"),
            "look-alike": self.headers(Origin="http://127.0.0.1:8765.evil.example"),
            "no host": self.headers(Host=None),
            "rebinding host": self.headers(Host="evil.example:8765"),
            "host without a port": self.headers(Host="127.0.0.1"),
            "host on another port": self.headers(Host="127.0.0.1:9999"),
            "lan address": self.headers(Host="192.168.1.5:8765"),
        }
        for label, headers in cases.items():
            with self.subTest(label):
                refusal = guard.check(headers)
                self.assertIsNotNone(refusal, label)
                self.assertEqual(refusal.status, 403)
                self.assertNotIn("T" * 10, refusal.message, "a refusal never echoes the token")

    def test_controls_are_off_for_a_non_loopback_bind_whatever_the_request(self):
        for host in ("0.0.0.0", "192.168.1.5", "::"):
            guard = ControlGuard(host, 8765, "T" * 43)
            self.assertFalse(guard.controls)
            refusal = guard.check(self.headers())
            self.assertEqual(refusal.status, 403)
            self.assertIn("localhost", refusal.message)
            session = guard.session(self.headers(), "1.0")
            self.assertEqual((session["controls"], session["token"]), (False, None))

    def test_the_session_gives_the_token_only_to_a_loopback_host_name(self):
        guard = self.guard()
        session = guard.session({"Host": "127.0.0.1:8765"}, "9.9")
        self.assertEqual(session, {"api_version": 1, "mode": "local", "controls": True, "token": "T" * 43, "version": "9.9"})
        for host in ("evil.example:8765", "127.0.0.1", None):
            session = guard.session({} if host is None else {"Host": host}, "9.9")
            self.assertEqual((session["controls"], session["token"]), (False, None), host)

    def test_tokens_are_random_per_guard_and_long(self):
        tokens = {ControlGuard("127.0.0.1", 1).token for _ in range(5)}
        self.assertEqual(len(tokens), 5)
        self.assertTrue(all(len(t) >= 40 for t in tokens))

    def test_body_length_rules(self):
        guard = self.guard()
        self.assertEqual(guard.body_length({}), 0)
        self.assertEqual(guard.body_length({"Content-Length": "12"}), 12)
        self.assertEqual(guard.body_length({"Content-Length": str(MAX_BODY_BYTES)}), MAX_BODY_BYTES)
        for headers, status in (({"Content-Length": str(MAX_BODY_BYTES + 1)}, 413), ({"Content-Length": "-1"}, 400),
                                ({"Content-Length": "abc"}, 400), ({"Transfer-Encoding": "chunked"}, 411)):
            with self.subTest(headers=headers), self.assertRaises(ApiError) as caught:
                guard.body_length(headers)
            self.assertEqual(caught.exception.status, status)

    def test_body_parsing(self):
        guard = self.guard()
        self.assertEqual(guard.parse_body(b""), {})
        self.assertEqual(guard.parse_body(b' {"a": 1} '), {"a": 1})
        for bad in (b"{nope", b"[1]", b'"text"', b"\xff\xfe", b"null"):
            with self.subTest(bad=bad), self.assertRaises(ApiError) as caught:
                guard.parse_body(bad)
            self.assertEqual(caught.exception.status, 400)


def boom(request):
    raise RuntimeError("secret detail C:\\Users\\someone\\x aijob-fakefakefake0001")


class HttpSecurityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)

        def setup(api: Api) -> None:
            api.add_route("POST", r"/api/test/echo", lambda request: (200, {"echo": request.body, "length": len(request.body)} if len(json.dumps(request.body)) < 100
                                                        else {"keys": sorted(request.body)}))
            api.add_route("POST", r"/api/test/boom", boom)
            api.add_route("GET", r"/api/test/boom", boom)

        self.server = RunningServer(Path(directory.name), api_setup=setup)
        self.addCleanup(self.server.close)

    def test_a_request_with_the_token_and_the_viewers_own_origin_is_served(self):
        status, payload = self.server.post_json("/api/test/echo", {"hello": "world"})
        self.assertEqual((status, payload["echo"]), (200, {"hello": "world"}))

    def test_the_localhost_name_works_too(self):
        port = self.server.port
        status, payload = self.server.post_json("/api/test/echo", {"a": 1}, host="localhost:{}".format(port),
                                                headers={"Origin": "http://localhost:{}".format(port)})
        self.assertEqual(status, 200)

    def test_the_session_endpoint_issues_the_token_to_the_page(self):
        session = self.server.session()
        self.assertEqual(session["api_version"], 1)
        self.assertEqual((session["mode"], session["controls"]), ("local", True))
        self.assertEqual(session["token"], self.server.guard.token)
        self.assertIsInstance(session["version"], str)
        status, headers, _body = self.server.request("GET", "/api/session")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("Access-Control-Allow-Origin", headers, "no CORS: another page cannot read the token")

    def test_a_rebinding_page_does_not_get_the_token(self):
        status, _headers, body = self.server.request("GET", "/api/session", host="evil.example:{}".format(self.server.port))
        payload = json.loads(body)
        self.assertEqual((status, payload["controls"], payload["token"]), (200, False, None))
        self.assertNotIn(self.server.guard.token, body.decode("utf-8"))

    def test_every_refusal_is_403_and_never_runs_the_route(self):
        port = self.server.port
        token = self.server.guard.token
        good = {"Origin": self.server.origin, "X-Faultline-Token": token}
        cases = [
            ("no token", {"Origin": self.server.origin}, None),
            ("wrong token", dict(good, **{"X-Faultline-Token": "wrong"}), None),
            ("no origin", {"X-Faultline-Token": token}, None),
            ("foreign origin", dict(good, Origin="http://evil.example"), None),
            ("null origin", dict(good, Origin="null"), None),
            ("origin other port", dict(good, Origin="http://127.0.0.1:{}".format(port + 1)), None),
            ("rebinding host", good, "evil.example:{}".format(port)),
            ("host without port", good, "127.0.0.1"),
            ("lan host", good, "192.168.1.5:{}".format(port)),
        ]
        for label, headers, host in cases:
            with self.subTest(label):
                status, _headers, body = self.server.request("POST", "/api/test/echo", {"x": 1}, headers, host=host)
                self.assertEqual(status, 403)
                payload = json.loads(body)
                self.assertEqual(set(payload), {"error", "errors"})
                self.assertNotIn(token, body.decode("utf-8"))
                self.assertNotIn("echo", payload)

    def test_a_refused_request_does_not_reveal_whether_a_path_exists(self):
        for path in ("/api/test/echo", "/api/runs/anything/stop", "/api/nonsense"):
            status, _headers, _body = self.server.request("POST", path, {}, {"Origin": "http://evil.example"})
            self.assertEqual(status, 403, path)

    def test_an_unknown_path_with_valid_credentials_is_404(self):
        status, payload = self.server.post_json("/api/nonsense", {})
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "There is nothing at this address.")

    def test_a_body_of_exactly_two_megabytes_is_accepted_and_one_byte_more_is_refused(self):
        filler = '{"pad": "' + "x" * (MAX_BODY_BYTES - len('{"pad": ""}')) + '"}'
        self.assertEqual(len(filler.encode("utf-8")), MAX_BODY_BYTES)
        status, headers, body = self.server.post("/api/test/echo", raw=filler.encode("utf-8"))
        self.assertEqual((status, json.loads(body)), (200, {"keys": ["pad"]}))
        # One byte over: the server answers from the declared length, before reading the body.
        connection = socket.create_connection(("127.0.0.1", self.server.port), timeout=10)
        try:
            request = ("POST /api/test/echo HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nOrigin: {}\r\nX-Faultline-Token: {}\r\n"
                       "Content-Length: {}\r\nConnection: close\r\n\r\n").format(
                           self.server.port, self.server.origin, self.server.guard.token, MAX_BODY_BYTES + 1)
            connection.sendall(request.encode("ascii") + b"{}")
            chunks = []
            while True:
                block = connection.recv(4096)
                if not block:
                    break
                chunks.append(block)
            answer = b"".join(chunks).decode("latin-1")
        finally:
            connection.close()
        self.assertTrue(answer.startswith("HTTP/1.0 413") or answer.startswith("HTTP/1.1 413"), answer[:60])
        self.assertIn("larger than 2 MB", answer)

    def test_a_bad_body_is_a_400_with_a_plain_sentence(self):
        for raw in (b"{nope", b"[1, 2]"):
            status, headers, body = self.server.post("/api/test/echo", raw=raw)
            self.assertEqual(status, 400, raw)
            self.assertIn("error", json.loads(body))
            self.assertNotIn("Traceback", body.decode("utf-8"))

    def test_a_route_that_blows_up_gives_a_sentence_and_no_detail(self):
        for status, headers, body in (self.server.post("/api/test/boom", {}),
                                      self.server.request("GET", "/api/test/boom")):
            self.assertEqual(status, 500)
            text = body.decode("utf-8")
            self.assertEqual(set(json.loads(text)), {"error", "errors"})
            for leak in ("secret detail", "someone", "aijob", "Traceback", "RuntimeError"):
                self.assertNotIn(leak, text)

    def test_an_empty_post_is_an_empty_object(self):
        status, payload = self.server.post_json("/api/test/echo")
        self.assertEqual((status, payload["echo"]), (200, {}))

    def test_the_token_never_appears_outside_the_session_response(self):
        token = self.server.guard.token
        for method, path in (("GET", "/api/health"), ("GET", "/api/nonsense"), ("GET", "/")):
            _status, headers, body = self.server.request(method, path)
            self.assertNotIn(token, body.decode("utf-8", "replace"), path)
            self.assertNotIn(token, json.dumps(headers))
        status, headers, body = self.server.post("/api/test/echo", {"a": 1})
        self.assertNotIn(token, body.decode("utf-8"))

    def test_responses_forbid_framing_and_sniffing(self):
        for method, path in (("GET", "/api/session"), ("GET", "/api/health"), ("POST", "/api/test/echo")):
            _status, headers, _body = self.server.request(method, path, None if method == "GET" else {},
                                                          None if method == "GET" else self.server.good_headers())
            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff", path)
            self.assertEqual(headers.get("X-Frame-Options"), "DENY", path)
            self.assertEqual(headers.get("Cache-Control"), "no-store", path)


class NonLoopbackBindTests(unittest.TestCase):
    def test_controls_are_disabled_when_the_guard_is_for_a_public_bind(self):
        with tempfile.TemporaryDirectory() as directory:
            def setup(api: Api) -> None:
                api.add_route("POST", r"/api/test/echo", lambda request: (200, {"echo": True}))

            server = RunningServer(Path(directory), api_setup=setup)
            try:
                # The same server, but told it was bound to a LAN address: the guard must refuse everything.
                server.guard.host, server.guard.controls = "192.168.1.5", False
                session = server.session()
                self.assertEqual((session["controls"], session["token"]), (False, None))
                status, _headers, body = server.post("/api/test/echo", {})
                self.assertEqual(status, 403)
                self.assertIn("localhost", json.loads(body)["error"])
            finally:
                server.close()


if __name__ == "__main__":
    unittest.main()
