from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException

from app.routers import me
import app.services.billing.access as access
import app.services.billing.manager as manager
from app.models.venue_billing_transaction import VenueBillingTransaction


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, member_role: str | None = None):
        self.member_role = member_role
        self.added = []

    def execute(self, stmt):
        return _ScalarResult(self.member_role)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for idx, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                setattr(obj, "id", idx)


class BillingAccessTests(TestCase):
    def test_permissions_reject_missing_venue_before_creating_billing_state(self):
        fake_db = _FakeSession(member_role=None)
        user = SimpleNamespace(id=10, system_role="NONE")

        with patch.object(me, "get_venue_billing_snapshot") as get_snapshot, \
             patch.object(me, "build_setup_summary") as build_summary:
            with self.assertRaises(HTTPException) as raised:
                me.my_venue_permissions(venue_id=999_999, db=fake_db, user=user)

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "Venue not found")
        get_snapshot.assert_not_called()
        build_summary.assert_not_called()
        self.assertEqual(fake_db.added, [])

    def test_owner_gets_readonly_on_grace(self):
        fake_db = _FakeSession(member_role="OWNER")
        user = SimpleNamespace(id=10, system_role="NONE")
        now = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
        state = SimpleNamespace(
            paid_until=now - timedelta(hours=2),
            grace_until=now + timedelta(days=2),
            status="ACTIVE",
        )
        with patch.object(access, "get_or_create_billing_state", return_value=state), patch.object(access, "utcnow", return_value=now):
            payload = access.get_user_billing_access(fake_db, venue_id=55, user=user, membership_role="OWNER")
        self.assertEqual(payload["billing_status"], "GRACE")
        self.assertEqual(payload["billing_access_mode"], access.BILLING_ACCESS_READONLY)
        self.assertTrue(payload["billing_restricted_reason"])

    def test_staff_is_denied_on_grace(self):
        fake_db = _FakeSession(member_role="STAFF")
        user = SimpleNamespace(id=11, system_role="NONE")
        now = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
        state = SimpleNamespace(
            paid_until=now - timedelta(hours=2),
            grace_until=now + timedelta(days=1),
            status="ACTIVE",
        )
        with patch.object(access, "get_or_create_billing_state", return_value=state), patch.object(access, "utcnow", return_value=now):
            payload = access.get_user_billing_access(fake_db, venue_id=99, user=user, membership_role="STAFF")
        self.assertEqual(payload["billing_status"], "GRACE")
        self.assertEqual(payload["billing_access_mode"], access.BILLING_ACCESS_DENIED)


class BillingJobsTests(TestCase):
    def test_expire_stale_pending_checkouts_marks_transaction_failed(self):
        fake_db = _FakeSession()
        now = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
        tx = VenueBillingTransaction(
            venue_id=77,
            source="ROBOKASSA",
            type="PAYMENT",
            status="PENDING",
            amount_minor=299000,
            days_added=30,
            provider_invoice_id="555",
            provider_payload_json={"checkout_expires_at": (now - timedelta(minutes=1)).isoformat()},
            created_by_user_id=5,
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
        )
        tx.id = 555

        class _Scalars:
            def __init__(self, values):
                self._values = values

            def all(self):
                return list(self._values)

        class _ExecResult:
            def __init__(self, values):
                self._values = values

            def scalars(self):
                return _Scalars(self._values)

        fake_db.execute = lambda stmt: _ExecResult([tx])

        with patch.object(manager, "utcnow", return_value=now):
            expired_count, events = manager.expire_stale_pending_checkouts(fake_db, now=now)

        self.assertEqual(expired_count, 1)
        self.assertEqual(tx.status, "FAILED")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "ROBOKASSA_PAYMENT_EXPIRED")

    def test_set_paid_until_sets_suspended_when_date_is_old(self):
        fake_db = _FakeSession()
        now = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
        state = SimpleNamespace(
            venue_id=123,
            status="ACTIVE",
            paid_until=now - timedelta(days=1),
            grace_until=now + timedelta(days=2),
            next_payment_due_at=now - timedelta(days=1),
            updated_at=now,
        )
        target_paid_until = now - timedelta(days=10)

        with patch.object(manager, "utcnow", return_value=now), patch.object(manager, "get_or_create_billing_state", return_value=state):
            state_after, tx, event = manager.set_venue_billing_paid_until(
                fake_db,
                venue_id=123,
                paid_until=target_paid_until,
                created_by_user_id=1,
                comment="force old",
                amount_minor=0,
            )

        self.assertEqual(state_after.status, "SUSPENDED")
        self.assertEqual(tx.type, "SET_PAID_UNTIL")
        self.assertEqual(event.new_status, "SUSPENDED")
