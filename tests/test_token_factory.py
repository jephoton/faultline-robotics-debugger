"""Bounded Token Factory client tests; every provider response is a fixture."""

from __future__ import annotations

import io
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from robot_debug.evidence_packet import packet_identity
from robot_debug.token_factory import (
    ENDPOINT,
    MODEL,
    TokenFactoryError,
    load_api_key,
    preflight,
    request_interpretation,
    reserve_pilot,
)

PACKET = {
    "schema_version": 1,
    "task": {"suite": "libero-object", "task_id": 1, "reset_index": 0},
    "reduced_mask": {
        "family": "agentview-opaque-rectangle",
        "rectangle": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
        "fill_value": None,
    },
    "episodes": [{"evidence_id": "0123456789abcdef", "role": "reduced",
                  "raw_outcome": "task_failure", "gate_outcome": "policy_failure"}],
}
KEY = "TEST-SECRET-DO-NOT-LOG"
CONTENT = json.dumps({
    "schema_version": 1,
    "observations": [{"text": "The reported reduced episode failed.",
                      "evidence_ids": ["0123456789abcdef"]}],
    "hypotheses": [],
    "limitations": ["Evidence is limited."],
}, separators=(",", ":"))


class _Response:
    def __init__(self, body: bytes, status: int = 200):
        self.status = status
        self._body = io.BytesIO(body)

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)


class _Connection:
    instances: list["_Connection"] = []
    response = _Response(b"{}")

    def __init__(self, host, *, timeout, context):
        self.host = host
        self.timeout = timeout
        self.context = context
        self.calls = []
        self.closed = False
        self.__class__.instances.append(self)

    def request(self, method, path, body=None, headers=None):
        self.calls.append((method, path, body, headers))

    def getresponse(self):
        return self.__class__.response

    def close(self):
        self.closed = True


