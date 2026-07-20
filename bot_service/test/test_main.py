from __future__ import annotations

import asyncio
import socket
import urllib.parse
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastapi import HTTPException

from bot_service import main


class TelegramHelpersTests(TestCase):
    def test_payload_is_encoded_for_telegram_form_api(self):
        encoded = main._telegram_payload_to_form_bytes({
            "chat_id": 42,
            "disable_notification": True,
            "reply_markup": {"inline_keyboard": []},
            "empty": None,
        })

        parsed = urllib.parse.parse_qs(encoded.decode("utf-8"))
        self.assertEqual(parsed["chat_id"], ["42"])
        self.assertEqual(parsed["disable_notification"], ["true"])
        self.assertEqual(parsed["reply_markup"], ['{"inline_keyboard": []}'])
        self.assertNotIn("empty", parsed)

    def test_normalize_error_uses_retry_after_and_description(self):
        retryable, description = main._normalize_telegram_error(
            400,
            '{"description":"Too Many Requests","parameters":{"retry_after":3}}',
        )

        self.assertTrue(retryable)
        self.assertEqual(description, "Too Many Requests")

    def test_normalize_error_handles_empty_and_plain_text_body(self):
        self.assertEqual(main._normalize_telegram_error(503, None), (True, None))
        self.assertEqual(main._normalize_telegram_error(400, " bad request "), (False, "bad request"))

    def test_parse_api_response_handles_success_and_transport_failure(self):
        success = main._parse_telegram_api_response("sendMessage", 200, '{"ok":true,"result":{"message_id":7}}')
        failure = main._parse_telegram_api_response("sendMessage", None, "", curl_returncode=28)

        self.assertTrue(success["ok"])
        self.assertEqual(success["status_code"], 200)
        self.assertEqual(success["result"]["result"]["message_id"], 7)
        self.assertFalse(failure["ok"])
        self.assertTrue(failure["retryable"])
        self.assertIn("sendMessage", failure["error"])

    def test_transport_uses_curl_fallback_after_urllib_failure(self):
        urllib_result = {"ok": False, "retryable": True, "error": "timeout"}
        curl_result = {"ok": True, "retryable": False}

        with patch.dict("os.environ", {"TELEGRAM_API_TRANSPORT": "urllib", "TELEGRAM_API_CURL_FALLBACK": "1"}), \
             patch.object(main, "_telegram_api_post_urllib", return_value=urllib_result) as urllib_post, \
             patch.object(main, "_telegram_api_post_curl", return_value=curl_result) as curl_post:
            result = main._telegram_api_post("token", "sendMessage", {"chat_id": 1})

        self.assertIs(result, curl_result)
        urllib_post.assert_called_once()
        curl_post.assert_called_once()

    def test_transport_can_return_urllib_failure_without_fallback(self):
        urllib_result = {"ok": False, "retryable": True, "error": "timeout"}

        with patch.dict("os.environ", {"TELEGRAM_API_TRANSPORT": "urllib", "TELEGRAM_API_CURL_FALLBACK": "0"}), \
             patch.object(main, "_telegram_api_post_urllib", return_value=urllib_result), \
             patch.object(main, "_telegram_api_post_curl") as curl_post:
            result = main._telegram_api_post("token", "sendMessage", {})

        self.assertIs(result, urllib_result)
        curl_post.assert_not_called()

    def test_curl_transport_builds_request_and_parses_success(self):
        process = SimpleNamespace(
            returncode=0,
            stdout=b'{"ok":true,"result":{"message_id":8}}',
            stderr=b"",
        )
        with patch.dict("os.environ", {
            "TELEGRAM_FORCE_IPV4": "1",
            "TELEGRAM_API_TIMEOUT_SECONDS": "4",
            "TELEGRAM_API_CONNECT_TIMEOUT_SECONDS": "2",
        }), patch.object(main.subprocess, "run", return_value=process) as run:
            result = main._telegram_api_post_curl("token", "sendMessage", {"chat_id": 7})

        self.assertTrue(result["ok"])
        command = run.call_args.args[0]
        self.assertIn("-4", command)
        self.assertIn("https://api.telegram.org/bottoken/sendMessage", command)
        self.assertEqual(run.call_args.kwargs["input"], b"chat_id=7")

    def test_urllib_transport_parses_success(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = b'{"ok":true,"result":true}'

        with patch.object(main.urllib.request, "urlopen", return_value=response) as urlopen:
            result = main._telegram_api_post_urllib("token", "sendMessage", {"chat_id": 7})

        self.assertTrue(result["ok"])
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 7)

    def test_ipv4_resolver_is_forced_only_for_telegram(self):
        resolver = Mock(return_value=[("resolved",)])
        with patch.object(main, "_ORIGINAL_GETADDRINFO", resolver), \
             patch.dict("os.environ", {"TELEGRAM_FORCE_IPV4": "1"}):
            main._telegram_ipv4_getaddrinfo("api.telegram.org", 443)
            main._telegram_ipv4_getaddrinfo("example.test", 443)

        self.assertEqual(resolver.call_args_list[0].args[2], socket.AF_INET)
        self.assertEqual(resolver.call_args_list[1].args[2], 0)


