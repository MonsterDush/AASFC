from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from app.services import signed_links


class SignedLinksTests(TestCase):
    def test_round_trip_adds_expiry_and_preserves_payload(self):
        with patch.object(signed_links.settings, "EXPORT_LINK_SECRET", "export-secret"), \
             patch("app.services.signed_links.time.time", return_value=1_000):
            token = signed_links.make_signed_token({"venue_id": 7, "format": "xlsx"}, ttl_seconds=60)
            payload = signed_links.verify_signed_token(token)

        self.assertEqual(payload, {"venue_id": 7, "format": "xlsx", "exp": 1_060})
        self.assertEqual(token.count("."), 1)
        self.assertNotIn("=", token)

    def test_default_secret_and_ttl_are_used(self):
        with patch.object(signed_links.settings, "EXPORT_LINK_SECRET", ""), \
             patch.object(signed_links.settings, "JWT_SECRET", "jwt-fallback"), \
             patch.object(signed_links.settings, "EXPORT_LINK_TTL_SECONDS", 30), \
             patch("app.services.signed_links.time.time", return_value=2_000):
            token = signed_links.make_signed_token({"report_id": 9})
            payload = signed_links.verify_signed_token(token)

        self.assertEqual(payload["exp"], 2_030)
        self.assertEqual(payload["report_id"], 9)

    def test_non_positive_explicit_ttl_is_clamped(self):
        with patch.object(signed_links.settings, "EXPORT_LINK_SECRET", "secret"), \
             patch("app.services.signed_links.time.time", return_value=3_000):
            token = signed_links.make_signed_token({}, ttl_seconds=-20)
            payload = signed_links.verify_signed_token(token)

        self.assertEqual(payload["exp"], 3_001)

    def test_tampered_signature_is_rejected(self):
        with patch.object(signed_links.settings, "EXPORT_LINK_SECRET", "secret"), \
             patch("app.services.signed_links.time.time", return_value=4_000):
            token = signed_links.make_signed_token({"venue_id": 5}, ttl_seconds=10)
            body, _ = token.split(".", 1)
            tampered = f"{body}.{signed_links._b64url_encode(b'x' * 32)}"

            with self.assertRaisesRegex(ValueError, "bad signature"):
                signed_links.verify_signed_token(tampered)

    def test_expired_token_is_rejected_but_boundary_is_valid(self):
        with patch.object(signed_links.settings, "EXPORT_LINK_SECRET", "secret"):
            with patch("app.services.signed_links.time.time", return_value=5_000):
                token = signed_links.make_signed_token({}, ttl_seconds=5)

            with patch("app.services.signed_links.time.time", return_value=5_005):
                self.assertEqual(signed_links.verify_signed_token(token)["exp"], 5_005)
            with patch("app.services.signed_links.time.time", return_value=5_006):
                with self.assertRaisesRegex(ValueError, "expired"):
                    signed_links.verify_signed_token(token)

    def test_malformed_token_is_rejected(self):
        for token in ("", "missing-separator"):
            with self.subTest(token=token):
                with self.assertRaisesRegex(ValueError, "bad token"):
                    signed_links.verify_signed_token(token)
