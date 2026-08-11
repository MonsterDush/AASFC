from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.request_ip import resolve_client_ip
from app.core.security_headers import security_headers
from app import main
from app.models import SecurityRateLimit
from app.routers import auth_phone, public_leads
from app.routers.auth_schemas import PasswordLoginIn
from app.services.security_rate_limits import (
    RateLimitDecision,
    RateLimitPolicy,
    check_rate_limit,
    consume_rate_limit,
    register_rate_limit_failure,
    reset_rate_limit,
)


class SecurityRateLimitServiceTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        SecurityRateLimit.__table__.create(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
        self.policy = RateLimitPolicy(limit=2, window_seconds=60, block_seconds=120)

    def tearDown(self):
        self.engine.dispose()

    def test_consume_allows_limit_then_blocks_without_storing_raw_subject(self):
        with self.Session() as db:
            first = consume_rate_limit(
                db, scope="public-lead-ip", subject="203.0.113.7", policy=self.policy, now=self.now
            )
            second = consume_rate_limit(
                db, scope="public-lead-ip", subject="203.0.113.7", policy=self.policy, now=self.now
            )
            blocked = consume_rate_limit(
                db, scope="public-lead-ip", subject="203.0.113.7", policy=self.policy, now=self.now
            )
            db.commit()

            row = db.execute(select(SecurityRateLimit)).scalar_one()
            self.assertTrue(first.allowed)
            self.assertTrue(second.allowed)
            self.assertFalse(blocked.allowed)
            self.assertEqual(blocked.retry_after_seconds, 120)
            self.assertEqual(row.attempt_count, 2)
            self.assertNotIn("203.0.113.7", row.subject_hash)
            self.assertEqual(len(row.subject_hash), 64)

    def test_failed_attempts_block_at_threshold_and_reset_after_success(self):
        with self.Session() as db:
            first = register_rate_limit_failure(
                db, scope="password-login-account", subject="+79990000001", policy=self.policy, now=self.now
            )
            blocked = register_rate_limit_failure(
                db, scope="password-login-account", subject="+79990000001", policy=self.policy, now=self.now
            )
            current = check_rate_limit(
                db, scope="password-login-account", subject="+79990000001", policy=self.policy, now=self.now
            )
            self.assertTrue(first.allowed)
            self.assertFalse(blocked.allowed)
            self.assertFalse(current.allowed)

            reset_rate_limit(db, scope="password-login-account", subject="+79990000001")
            db.commit()
            allowed = check_rate_limit(
                db, scope="password-login-account", subject="+79990000001", policy=self.policy, now=self.now
            )
            self.assertTrue(allowed.allowed)

    def test_expired_window_starts_fresh(self):
        with self.Session() as db:
            consume_rate_limit(db, scope="public-lead-ip", subject="203.0.113.8", policy=self.policy, now=self.now)
            db.commit()
            decision = consume_rate_limit(
                db,
                scope="public-lead-ip",
                subject="203.0.113.8",
                policy=self.policy,
                now=self.now + timedelta(seconds=61),
            )
            self.assertTrue(decision.allowed)
            self.assertEqual(decision.remaining, 1)


class RequestIpTests(TestCase):
    def test_trusted_proxy_uses_first_forwarded_address(self):
        request = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            headers={"x-forwarded-for": "203.0.113.9, 127.0.0.1"},
        )
        self.assertEqual(resolve_client_ip(request), "203.0.113.9")

    def test_untrusted_peer_cannot_spoof_forwarded_address(self):
        request = SimpleNamespace(
            client=SimpleNamespace(host="198.51.100.4"),
            headers={"x-forwarded-for": "203.0.113.9"},
        )
        self.assertEqual(resolve_client_ip(request), "198.51.100.4")


