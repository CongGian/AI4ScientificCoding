import base64
import hashlib
import hmac
import unittest

import httpx

from llm_proxy.app import (
    _capture_payload,
    _decode_sse,
    _extract_response_metadata,
    _forward_response_headers,
    validate_gateway_token,
)


class GatewayUnitTests(unittest.TestCase):
    def test_signed_token_validation(self):
        participant_id = "a" * 64
        signing_key = "test-signing-key"
        signed_value = f"v1.{participant_id}"
        signature = base64.urlsafe_b64encode(
            hmac.new(
                signing_key.encode(), signed_value.encode(), hashlib.sha256
            ).digest()
        ).decode().rstrip("=")

        self.assertEqual(
            validate_gateway_token(f"{signed_value}.{signature}", signing_key),
            participant_id,
        )

    def test_tampered_token_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_gateway_token(f"v1.{'a' * 64}.invalid", "test-signing-key")

    def test_capture_limit_is_explicit(self):
        payload, truncated = _capture_payload(
            b'{"prompt":"long-value"}', "application/json", 10, True
        )
        self.assertTrue(truncated)
        self.assertTrue(payload["_capture_truncated"])

    def test_sse_capture_and_usage(self):
        payload = _decode_sse(
            b'data: {"model":"test","choices":[{"delta":{"content":"hi"}}]}\n\n'
            b'data: {"model":"test","usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}\n\n'
            b'data: [DONE]\n\n'
        )
        self.assertEqual(len(payload["events"]), 2)
        self.assertEqual(
            _extract_response_metadata(payload), ("test", 2, 1, 3)
        )

    def test_invalid_compression_headers_are_not_forwarded(self):
        headers = httpx.Headers(
            {
                "content-type": "application/json",
                "content-length": "100",
                "content-encoding": "gzip",
                "x-upstream": "yes",
            }
        )
        forwarded = _forward_response_headers(headers)
        self.assertNotIn("content-length", forwarded)
        self.assertNotIn("content-encoding", forwarded)
        self.assertEqual(forwarded["x-upstream"], "yes")


if __name__ == "__main__":
    unittest.main()