class BotServiceEndpointTests(TestCase):
    def test_health(self):
        self.assertEqual(main.health(), {"ok": True})

    def test_proxy_rejects_bad_secret(self):
        request = SimpleNamespace(headers={"X-Bot-Secret": "wrong"})
        payload = main.TelegramApiIn(method="sendMessage", payload={})

        with patch.object(main, "BOT_SERVICE_SECRET", "expected"), \
             patch.object(main, "TG_BOT_TOKEN", "token"):
            with self.assertRaises(HTTPException) as raised:
                main.telegram_api_proxy(payload, request)

        self.assertEqual(raised.exception.status_code, 401)

    def test_proxy_requires_bot_token(self):
        request = SimpleNamespace(headers={})
        payload = main.TelegramApiIn(method="sendMessage", payload={})

        with patch.object(main, "BOT_SERVICE_SECRET", ""), patch.object(main, "TG_BOT_TOKEN", None):
            with self.assertRaises(HTTPException) as raised:
                main.telegram_api_proxy(payload, request)

        self.assertEqual(raised.exception.status_code, 500)

    def test_proxy_forwards_valid_request(self):
        request = SimpleNamespace(headers={"X-Bot-Secret": "expected"})
        payload = main.TelegramApiIn(method="sendMessage", payload={"chat_id": 7})
        expected = {"ok": True}

        with patch.object(main, "BOT_SERVICE_SECRET", "expected"), \
             patch.object(main, "TG_BOT_TOKEN", "token"), \
             patch.object(main, "_telegram_api_post", return_value=expected) as telegram_post:
            result = main.telegram_api_proxy(payload, request)

        self.assertIs(result, expected)
        telegram_post.assert_called_once_with("token", "sendMessage", {"chat_id": 7})

    def test_background_forwarder_logs_non_success_and_exceptions(self):
        with patch.object(main, "_forward_telegram_update_to_backend", return_value=(503, "unavailable")), \
             patch.object(main.log, "error") as log_error:
            main._forward_telegram_update_to_backend_background(b"{}")
        log_error.assert_called_once()

        with patch.object(main, "_forward_telegram_update_to_backend", side_effect=RuntimeError("boom")), \
             patch.object(main.log, "exception") as log_exception:
            main._forward_telegram_update_to_backend_background(b"{}")
        log_exception.assert_called_once()

    def test_forward_update_posts_json_and_propagates_secret(self):
        response = MagicMock()
        response.__enter__.return_value.status = 204
        response.__enter__.return_value.read.return_value = b""

        with patch.object(main.urllib.request, "urlopen", return_value=response) as urlopen:
            status, body = main._forward_telegram_update_to_backend(b'{"update_id":1}', secret_token="secret")

        self.assertEqual((status, body), (204, ""))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.data, b'{"update_id":1}')
        self.assertEqual(request.get_header("X-telegram-bot-api-secret-token"), "secret")

    def test_webhook_schedules_background_forwarding(self):
        class BackgroundTasksStub:
            def __init__(self):
                self.calls = []

            def add_task(self, func, *args, **kwargs):
                self.calls.append((func, args, kwargs))

        request = SimpleNamespace(headers={}, body=AsyncMock(return_value=b'{"update_id":1}'))
        background_tasks = BackgroundTasksStub()

        with patch.object(main, "TG_WEBHOOK_SECRET_TOKEN", ""):
            result = asyncio.run(main.telegram_webhook(request, background_tasks))

        self.assertIsNone(result)
        self.assertEqual(len(background_tasks.calls), 1)
        func, args, kwargs = background_tasks.calls[0]
        self.assertIs(func, main._forward_telegram_update_to_backend_background)
        self.assertEqual(args, (b'{"update_id":1}',))
        self.assertEqual(kwargs, {"secret_token": None})
