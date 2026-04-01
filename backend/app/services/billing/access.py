from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.venue_billing_state import VenueBillingState
from app.models.venue_member import VenueMember
from .manager import get_or_create_billing_state
from .state import BILLING_STATUS_ACTIVE, build_billing_snapshot, utcnow

BILLING_ACCESS_FULL = "FULL"
BILLING_ACCESS_READONLY = "BILLING_READONLY"
BILLING_ACCESS_DENIED = "DENIED"


def get_billing_snapshot_for_state(state: VenueBillingState | None):
    if state is None:
        return build_billing_snapshot(paid_until=None, grace_until=None, status=BILLING_STATUS_ACTIVE, now=utcnow())
    return build_billing_snapshot(
        paid_until=getattr(state, "paid_until", None),
        grace_until=getattr(state, "grace_until", None),
        status=getattr(state, "status", None),
        now=utcnow(),
    )


def get_venue_billing_snapshot(db: Session, *, venue_id: int):
    state = get_or_create_billing_state(db, venue_id=int(venue_id))
    return get_billing_snapshot_for_state(state)


def serialize_billing_snapshot(state: VenueBillingState | None) -> dict:
    snapshot = get_billing_snapshot_for_state(state)
    return {
        "billing_status": snapshot.status,
        "paid_until": snapshot.paid_until.isoformat() if snapshot.paid_until else None,
        "grace_until": snapshot.grace_until.isoformat() if snapshot.grace_until else None,
        "billing_restricted_reason": snapshot.restricted_reason,
        "billing_days_left": snapshot.days_left,
    }


def get_user_billing_access(db: Session, *, venue_id: int, user: User, membership_role: str | None = None) -> dict:
    state = get_or_create_billing_state(db, venue_id=int(venue_id))
    snapshot = get_billing_snapshot_for_state(state)

    if user.system_role in {"SUPER_ADMIN", "MODERATOR"}:
        return {
            "billing_status": snapshot.status,
            "billing_access_mode": BILLING_ACCESS_FULL,
            "paid_until": snapshot.paid_until,
            "grace_until": snapshot.grace_until,
            "billing_restricted_reason": None,
            "state": state,
        }

    role_upper = str(membership_role or "").upper()
    if not role_upper:
        vm = db.execute(
            select(VenueMember.venue_role).where(
                VenueMember.venue_id == int(venue_id),
                VenueMember.user_id == int(user.id),
                VenueMember.is_active.is_(True),
            )
        ).scalar_one_or_none()
        role_upper = str(vm or "").upper()

    if snapshot.status == BILLING_STATUS_ACTIVE:
        access_mode = BILLING_ACCESS_FULL
        reason = None
    elif role_upper == "OWNER":
        access_mode = BILLING_ACCESS_READONLY
        reason = snapshot.restricted_reason
    else:
        access_mode = BILLING_ACCESS_DENIED
        reason = snapshot.restricted_reason

    return {
        "billing_status": snapshot.status,
        "billing_access_mode": access_mode,
        "paid_until": snapshot.paid_until,
        "grace_until": snapshot.grace_until,
        "billing_restricted_reason": reason,
        "state": state,
    }
