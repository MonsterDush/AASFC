from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from defusedxml.common import EntitiesForbidden

from app.services import sms_auth, tg_notify
from app.services.billing import refunds


class OutboundUrlSecurityTests(TestCase):
    def test_sms_provider_rejects_non_https_and_embedded_credentials(self):
        provider = sms_auth.SmsRuProvider()
        for url in ("http://sms.example/send", "https://user:secret@sms.example/send", "not-a-url"):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                provider._request_json(url, {"phone": "79990000000"})

    def test_bot_service_allows_https_and_loopback_http_only(self):
        self.assertEqual(tg_notify._validated_bot_service_url("https://bot.example/"), "https://bot.example")
        self.assertEqual(tg_notify._validated_bot_service_url("http://127.0.0.1:9002"), "http://127.0.0.1:9002")
        for url in ("http://bot.example", "ftp://bot.example", "https://user:secret@bot.example"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                tg_notify._validated_bot_service_url(url)

    def test_notification_fails_closed_before_requesting_an_unsafe_service_url(self):
        with (
            patch.object(tg_notify, "_bot_service_url", return_value="http://bot.example"),
            patch.object(tg_notify.urllib.request, "urlopen") as urlopen,
        ):
            result = tg_notify._send_via_bot_service(chat_id=7, text="test")

        self.assertFalse(result["ok"])
        self.assertFalse(result["retryable"])
        urlopen.assert_not_called()

    def test_blocked_telegram_recipient_is_classified_as_unreachable(self):
        self.assertTrue(
            tg_notify.recipient_is_unreachable(
                {
                    "ok": False,
                    "retryable": False,
                    "status_code": 403,
                    "error": "Forbidden: bot was blocked by the user",
                }
            )
        )
        self.assertFalse(
            tg_notify.recipient_is_unreachable(
                {
                    "ok": False,
                    "retryable": False,
                    "status_code": 400,
                    "error": "Bad Request: message is too long",
                }
            )
        )
        self.assertFalse(
            tg_notify.recipient_is_unreachable(
                {
                    "ok": False,
                    "retryable": True,
                    "status_code": 503,
                    "error": "Bad Gateway",
                }
            )
        )

    def test_safe_bot_service_failure_reason_is_preserved_and_classified(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = (
            b'{"ok":false,"retryable":false,"status_code":200,'
            b'"error":"Telegram request failed","failure_reason":"recipient_unreachable"}'
        )

        with (
            patch.dict(
                "os.environ",
                {"BOT_SERVICE_URL": "https://bot.example", "BOT_SERVICE_SECRET": "expected"},
            ),
            patch.object(tg_notify.urllib.request, "urlopen", return_value=response),
        ):
            result = tg_notify._send_via_bot_service(chat_id=7, text="test")

        self.assertEqual(result["failure_reason"], "recipient_unreachable")
        self.assertTrue(tg_notify.recipient_is_unreachable(result))


class RefundXmlSecurityTests(TestCase):
    def test_operation_info_rejects_external_entities(self):
        config = SimpleNamespace(
            is_enabled=True,
            merchant_login="merchant",
            password2="secret",
            opstate_url="https://payments.example/opstate",
            hash_algorithm="sha256",
            timeout_seconds=5,
        )
        response = MagicMock()
        response.text = '<!DOCTYPE data [<!ENTITY leak SYSTEM "file:///etc/passwd">]><data>&leak;</data>'

        with (
            patch.object(refunds, "get_robokassa_refund_config", return_value=config),
            patch.object(refunds, "_hash_value", return_value="signature"),
            patch.object(refunds.requests, "get", return_value=response),
            self.assertRaises(EntitiesForbidden),
        ):
            refunds.fetch_operation_info(invoice_id=1)
