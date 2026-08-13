from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import app.services.billing.manager as manager
import app.services.billing.robokassa as robokassa
import app.services.billing.state as state
from app.models.venue_billing_transaction import VenueBillingTransaction


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for idx, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                setattr(obj, "id", idx)


class BillingStateTests(TestCase):
    def test_snapshot_transitions_active_grace_suspended(self):
        now = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
        paid_until = now + timedelta(days=2)
        snap_active = state.build_billing_snapshot(paid_until=paid_until, grace_until=None, now=now)
        self.assertEqual(snap_active.status, state.BILLING_STATUS_ACTIVE)

        snap_grace = state.build_billing_snapshot(
            paid_until=now - timedelta(hours=1),
            grace_until=now + timedelta(days=2),
            now=now,
        )
        self.assertEqual(snap_grace.status, state.BILLING_STATUS_GRACE)
        self.assertTrue(snap_grace.is_overdue)

        snap_suspended = state.build_billing_snapshot(
            paid_until=now - timedelta(days=5),
            grace_until=now - timedelta(days=1),
            now=now,
        )
        self.assertEqual(snap_suspended.status, state.BILLING_STATUS_SUSPENDED)
        self.assertTrue(snap_suspended.is_overdue)

    def test_build_checkout_url_uses_successurl2_and_failurl2(self):
        url = robokassa.build_checkout_url(
            merchant_login="demo",
            out_sum="2990.000000",
            invoice_id="123",
            description="Axelio",
            password1="pass1",
            algorithm="MD5",
            payment_url="https://auth.robokassa.ru/Merchant/Index.aspx",
            result_url="https://api.axelio.ru/billing/robokassa/result",
            success_url="https://api.axelio.ru/billing/robokassa/success",
            fail_url="https://api.axelio.ru/billing/robokassa/fail",
            extra_params={"Shp_tx": "123", "Shp_venueId": "77"},
            test_mode=True,
            expiration_date="2026-04-02T14:00",
        )
        query = parse_qs(urlparse(url).query)
        self.assertIn("SuccessUrl2", query)
        self.assertIn("FailUrl2", query)
        self.assertIn("SuccessUrl2Method", query)
        self.assertIn("FailUrl2Method", query)
        self.assertNotIn("SuccessURL", query)
        self.assertNotIn("FailURL", query)
        self.assertEqual(query["IsTest"][0], "1")
        self.assertEqual(query["ExpirationDate"][0], "2026-04-02T14:00")


class BillingManagerTests(TestCase):
    def test_extend_from_future_paid_until(self):
        fake_db = _FakeSession()
        now = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
        future_paid_until = now + timedelta(days=10)
        billing_state = SimpleNamespace(
            venue_id=55,
            status="ACTIVE",
            paid_until=future_paid_until,
            grace_until=future_paid_until + timedelta(days=3),
            last_payment_at=None,
            next_payment_due_at=future_paid_until,
            provider="ROBOKASSA",
            updated_at=now,
        )

        with (
            patch.object(manager, "utcnow", return_value=now),
            patch.object(manager, "get_or_create_billing_state", return_value=billing_state),
        ):
            state_obj, tx, event = manager.extend_venue_billing(
                fake_db,
                venue_id=55,
                days=30,
                created_by_user_id=7,
                comment="manual",
            )

        self.assertIs(state_obj, billing_state)
        self.assertEqual(tx.period_from, future_paid_until)
        self.assertEqual(tx.period_until, future_paid_until + timedelta(days=30))
        self.assertEqual(billing_state.paid_until, future_paid_until + timedelta(days=30))
        self.assertEqual(event.meta_json.get("transaction_id"), tx.id)

    def test_apply_checkout_payment_success_is_idempotent(self):
        fake_db = _FakeSession()
        now = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
        billing_state = SimpleNamespace(
            venue_id=11,
            status="GRACE",
            paid_until=now - timedelta(days=1),
            grace_until=now + timedelta(days=2),
            last_payment_at=None,
            next_payment_due_at=now - timedelta(days=1),
            provider="ROBOKASSA",
            updated_at=now,
        )
        tx = VenueBillingTransaction(
            venue_id=11,
            source="ROBOKASSA",
            type="PAYMENT",
            status="PENDING",
            amount_minor=299000,
            days_added=30,
            provider_invoice_id="123",
            provider_payload_json={},
            created_by_user_id=99,
            created_at=now - timedelta(minutes=5),
            updated_at=now - timedelta(minutes=5),
        )
        tx.id = 123

        with (
            patch.object(manager, "utcnow", return_value=now),
            patch.object(manager, "get_or_create_billing_state", return_value=billing_state),
        ):
            state_after_first, tx_after_first, event_first, applied_first = manager.apply_checkout_payment_success(
                fake_db,
                transaction=tx,
                provider_payment_id="rk-1",
                provider_payload_json={"source": "result"},
                amount_minor=299000,
            )
            state_after_second, tx_after_second, event_second, applied_second = manager.apply_checkout_payment_success(
                fake_db,
                transaction=tx_after_first,
                provider_payment_id="rk-1",
                provider_payload_json={"source": "result"},
                amount_minor=299000,
            )

        self.assertTrue(applied_first)
        self.assertFalse(applied_second)
        self.assertIsNotNone(event_first)
        self.assertIsNone(event_second)
        self.assertEqual(tx_after_first.status, "SUCCEEDED")
        self.assertEqual(tx_after_first.period_until, now + timedelta(days=30))
        self.assertEqual(state_after_first.paid_until, now + timedelta(days=30))
        self.assertIs(state_after_second, billing_state)
        self.assertIs(tx_after_second, tx_after_first)
