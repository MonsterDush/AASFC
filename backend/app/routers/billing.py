from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_member import VenueMember
from app.services.billing import get_user_billing_access, get_or_create_billing_state, list_billing_transactions

router = APIRouter(prefix="/venues", tags=["billing"])


def _require_owner_or_admin_billing_access(db: Session, *, venue_id: int, user: User) -> str:
    if user.system_role in {"SUPER_ADMIN", "MODERATOR"}:
        return "SUPER_ADMIN"
    member = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.user_id == int(user.id),
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if member is None or str(member.venue_role or "").upper() != "OWNER":
        raise HTTPException(status_code=403, detail="Forbidden")
    return "OWNER"


@router.get("/{venue_id}/billing")
def get_venue_billing(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    role = _require_owner_or_admin_billing_access(db, venue_id=venue_id, user=user)
    venue = db.execute(select(Venue).where(Venue.id == int(venue_id))).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")

    state = get_or_create_billing_state(db, venue_id=int(venue_id))
    access = get_user_billing_access(db, venue_id=int(venue_id), user=user, membership_role=role)
    txs = list_billing_transactions(db, venue_id=int(venue_id), limit=10)

    return {
        "venue_id": int(venue.id),
        "venue_name": venue.name,
        "plan": {
            "code": state.plan_code,
            "price_minor": int(state.price_minor or 0),
            "currency": state.currency,
            "label": "Axelio · 2990 ₽ / 30 дней",
        },
        "provider": state.provider,
        "status": access.get("billing_status"),
        "billing_access_mode": access.get("billing_access_mode"),
        "paid_until": access.get("paid_until").isoformat() if access.get("paid_until") else None,
        "grace_until": access.get("grace_until").isoformat() if access.get("grace_until") else None,
        "last_payment_at": state.last_payment_at.isoformat() if state.last_payment_at else None,
        "next_payment_due_at": state.next_payment_due_at.isoformat() if state.next_payment_due_at else None,
        "auto_renew_enabled": bool(state.auto_renew_enabled),
        "can_extend": True,
        "billing_restricted_reason": access.get("billing_restricted_reason"),
        "transactions": [
            {
                "id": int(tx.id),
                "source": tx.source,
                "type": tx.type,
                "status": tx.status,
                "amount_minor": int(tx.amount_minor or 0),
                "days_added": int(tx.days_added or 0) if tx.days_added is not None else None,
                "period_from": tx.period_from.isoformat() if tx.period_from else None,
                "period_until": tx.period_until.isoformat() if tx.period_until else None,
                "provider_invoice_id": tx.provider_invoice_id,
                "provider_payment_id": tx.provider_payment_id,
                "comment": tx.comment,
                "created_at": tx.created_at.isoformat() if tx.created_at else None,
            }
            for tx in txs
        ],
    }