class ProductionSecurityConfigurationTests(TestCase):
    def _settings(self, **overrides):
        values = {
            "_env_file": None,
            "database_url": "sqlite+pysqlite:///:memory:",
            "TG_BOT_TOKEN": "test-token",
            "JWT_SECRET": "test-secret",
            "APP_ENV": "production",
            "PHONE_AUTH_PROVIDER": "sms_ru",
            "PHONE_AUTH_DEBUG_REVEAL_CODE": False,
            "COOKIE_SECURE": True,
            "SENTRY_DSN": "https://public@example.invalid/1",
        }
        values.update(overrides)
        return Settings(**values)

    def test_production_rejects_debug_auth_and_insecure_cookie(self):
        with self.assertRaisesRegex(ValueError, "PHONE_AUTH_PROVIDER=debug"):
            self._settings(PHONE_AUTH_PROVIDER="debug")
        with self.assertRaisesRegex(ValueError, "PHONE_AUTH_DEBUG_REVEAL_CODE"):
            self._settings(PHONE_AUTH_DEBUG_REVEAL_CODE=True)
        with self.assertRaisesRegex(ValueError, "COOKIE_SECURE=false"):
            self._settings(COOKIE_SECURE=False)
        with self.assertRaisesRegex(ValueError, "SENTRY_DSN is required"):
            self._settings(SENTRY_DSN="")

    def test_sentry_trace_sample_rate_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            self._settings(SENTRY_TRACES_SAMPLE_RATE=1.5)

    def test_production_disables_openapi_surfaces(self):
        with patch.object(main.settings, "APP_ENV", "production"):
            self.assertEqual(
                main._fastapi_options(),
                {"docs_url": None, "redoc_url": None, "openapi_url": None},
            )

    def test_production_headers_include_transport_and_content_policy(self):
        headers = security_headers(production=True)
        self.assertIn("max-age=31536000", headers["Strict-Transport-Security"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")


class SecurityRateLimitRouterTests(TestCase):
    def test_password_login_stops_before_password_check_when_blocked(self):
        request = SimpleNamespace(client=SimpleNamespace(host="198.51.100.1"), headers={})
        db = MagicMock()
        with (
            patch.object(auth_phone, "check_rate_limit", return_value=RateLimitDecision(False, 90, 0)),
            patch.object(auth_phone, "find_user_by_phone") as find_user,
        ):
            with self.assertRaises(HTTPException) as raised:
                auth_phone.password_login(
                    PasswordLoginIn(phone="+79990000001", password="Wrong123"),
                    request,
                    MagicMock(),
                    db,
                )
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.headers["Retry-After"], "90")
        find_user.assert_not_called()

    def test_password_login_records_both_failed_subjects(self):
        request = SimpleNamespace(client=SimpleNamespace(host="198.51.100.2"), headers={})
        db = MagicMock()
        with (
            patch.object(auth_phone, "check_rate_limit", return_value=RateLimitDecision(True, 0, 1)),
            patch.object(auth_phone, "find_user_by_phone", return_value=None),
            patch.object(
                auth_phone, "register_rate_limit_failure", return_value=RateLimitDecision(True, 0, 1)
            ) as register,
        ):
            with self.assertRaises(HTTPException) as raised:
                auth_phone.password_login(
                    PasswordLoginIn(phone="+79990000001", password="Wrong123"),
                    request,
                    MagicMock(),
                    db,
                )
        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(register.call_count, 2)
        db.commit.assert_called_once()

    def test_public_lead_rate_limit_prevents_notification(self):
        request = SimpleNamespace(client=SimpleNamespace(host="198.51.100.3"), headers={})
        db = MagicMock()
        payload = public_leads.PublicLeadIn(name="Тест", phone="+79990000001")
        with (
            patch.object(public_leads, "consume_rate_limit", return_value=RateLimitDecision(False, 60, 0)),
            patch.object(public_leads.tg_notify, "notify_result") as notify,
        ):
            with self.assertRaises(HTTPException) as raised:
                public_leads.create_public_lead(payload, request, db)
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.headers["Retry-After"], "60")
        notify.assert_not_called()
        db.commit.assert_called_once()
