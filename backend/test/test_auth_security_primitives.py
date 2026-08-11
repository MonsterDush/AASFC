from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import jwt
from fastapi import HTTPException

from app.auth import jwt_tokens, passwords


class PasswordPrimitiveTests(TestCase):
    def test_password_policy_requires_length_letter_and_digit(self):
        with patch.object(passwords.settings, "PASSWORD_MIN_LENGTH", 10):
            with self.assertRaisesRegex(HTTPException, "10 символов"):
                passwords.validate_new_password("Short1")
            with self.assertRaisesRegex(HTTPException, "хотя бы одну букву"):
                passwords.validate_new_password("1234567890")
            with self.assertRaisesRegex(HTTPException, "хотя бы одну цифру"):
                passwords.validate_new_password("OnlyLetters")
            self.assertEqual(passwords.validate_new_password("SafePass10"), "SafePass10")

    def test_hash_and_verify_password_reject_wrong_or_malformed_values(self):
        with patch.object(passwords.settings, "PASSWORD_PBKDF2_ITERATIONS", 1):
            encoded = passwords.hash_password("SafePass10")

        self.assertTrue(encoded.startswith(f"{passwords.PBKDF2_ALGORITHM}$120000$"))
        self.assertTrue(passwords.verify_password("SafePass10", encoded))
        self.assertFalse(passwords.verify_password("WrongPass10", encoded))
        self.assertFalse(passwords.verify_password("SafePass10", None))
        self.assertFalse(passwords.verify_password("SafePass10", "broken"))
        self.assertFalse(passwords.verify_password("SafePass10", encoded.replace("pbkdf2_sha256", "unknown", 1)))

    def test_has_and_set_password_preserve_first_set_time_and_rotate_sessions(self):
        first_set_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
        changed_at = datetime(2026, 8, 12, tzinfo=timezone.utc)
        user = SimpleNamespace(
            password_hash="",
            password_set_at=None,
            password_changed_at=None,
            session_version=2,
        )
        self.assertFalse(passwords.has_password(user))

        with (
            patch.object(passwords, "hash_password", return_value="encoded"),
            patch.object(passwords, "utcnow", return_value=first_set_at),
        ):
            passwords.set_password(user, "SafePass10")

        self.assertTrue(passwords.has_password(user))
        self.assertEqual(user.password_set_at, first_set_at)
        self.assertEqual(user.password_changed_at, first_set_at)
        self.assertEqual(user.session_version, 3)

        with (
            patch.object(passwords, "hash_password", return_value="encoded-2"),
            patch.object(passwords, "utcnow", return_value=changed_at),
        ):
            passwords.set_password(user, "OtherPass20", is_reset=True)

        self.assertEqual(user.password_set_at, first_set_at)
        self.assertEqual(user.password_changed_at, changed_at)
        self.assertEqual(user.password_hash, "encoded-2")
        self.assertEqual(user.session_version, 4)


class JwtPrimitiveTests(TestCase):
    def setUp(self):
        self.config = jwt_tokens.JwtConfig(
            secret="test-secret-with-at-least-32-bytes",
            issuer="axelio-test",
            audience="axelio-browser",
            ttl_seconds=60,
        )

    def test_access_token_round_trip_keeps_session_and_extra_claims(self):
        token = jwt_tokens.create_access_token(
            self.config,
            42,
            session_version=3,
            extra_claims={"demo_persona": "OWNER"},
        )
        payload = jwt_tokens.decode_access_token(self.config, token)

        self.assertEqual(payload["sub"], "42")
        self.assertEqual(payload["sv"], 3)
        self.assertEqual(payload["typ"], "access")
        self.assertEqual(payload["demo_persona"], "OWNER")

    def test_extra_claims_cannot_override_security_claims(self):
        with self.assertRaisesRegex(ValueError, "exp, sub"):
            jwt_tokens.create_access_token(
                self.config,
                42,
                extra_claims={"sub": "7", "exp": 9999999999},
            )

    def test_decode_rejects_expired_token_and_wrong_audience(self):
        expired_config = jwt_tokens.JwtConfig(
            secret=self.config.secret,
            issuer=self.config.issuer,
            audience=self.config.audience,
            ttl_seconds=-1,
        )
        expired = jwt_tokens.create_access_token(expired_config, 42)
        with self.assertRaises(jwt.ExpiredSignatureError):
            jwt_tokens.decode_access_token(expired_config, expired)

        valid = jwt_tokens.create_access_token(self.config, 42)
        wrong_audience = jwt_tokens.JwtConfig(
            secret=self.config.secret,
            issuer=self.config.issuer,
            audience="other-client",
            ttl_seconds=60,
        )
        with self.assertRaises(jwt.InvalidAudienceError):
            jwt_tokens.decode_access_token(wrong_audience, valid)


if __name__ == "__main__":
    import unittest

    unittest.main()
