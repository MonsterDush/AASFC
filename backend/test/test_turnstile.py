from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services import turnstile


class TurnstileVerificationTests(TestCase):
    def _settings(self, **overrides):
        values = {
            "PUBLIC_LEAD_CAPTCHA_REQUIRED": True,
            "TURNSTILE_SECRET_KEY": "secret",
            "TURNSTILE_EXPECTED_ACTION": "public_lead",
            "TURNSTILE_TIMEOUT_SECONDS": 5.0,
            "turnstile_allowed_hostnames": lambda: {"axelio.ru", "www.axelio.ru"},
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_disabled_captcha_is_an_explicit_success(self):
        with patch.object(turnstile, "settings", self._settings(PUBLIC_LEAD_CAPTCHA_REQUIRED=False)):
            result = turnstile.verify_turnstile_token(token=None, remote_ip="203.0.113.5")
        self.assertTrue(result.success)
        self.assertEqual(result.reason, "disabled")

    def test_missing_oversized_and_unconfigured_tokens_fail_closed(self):
        with patch.object(turnstile, "settings", self._settings()):
            self.assertEqual(turnstile.verify_turnstile_token(token="", remote_ip=None).reason, "missing_token")
            self.assertEqual(
                turnstile.verify_turnstile_token(token="x" * 2049, remote_ip=None).reason,
                "token_too_long",
            )
        with patch.object(turnstile, "settings", self._settings(TURNSTILE_SECRET_KEY="")):
            self.assertEqual(turnstile.verify_turnstile_token(token="token", remote_ip=None).reason, "not_configured")

    def test_success_requires_matching_action_and_hostname(self):
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "success": True,
                "hostname": "axelio.ru",
                "action": "public_lead",
                "error-codes": [],
            },
        )
        with (
            patch.object(turnstile, "settings", self._settings()),
            patch.object(turnstile.requests, "post", return_value=response) as post,
        ):
            result = turnstile.verify_turnstile_token(token="valid-token", remote_ip="203.0.113.5")
        self.assertTrue(result.success)
        self.assertEqual(result.reason, "verified")
        sent = post.call_args.kwargs
        self.assertEqual(sent["data"]["remoteip"], "203.0.113.5")
        self.assertEqual(sent["data"]["response"], "valid-token")
        self.assertTrue(sent["data"]["idempotency_key"])

    def test_provider_failure_mismatch_and_network_error_are_rejected(self):
        cases = [
            ({"success": False, "error-codes": ["timeout-or-duplicate"]}, "challenge_failed"),
            ({"success": True, "hostname": "axelio.ru", "action": "other"}, "action_mismatch"),
            ({"success": True, "hostname": "attacker.example", "action": "public_lead"}, "hostname_mismatch"),
        ]
        for payload, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                response = SimpleNamespace(raise_for_status=lambda: None, json=lambda payload=payload: payload)
                with (
                    patch.object(turnstile, "settings", self._settings()),
                    patch.object(turnstile.requests, "post", return_value=response),
                ):
                    result = turnstile.verify_turnstile_token(token="token", remote_ip=None)
                self.assertFalse(result.success)
                self.assertEqual(result.reason, expected_reason)

        with (
            patch.object(turnstile, "settings", self._settings()),
            patch.object(turnstile.requests, "post", side_effect=turnstile.requests.Timeout("timeout")),
        ):
            result = turnstile.verify_turnstile_token(token="token", remote_ip=None)
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "verification_unavailable")
