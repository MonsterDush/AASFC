from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException

from app.routers import venue_access
from app.services.billing import BILLING_ACCESS_FULL


class _QueryStub:
    def __init__(self, value):
        self.value = value

    def filter(self, *args):
        return self

    def one_or_none(self):
        return self.value


class _DbStub:
    def __init__(self, membership=None):
        self.membership = membership

    def query(self, model):
        return _QueryStub(self.membership)


class VenueAccessTests(TestCase):
    def test_system_admins_bypass_membership_lookup(self):
        db = SimpleNamespace()
        super_admin = SimpleNamespace(id=1, system_role="SUPER_ADMIN")
        moderator = SimpleNamespace(id=2, system_role="MODERATOR")

        self.assertTrue(venue_access.is_owner_or_super_admin(db, venue_id=5, user=super_admin))
        self.assertTrue(venue_access.is_active_member_or_admin(db, venue_id=5, user=moderator))

    def test_owner_requires_active_membership_and_full_billing_access(self):
        owner = SimpleNamespace(id=7, system_role="NONE")
        membership = SimpleNamespace(venue_role="OWNER")
        db = _DbStub(membership)

        with patch.object(
            venue_access, "get_user_billing_access", return_value={"billing_access_mode": BILLING_ACCESS_FULL}
        ):
            self.assertTrue(venue_access.is_owner_or_super_admin(db, venue_id=5, user=owner))
        with patch.object(venue_access, "get_user_billing_access", return_value={"billing_access_mode": "DENIED"}):
            self.assertFalse(venue_access.is_owner_or_super_admin(db, venue_id=5, user=owner))

    def test_restricted_member_keeps_billing_reason(self):
        user = SimpleNamespace(id=7, system_role="NONE")
        membership = SimpleNamespace(venue_role="STAFF")
        db = _DbStub(membership)

        with patch.object(
            venue_access,
            "get_user_billing_access",
            return_value={
                "billing_access_mode": "DENIED",
                "billing_restricted_reason": "subscription expired",
            },
        ):
            with self.assertRaises(HTTPException) as raised:
                venue_access.require_active_member_or_admin(db, venue_id=5, user=user)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail, "subscription expired")

    def test_active_member_boolean_and_guard_preserve_full_access(self):
        user = SimpleNamespace(id=7, system_role="NONE")
        membership = SimpleNamespace(venue_role="STAFF")
        db = _DbStub(membership)

        with patch.object(
            venue_access, "get_user_billing_access", return_value={"billing_access_mode": BILLING_ACCESS_FULL}
        ):
            self.assertTrue(venue_access.is_active_member_or_admin(db, venue_id=5, user=user))
            self.assertIsNone(venue_access.require_active_member_or_admin(db, venue_id=5, user=user))

    def test_missing_membership_is_denied(self):
        user = SimpleNamespace(id=7, system_role="NONE")
        db = _DbStub(None)

        self.assertFalse(venue_access.is_active_member_or_admin(db, venue_id=5, user=user))
        with self.assertRaises(HTTPException) as raised:
            venue_access.require_active_member_or_admin(db, venue_id=5, user=user)
        self.assertEqual(raised.exception.status_code, 403)

    def test_report_viewer_checks_all_supported_permissions(self):
        user = SimpleNamespace(id=7, system_role="NONE")
        denied = HTTPException(status_code=403, detail="Forbidden")

        with (
            patch.object(venue_access, "is_owner_or_super_admin", return_value=False),
            patch.object(
                venue_access, "require_venue_permission", side_effect=[denied, denied, None]
            ) as require_permission,
        ):
            self.assertTrue(venue_access.is_report_viewer(SimpleNamespace(), venue_id=5, user=user))

        self.assertEqual(require_permission.call_count, 3)
        self.assertEqual(require_permission.call_args.kwargs["permission_code"], "SHIFT_REPORT_EDIT")

    def test_revenue_viewer_denies_user_without_owner_or_permission_access(self):
        user = SimpleNamespace(id=7, system_role="NONE")
        with (
            patch.object(venue_access, "is_owner_or_super_admin", return_value=False),
            patch.object(venue_access, "require_venue_permission", side_effect=HTTPException(status_code=403)),
        ):
            with self.assertRaises(HTTPException) as raised:
                venue_access.require_revenue_viewer(SimpleNamespace(), venue_id=5, user=user)

        self.assertEqual(raised.exception.status_code, 403)
