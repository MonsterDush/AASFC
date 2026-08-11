from __future__ import annotations

import asyncio
import json
import logging
from io import StringIO
from unittest import TestCase
from unittest.mock import patch

from starlette.requests import Request
from starlette.responses import Response

from app.core import observability


def _request(*, request_id: str | None = None, venue_id: str | None = None) -> Request:
    headers = []
    if request_id is not None:
        headers.append((b"x-request-id", request_id.encode("utf-8")))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/venues/7/summary",
        "raw_path": b"/venues/7/summary",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 9001),
        "root_path": "",
        "path_params": {"venue_id": venue_id} if venue_id is not None else {},
    }
    return Request(scope)


class RequestIdTests(TestCase):
    def test_normalize_request_id_accepts_safe_value_and_replaces_unsafe_input(self):
        self.assertEqual(observability.normalize_request_id("edge-123:abc"), "edge-123:abc")
        generated = observability.normalize_request_id("bad request id\nforged")
        self.assertRegex(generated, r"^[0-9a-f]{32}$")

    def test_observe_request_returns_request_id_and_records_request_fields(self):
        request = _request(request_id="edge-123", venue_id="7")

        async def call_next(_request: Request) -> Response:
            return Response(status_code=204)

        with patch.object(logging.getLogger("axelio.request"), "info") as info:
            response = asyncio.run(observability.observe_request(request, call_next))

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["X-Request-ID"], "edge-123")
        fields = info.call_args.kwargs["extra"]
        self.assertEqual(fields["status_code"], 204)
        self.assertEqual(fields["venue_id"], 7)
        self.assertGreaterEqual(fields["duration_ms"], 0)


class StructuredLoggingTests(TestCase):
    def test_json_formatter_emits_context_and_request_fields(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(observability.RequestContextFilter())
        handler.setFormatter(observability.JsonFormatter())
        logger = logging.getLogger("axelio.test.observability")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)

        logger.info(
            "request_complete",
            extra={"method": "GET", "route": "/health", "status_code": 200, "duration_ms": 1.25},
        )
        payload = json.loads(stream.getvalue())

        self.assertEqual(payload["message"], "request_complete")
        self.assertEqual(payload["method"], "GET")
        self.assertEqual(payload["route"], "/health")
        self.assertEqual(payload["status_code"], 200)
        self.assertIn("environment", payload)
        self.assertIn("release", payload)
        self.assertIn("request_id", payload)


class ErrorTrackingTests(TestCase):
    def test_sentry_scrubber_removes_credentials_payload_and_user(self):
        event = {
            "request": {
                "headers": {
                    "Authorization": "Bearer secret",
                    "Cookie": "session=secret",
                    "Accept": "application/json",
                },
                "cookies": {"session": "secret"},
                "data": {"password": "secret"},
            },
            "user": {"email": "person@example.com"},
        }

        scrubbed = observability._scrub_sentry_event(event, {})

        self.assertEqual(scrubbed["request"]["headers"], {"Accept": "application/json"})
        self.assertNotIn("cookies", scrubbed["request"])
        self.assertNotIn("data", scrubbed["request"])
        self.assertNotIn("user", scrubbed)

    def test_sentry_is_optional_and_uses_release_without_default_pii(self):
        with patch.object(observability.settings, "SENTRY_DSN", ""):
            self.assertFalse(observability.init_error_tracking())

        with (
            patch.object(observability.settings, "SENTRY_DSN", "https://public@example.invalid/1"),
            patch.object(observability.settings, "SENTRY_TRACES_SAMPLE_RATE", 0.25),
            patch.object(observability.settings, "APP_ENV", "test"),
            patch.object(observability.settings, "RELEASE_VERSION", "abc123"),
            patch.object(observability.sentry_sdk, "init") as sentry_init,
        ):
            self.assertTrue(observability.init_error_tracking())

        options = sentry_init.call_args.kwargs
        self.assertEqual(options["environment"], "test")
        self.assertEqual(options["release"], "axelio@abc123")
        self.assertEqual(options["traces_sample_rate"], 0.25)
        self.assertFalse(options["send_default_pii"])


if __name__ == "__main__":
    import unittest

    unittest.main()