class TokenFactoryTests(unittest.TestCase):
    def response(self, **changes):
        value = {
            "model": MODEL,
            "choices": [{"message": {"content": CONTENT}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                      "total_tokens": 120},
        }
        value.update(changes)
        return value

    def assert_safe_failure(self, result, status, code):
        self.assertIsNone(result["response_json"])
        self.assertEqual(result["provenance"]["request_status"], status)
        self.assertEqual(result["provenance"]["error_code"], code)
        self.assertNotIn(KEY, json.dumps(result))

    def assert_store_compatible_provenance(self, provenance):
        status = provenance["request_status"]
        code = provenance["error_code"]
        self.assertTrue(
            (status == "transport_error" and code == "timeout")
            or (status == "http_error" and code in {
                "http_error", "authentication_failed", "catalog_missing",
            })
            or (status == "invalid_response" and code in {
                "invalid_response", "output_limit",
            }),
            (status, code),
        )

    def test_preflight_requires_exact_model_and_never_posts(self):
        calls = []

        def transport(method, path, payload, api_key):
            calls.append((method, path, payload, api_key))
            return {"data": [{"id": MODEL}]}

        self.assertEqual(preflight(KEY, transport), {"model": MODEL, "endpoint": ENDPOINT})
        self.assertEqual(calls, [("GET", "models", None, KEY)])
        with self.assertRaisesRegex(TokenFactoryError, "^catalog_missing$"):
            preflight(KEY, lambda *args: {"data": [{"id": "other"}]})
        with self.assertRaisesRegex(TokenFactoryError, "^invalid_response$"):
            preflight(KEY, lambda *args: {"data": "bad"})

    def test_preflight_maps_transport_failures_to_safe_codes(self):
        failures = [
            (TimeoutError(KEY), "timeout"),
            (urllib.error.HTTPError("secret", 401, KEY, {}, None),
             "authentication_failed"),
            (urllib.error.HTTPError("secret", 429, KEY, {}, None), "http_error"),
            (RuntimeError(KEY), "http_error"),
        ]
        for error, code in failures:
            with self.subTest(code=code):
                with self.assertRaisesRegex(TokenFactoryError, f"^{code}$") as caught:
                    preflight(KEY, lambda *args, error=error: (_ for _ in ()).throw(error))
                self.assertNotIn(KEY, str(caught.exception))

    def test_request_is_bounded_and_provenance_is_allowlisted(self):
        sent = []

        def transport(method, path, payload, api_key):
            sent.append((method, path, payload, api_key))
            return self.response()

        result = request_interpretation(PACKET, KEY, transport)
        self.assertEqual(result["response_json"], CONTENT)
        provenance = result["provenance"]
        self.assertEqual(provenance["request_status"], "completed")
        self.assertEqual(provenance["estimated_cost_usd"], 0.0000108)
        self.assertEqual(provenance["prompt_tokens"], 100)
        self.assertEqual(provenance["completion_tokens"], 20)
        self.assertEqual(provenance["reservation_usd"], 0.02)
        self.assertIsNone(provenance["billed_cost_usd"])
        self.assertEqual(set(provenance), {
            "source", "provider", "model", "endpoint", "created_at",
            "request_status", "error_code", "latency_seconds", "prompt_tokens",
            "completion_tokens", "estimated_cost_usd", "billed_cost_usd",
            "reservation_usd",
        })
        method, path, payload, key = sent[0]
        self.assertEqual((method, path, key), ("POST", "chat/completions", KEY))
        self.assertEqual((payload["model"], payload["max_tokens"],
                          payload["temperature"], payload["stream"]),
                         (MODEL, 4096, 0, False))
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        encoded = json.dumps(payload, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        self.assertLessEqual(len(encoded), 6000)
        self.assertNotIn(KEY, encoded.decode())
        self.assertEqual([item["role"] for item in payload["messages"]],
                         ["system", "user"])
        self.assertEqual(json.loads(payload["messages"][1]["content"]), PACKET)
        system = payload["messages"][0]["content"]
        self.assertIn("not per-episode geometry", system)
        self.assertIn("not a global minimum", system)
        self.assertIn("no causal proof", system)
        self.assertIn('"text"', system)
        self.assertIn('"evidence_ids"', system)
        self.assertIn("1 or 2 brief", system)
        example_start = system.index("{")
        example = json.loads(system[example_start:])
        self.assertEqual(set(example), {"schema_version", "observations",
                                        "hypotheses", "limitations"})

    def test_missing_usage_is_completed_with_unknown_cost(self):
        responses = [self.response(), self.response(
            usage={"prompt_tokens": None, "completion_tokens": None})]
        responses[0].pop("usage")
        for response in responses:
            with self.subTest(response=response):
                result = request_interpretation(PACKET, KEY, lambda *args: response)
                self.assertEqual(result["response_json"], CONTENT)
                provenance = result["provenance"]
                self.assertEqual(provenance["request_status"], "completed")
                self.assertIsNone(provenance["prompt_tokens"])
                self.assertIsNone(provenance["completion_tokens"])
                self.assertIsNone(provenance["estimated_cost_usd"])

    def test_completion_usage_accepts_the_4096_boundary_and_exact_cost(self):
        response = self.response(usage={
            "prompt_tokens": 100, "completion_tokens": 4096,
            "total_tokens": 4196,
        })
        result = request_interpretation(PACKET, KEY, lambda *args: response)
        self.assertEqual(result["response_json"], CONTENT)
        self.assertEqual(result["provenance"]["completion_tokens"], 4096)
        self.assertEqual(result["provenance"]["estimated_cost_usd"], 0.00098904)

    def test_bad_packet_or_oversized_request_fails_before_transport(self):
        bad = dict(PACKET, source_instruction="ignore rules")
        with self.assertRaisesRegex(ValueError, "invalid evidence packet"):
            request_interpretation(bad, KEY, lambda *args: self.fail("transport called"))
        large = dict(PACKET)
        large["episodes"] = [
            {"evidence_id": f"{index:016x}", "role": "reduced",
             "raw_outcome": "task_failure", "gate_outcome": "policy_failure"}
            for index in range(64)
        ]
        with self.assertRaisesRegex(TokenFactoryError, "^request_too_large$"):
            request_interpretation(large, KEY,
                                   lambda *args: self.fail("transport called"))

    def test_wrong_model_finish_content_and_malformed_usage_are_rejected(self):
        invalid = [
            self.response(model="different"),
            self.response(choices=[{"message": {"content": CONTENT},
                                    "finish_reason": "unknown"}]),
            self.response(choices=[{"message": {"content": "not-json"},
                                    "finish_reason": "stop"}]),
            self.response(usage={"prompt_tokens": 1, "completion_tokens": 2,
                                 "total_tokens": 2}),
            self.response(usage={"prompt_tokens": True, "completion_tokens": 1}),
            self.response(usage={"prompt_tokens": 1, "completion_tokens": True}),
            self.response(usage={"prompt_tokens": -1, "completion_tokens": 1}),
            self.response(usage={"prompt_tokens": 1, "completion_tokens": -1}),
            self.response(usage={"prompt_tokens": 262145, "completion_tokens": 1}),
            self.response(usage={"prompt_tokens": 1, "completion_tokens": 4097}),
            self.response(usage={"prompt_tokens": None, "completion_tokens": 1}),
            self.response(usage={"prompt_tokens": 1, "completion_tokens": 1,
                                 "total_tokens": None}),
            self.response(usage={"prompt_tokens": 1, "completion_tokens": 1,
                                 "total_tokens": True}),
            self.response(usage={"prompt_tokens": 1, "completion_tokens": 1,
                                 "total_tokens": -1}),
            self.response(choices=[{"message": {"content": KEY},
                                    "finish_reason": "stop"}]),
        ]
        for response in invalid:
            with self.subTest(response=response):
                result = request_interpretation(PACKET, KEY, lambda *args: response)
                self.assert_safe_failure(result, "invalid_response", "invalid_response")

    def test_truncation_retains_trustworthy_usage_and_estimated_cost(self):
        response = self.response(
            choices=[{"message": {"content": KEY}, "finish_reason": "length"}],
            usage={"prompt_tokens": 100, "completion_tokens": 4096,
                   "total_tokens": 4196})
        result = request_interpretation(PACKET, KEY, lambda *args: response)
        self.assert_safe_failure(result, "invalid_response", "output_limit")
        provenance = result["provenance"]
        self.assertEqual(provenance["prompt_tokens"], 100)
        self.assertEqual(provenance["completion_tokens"], 4096)
        self.assertEqual(provenance["estimated_cost_usd"], 0.00098904)

    def test_output_limit_requires_exact_model_valid_usage_and_one_dict_choice(self):
        invalid = [
            self.response(model="different", choices=[{"finish_reason": "length"}]),
            self.response(usage={"prompt_tokens": 1, "completion_tokens": 4097},
                          choices=[{"finish_reason": "length"}]),
            self.response(choices=[]),
            self.response(choices=[{"finish_reason": "length"},
                                   {"finish_reason": "length"}]),
            self.response(choices=["length"]),
            self.response(choices=[{"finish_reason": 1}]),
        ]
        for response in invalid:
            with self.subTest(response=response):
                result = request_interpretation(PACKET, KEY, lambda *args: response)
                self.assert_safe_failure(result, "invalid_response", "invalid_response")

    def test_wrong_model_or_malformed_usage_does_not_claim_token_counts(self):
        responses = [
            self.response(model="different"),
            self.response(usage={"prompt_tokens": 1, "completion_tokens": 2,
                                 "total_tokens": 99}),
        ]
        for response in responses:
            with self.subTest(response=response):
                result = request_interpretation(PACKET, KEY, lambda *args: response)
                self.assert_safe_failure(result, "invalid_response", "invalid_response")
                self.assertIsNone(result["provenance"]["prompt_tokens"])
                self.assertIsNone(result["provenance"]["completion_tokens"])
                self.assertIsNone(result["provenance"]["estimated_cost_usd"])

    def test_http_timeout_and_other_transport_errors_are_sanitized_without_retry(self):
        failures = [
            (TimeoutError(KEY), "transport_error", "timeout"),
            (socket.timeout(KEY), "transport_error", "timeout"),
            (urllib.error.HTTPError("secret", 403, KEY, {}, None),
             "http_error", "authentication_failed"),
            (urllib.error.HTTPError("secret", 500, KEY, {}, None),
             "http_error", "http_error"),
            (RuntimeError(KEY), "http_error", "http_error"),
        ]
        for error, status, code in failures:
            with self.subTest(status=status, code=code):
                calls = 0

                def transport(*args):
                    nonlocal calls
                    calls += 1
                    raise error

                result = request_interpretation(PACKET, KEY, transport)
                self.assertEqual(calls, 1)
                self.assert_safe_failure(result, status, code)

    def test_transport_invalid_response_keeps_matching_status_pair(self):
        result = request_interpretation(
            PACKET, KEY,
            lambda *args: (_ for _ in ()).throw(TokenFactoryError("invalid_response")))
        self.assert_safe_failure(result, "invalid_response", "invalid_response")

    def test_post_maps_every_fixed_client_error_to_store_compatible_provenance(self):
        expected = {
            "missing_api_key": ("http_error", "http_error"),
            "invalid_api_key": ("http_error", "http_error"),
            "authentication_failed": ("http_error", "authentication_failed"),
            "catalog_missing": ("http_error", "catalog_missing"),
            "timeout": ("transport_error", "timeout"),
            "http_error": ("http_error", "http_error"),
            "invalid_response": ("invalid_response", "invalid_response"),
            "output_limit": ("http_error", "http_error"),
            "request_too_large": ("http_error", "http_error"),
            "invalid_reservation": ("http_error", "http_error"),
            "reservation_exists": ("http_error", "http_error"),
            "unsafe_pilot_path": ("http_error", "http_error"),
        }
        for raised_code, (status, stored_code) in expected.items():
            with self.subTest(raised_code=raised_code):
                result = request_interpretation(
                    PACKET, KEY,
                    lambda *args, code=raised_code: (_ for _ in ()).throw(
                        TokenFactoryError(code)))
                self.assert_safe_failure(result, status, stored_code)
                self.assert_store_compatible_provenance(result["provenance"])

    def test_valid_structured_response_containing_secret_is_rejected(self):
        secret_content = json.dumps({
            "schema_version": 1,
            "observations": [{"text": KEY,
                              "evidence_ids": ["0123456789abcdef"]}],
            "hypotheses": [],
            "limitations": [],
        }, separators=(",", ":"))
        for content in (secret_content,
                        secret_content.replace("TEST", "\\u0054EST")):
            with self.subTest(content=content):
                result = request_interpretation(
                    PACKET, KEY,
                    lambda *args, content=content: self.response(
                        choices=[{"message": {"content": content},
                                  "finish_reason": "stop"}]))
                self.assert_safe_failure(result, "invalid_response", "invalid_response")

    def test_default_transport_uses_exact_tls_host_paths_and_no_proxy(self):
        _Connection.instances = []
        _Connection.response = _Response(json.dumps({"data": [{"id": MODEL}]}).encode())
        with patch("robot_debug.token_factory.http.client.HTTPSConnection", _Connection), \
                patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.invalid:9999"}):
            self.assertEqual(preflight(KEY), {"model": MODEL, "endpoint": ENDPOINT})
        self.assertEqual(len(_Connection.instances), 1)
        connection = _Connection.instances[0]
        self.assertEqual(connection.host, "api.tokenfactory.nebius.com")
        self.assertEqual(connection.timeout, 90)
        self.assertIsNotNone(connection.context)
        self.assertTrue(connection.context.check_hostname)
        self.assertEqual(connection.context.verify_mode, 2)
        self.assertEqual(connection.calls[0][0:2], ("GET", "/v1/models"))
        self.assertEqual(connection.calls[0][3]["Authorization"], "Bearer " + KEY)
        self.assertTrue(connection.closed)

    def test_default_transport_refuses_redirects_and_caps_response_bytes(self):
        for status, body, expected in (
            (302, b"{}", "http_error"),
            (401, b"{}", "authentication_failed"),
            (403, b"{}", "authentication_failed"),
            (429, b"{}", "http_error"),
            (500, b"{}", "http_error"),
            (200, b"x" * 262145, "invalid_response"),
        ):
            with self.subTest(status=status):
                _Connection.instances = []
                _Connection.response = _Response(body, status)
                with patch("robot_debug.token_factory.http.client.HTTPSConnection",
                           _Connection):
                    with self.assertRaisesRegex(TokenFactoryError, f"^{expected}$"):
                        preflight(KEY)

    def test_default_transport_rejects_duplicate_and_nonfinite_json(self):
        bodies = [b'{"data":[],"data":[]}', b'{"data":NaN}',
                  b'{"data":[' + b"9" * 5000 + b"]}"]
        for body in bodies:
            with self.subTest(body=body):
                _Connection.instances = []
                _Connection.response = _Response(body)
                with patch("robot_debug.token_factory.http.client.HTTPSConnection",
                           _Connection):
                    with self.assertRaisesRegex(TokenFactoryError,
                                                "^invalid_response$"):
                        preflight(KEY)

    def test_load_api_key_uses_environment_or_explicit_safe_dotenv(self):
        with patch.dict(os.environ, {"NEBIUS_API_KEY": "environment-key"}, clear=True):
            self.assertEqual(load_api_key(), "environment-key")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(TokenFactoryError, "^missing_api_key$"):
                load_api_key()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selected.env"
            path.write_text("# comment\nNEBIUS_API_KEY='file-key'\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(load_api_key(path), "file-key")
            with patch.dict(os.environ, {"NEBIUS_API_KEY": "file-key"}, clear=True):
                self.assertEqual(load_api_key(path), "file-key")
            with patch.dict(os.environ, {"NEBIUS_API_KEY": "other"}, clear=True):
                with self.assertRaisesRegex(TokenFactoryError, "^invalid_api_key$"):
                    load_api_key(path)

    def test_load_api_key_accepts_lf_crlf_comments_and_ascii_spaces(self):
        contents = [
            b"  # comment\n  NEBIUS_API_KEY = fixture-key  \n",
            b"  # comment\r\n  export NEBIUS_API_KEY = \"fixture-key\"  \r\n",
        ]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ, {}, clear=True):
            path = Path(tmp) / "selected.env"
            for content in contents:
                with self.subTest(content=content):
                    path.write_bytes(content)
                    self.assertEqual(load_api_key(path), "fixture-key")

    def test_load_api_key_rejects_unsafe_files_and_values(self):
        cases = [
            "NEBIUS_API_KEY=one\nNEBIUS_API_KEY=two\n",
            'NEBIUS_API_KEY="unterminated\n',
            'NEBIUS_API_KEY=fixture"tail\n',
            "NEBIUS_API_KEY=fixture'tail\n",
            "NEBIUS_API_KEY=bad\x01value\n",
            "NEBIUS_API_KEY=fixture\x1chidden\n",
            "NEBIUS_API_KEY=fixture\u0085hidden\n",
            "NEBIUS_API_KEY=fixture\u2028hidden\n",
            "NEBIUS_API_KEY=\n",
        ]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            path = Path(tmp) / "selected.env"
            for content in cases:
                with self.subTest(content=repr(content)):
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(TokenFactoryError, "^invalid_api_key$"):
                        load_api_key(path)
            path.write_text("NEBIUS_API_KEY=$EXPANDED\n", encoding="utf-8")
            self.assertEqual(load_api_key(path), "$EXPANDED")
            path.write_bytes(b"#" * 65537)
            with self.assertRaisesRegex(TokenFactoryError, "^invalid_api_key$"):
                load_api_key(path)
            target = Path(tmp) / "target.env"
            target.write_text("NEBIUS_API_KEY=value\n", encoding="utf-8")
            link = Path(tmp) / "link.env"
            try:
                link.symlink_to(target)
            except OSError:
                pass
            else:
                with self.assertRaisesRegex(TokenFactoryError, "^invalid_api_key$"):
                    load_api_key(link)

    def test_load_api_key_sanitizes_malformed_unicode_and_dotdot_paths(self):
        # POSIX rejects lone surrogates before our loader can inspect them.
        # Inject the mapping itself to exercise loader validation on every OS.
        with patch("robot_debug.token_factory.os.environ", {"NEBIUS_API_KEY": "bad\ud800key"}):
            with self.assertRaisesRegex(TokenFactoryError, "^invalid_api_key$"):
                load_api_key()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            parent = Path(tmp)
            (parent / "unused").mkdir()
            (parent / "selected.env").write_text(
                "NEBIUS_API_KEY=value\n", encoding="utf-8")
            traversing = parent / "unused" / ".." / "selected.env"
            with self.assertRaisesRegex(TokenFactoryError, "^invalid_api_key$"):
                load_api_key(traversing)

    def test_reservation_is_exclusive_exact_and_survives_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pilot"
            case_id = "a" * 64
            packet_id = packet_identity(PACKET)
            first = reserve_pilot(root, case_id, packet_id)
            self.assertEqual(first, {
                "schema_version": 1, "reservation_usd": 0.02,
                "attempt_number": 1, "case_id": case_id,
                "packet_id": packet_id, "model": MODEL,
            })
            self.assertEqual(json.loads((root / "reservation.json").read_text(
                encoding="utf-8")), first)
            with self.assertRaisesRegex(TokenFactoryError, "^reservation_exists$"):
                reserve_pilot(root, case_id, packet_id)
            (root / "reservation.json").write_text("broken", encoding="utf-8")
            with self.assertRaisesRegex(TokenFactoryError, "^reservation_exists$"):
                reserve_pilot(root, case_id, packet_id)

    def test_reservation_race_allows_exactly_one_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pilot"
            barrier = threading.Barrier(8)

            def reserve(_):
                barrier.wait()
                try:
                    reserve_pilot(root, "b" * 64, packet_identity(PACKET))
                except TokenFactoryError as exc:
                    return str(exc)
                return "ok"

            with ThreadPoolExecutor(max_workers=8) as executor:
                outcomes = list(executor.map(reserve, range(8)))
            self.assertEqual(outcomes.count("ok"), 1)
            self.assertEqual(outcomes.count("reservation_exists"), 7)

    def test_reservation_rejects_bad_ids_and_symlink_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            for case_id, packet_id in (("A" * 64, "b" * 64),
                                       ("a" * 64, "not-a-hash")):
                with self.subTest(case_id=case_id, packet_id=packet_id):
                    with self.assertRaisesRegex(TokenFactoryError,
                                                "^invalid_reservation$"):
                        reserve_pilot(parent / "pilot", case_id, packet_id)
            target = parent / "target"
            target.mkdir()
            link = parent / "linked"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                pass
            else:
                with self.assertRaisesRegex(TokenFactoryError,
                                            "^unsafe_pilot_path$"):
                    reserve_pilot(link, "a" * 64, "b" * 64)
            with self.assertRaisesRegex(TokenFactoryError,
                                        "^invalid_reservation$"):
                reserve_pilot(parent / "pilot", None, "b" * 64)
            with self.assertRaisesRegex(TokenFactoryError,
                                        "^invalid_reservation$"):
                reserve_pilot(parent / "pilot", "a" * 64, 1)
            with self.assertRaisesRegex(TokenFactoryError,
                                        "^unsafe_pilot_path$"):
                reserve_pilot(parent / "unused" / ".." / "pilot",
                              "a" * 64, "b" * 64)

    def test_reservation_persists_when_transport_is_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pilot"
            reserve_pilot(root, "a" * 64, packet_identity(PACKET))
            result = request_interpretation(
                PACKET, KEY, lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
            self.assert_safe_failure(result, "http_error", "http_error")
            self.assertTrue((root / "reservation.json").exists())
            with self.assertRaisesRegex(TokenFactoryError, "^reservation_exists$"):
                reserve_pilot(root, "a" * 64, packet_identity(PACKET))


if __name__ == "__main__":
    unittest.main()
