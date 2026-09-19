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
