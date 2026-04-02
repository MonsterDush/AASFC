from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.guards import require_super_admin
from app.core.db import get_db
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_billing_transaction import VenueBillingTransaction
from app.models.venue_member import VenueMember
from app.services.billing import (
    extend_venue_billing,
    get_billing_snapshot_for_state,
    get_or_create_billing_state,
    list_billing_transactions,
    send_owner_billing_notification_once,
    set_venue_billing_paid_until,
)

router = APIRouter(prefix="/admin", tags=["admin-billing"])


class BillingExtendIn(BaseModel):
    days: int = Field(..., ge=1, le=3650)
    comment: str | None = Field(default=None, max_length=1000)
    amount_minor: int | None = Field(default=0, ge=0)


class BillingSetPaidUntilIn(BaseModel):
    paid_until: datetime
    comment: str | None = Field(default=None, max_length=1000)
    amount_minor: int | None = Field(default=0, ge=0)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _month_range_utc(target: date | None = None) -> tuple[datetime, datetime]:
    base = target or _utc_now().date()
    start = datetime.combine(date(base.year, base.month, 1), time.min, tzinfo=timezone.utc)
    if base.month == 12:
        end = datetime.combine(date(base.year + 1, 1, 1), time.min, tzinfo=timezone.utc)
    else:
        end = datetime.combine(date(base.year, base.month + 1, 1), time.min, tzinfo=timezone.utc)
    return start, end


def _load_owner_labels(db: Session, venue_ids: list[int]) -> dict[int, dict]:
    if not venue_ids:
        return {}
    rows = db.execute(
        select(VenueMember.venue_id, User.id, User.full_name, User.short_name, User.tg_username)
        .join(User, User.id == VenueMember.user_id)
        .where(
            VenueMember.venue_id.in_(venue_ids),
            VenueMember.is_active.is_(True),
            VenueMember.venue_role == "OWNER",
        )
        .order_by(VenueMember.venue_id.asc(), User.id.asc())
    ).all()
    out: dict[int, dict] = {}
    for row in rows:
        venue_id = int(row.venue_id)
        if venue_id in out:
            continue
        label = row.short_name or row.full_name or (f"@{str(row.tg_username).lstrip('@')}" if row.tg_username else None)
        out[venue_id] = {
            "user_id": int(row.id),
            "label": label,
            "tg_username": row.tg_username,
        }
    return out


@router.get("/billing/summary")
def get_admin_billing_summary(
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    venues = db.execute(select(Venue).order_by(Venue.id.asc())).scalars().all()
    now = _utc_now()
    month_start, month_end = _month_range_utc(now.date())

    active_count = 0
    grace_count = 0
    suspended_count = 0
    mrr_minor = 0
    due_soon_count = 0
    overdue_count = 0

    for venue in venues:
        state = get_or_create_billing_state(db, venue_id=int(venue.id))
        snapshot = get_billing_snapshot_for_state(state)
        status = snapshot.status
        if status == "ACTIVE":
            active_count += 1
            mrr_minor += int(state.price_minor or 0)
        elif status == "GRACE":
            grace_count += 1
            overdue_count += 1
        else:
            suspended_count += 1
            overdue_count += 1
        if snapshot.paid_until and snapshot.paid_until >= now and snapshot.paid_until <= now + timedelta(days=7):
            due_soon_count += 1

    tx_rows = db.execute(
        select(VenueBillingTransaction).where(
            VenueBillingTransaction.status == "SUCCEEDED",
            VenueBillingTransaction.created_at >= month_start,
            VenueBillingTransaction.created_at < month_end,
        )
    ).scalars().all()
    receipts_minor = sum(int(tx.amount_minor or 0) for tx in tx_rows)

    return {
        "totals": {
            "venues_total": len(venues),
            "active": active_count,
            "grace": grace_count,
            "suspended": suspended_count,
            "mrr_minor": int(mrr_minor),
            "receipts_current_month_minor": int(receipts_minor),
            "due_soon": due_soon_count,
            "overdue": overdue_count,
        },
        "period": {
            "month_start": month_start.isoformat(),
            "month_end": month_end.isoformat(),
        },
    }


@router.get("/billing/venues")
def get_admin_billing_venues(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    only_due_soon: bool = Query(default=False),
    only_overdue: bool = Query(default=False),
    include_archived: bool = Query(default=True),
    sort_by: str = Query(default="paid_until_asc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    stmt = select(Venue).order_by(Venue.id.desc())
    if not include_archived:
        stmt = stmt.where(Venue.is_archived.is_(False))
    if q:
        stmt = stmt.where(Venue.name.ilike(f"%{q.strip()}%"))
    venues = db.execute(stmt).scalars().all()
    owner_map = _load_owner_labels(db, [int(v.id) for v in venues])
    now = _utc_now()
    result = []
    normalized_status = str(status or "").strip().upper()

    for venue in venues:
        state = get_or_create_billing_state(db, venue_id=int(venue.id))
        snapshot = get_billing_snapshot_for_state(state)
        effective_status = snapshot.status
        if normalized_status and effective_status != normalized_status:
            continue
        if only_due_soon and not (snapshot.paid_until and now <= snapshot.paid_until <= now + timedelta(days=7)):
            continue
        if only_overdue and effective_status == "ACTIVE":
            continue

        txs = list_billing_transactions(db, venue_id=int(venue.id), limit=1)
        last_tx = txs[0] if txs else None
        owner = owner_map.get(int(venue.id)) or {}
        result.append({
            "venue_id": int(venue.id),
            "venue_name": venue.name,
            "is_archived": bool(venue.is_archived),
            "owner": owner,
            "status": effective_status,
            "paid_until": snapshot.paid_until.isoformat() if snapshot.paid_until else None,
            "grace_until": snapshot.grace_until.isoformat() if snapshot.grace_until else None,
            "last_payment_at": state.last_payment_at.isoformat() if state.last_payment_at else None,
            "next_payment_due_at": state.next_payment_due_at.isoformat() if state.next_payment_due_at else None,
            "last_extension_source": last_tx.source if last_tx else None,
            "last_extension_transaction": {
                "id": int(last_tx.id),
                "status": last_tx.status,
                "type": last_tx.type,
                "amount_minor": int(last_tx.amount_minor or 0),
                "days_added": int(last_tx.days_added or 0) if last_tx.days_added is not None else None,
                "created_at": last_tx.created_at.isoformat() if last_tx.created_at else None,
            } if last_tx else None,
        })

    def _date_value(value):
        if value is None:
            return datetime(1970, 1, 1, tzinfo=timezone.utc)
        if getattr(value, "tzinfo", None) is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    sort_key = str(sort_by or "paid_until_asc").strip().lower()
    if sort_key == "paid_until_desc":
        result.sort(key=lambda item: _date_value(item.get("paid_until") and datetime.fromisoformat(item["paid_until"])), reverse=True)
    elif sort_key == "last_payment_desc":
        result.sort(key=lambda item: _date_value(item.get("last_payment_at") and datetime.fromisoformat(item["last_payment_at"])), reverse=True)
    elif sort_key == "name_asc":
        result.sort(key=lambda item: str(item.get("venue_name") or "").lower())
    elif sort_key == "name_desc":
        result.sort(key=lambda item: str(item.get("venue_name") or "").lower(), reverse=True)
    else:
        result.sort(key=lambda item: _date_value(item.get("paid_until") and datetime.fromisoformat(item["paid_until"])))

    total = len(result)
    offset = (int(page) - 1) * int(page_size)
    paged = result[offset: offset + int(page_size)]

    return {
        "items": paged,
        "count": len(paged),
        "total": total,
        "page": int(page),
        "page_size": int(page_size),
        "sort_by": sort_key,
        "has_next": offset + int(page_size) < total,
    }


@router.post("/venues/{venue_id}/billing/extend")
def extend_admin_venue_billing(
    venue_id: int,
    payload: BillingExtendIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    venue = db.execute(select(Venue).where(Venue.id == int(venue_id))).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")

    state, tx, event = extend_venue_billing(
        db,
        venue_id=int(venue_id),
        days=int(payload.days),
        created_by_user_id=user.id,
        comment=payload.comment,
        amount_minor=int(payload.amount_minor or 0),
    )
    db.commit()
    db.refresh(state)
    db.refresh(tx)
    db.refresh(event)
    snapshot = get_billing_snapshot_for_state(state)

    paid_until_label = snapshot.paid_until.strftime("%d.%m.%Y") if snapshot.paid_until else "—"
    send_owner_billing_notification_once(
        db,
        venue_id=int(venue.id),
        notification_type="manual_extend",
        event_key=str(tx.id),
        text=f"Доступ по заведению «{venue.name}» продлён вручную на {int(payload.days)} дн. Новый срок оплаты — до {paid_until_label}.",
        button_text="Открыть заведение",
    )
    db.commit()

    return {
        "venue_id": int(venue.id),
        "venue_name": venue.name,
        "billing": {
            "status": snapshot.status,
            "paid_until": snapshot.paid_until.isoformat() if snapshot.paid_until else None,
            "grace_until": snapshot.grace_until.isoformat() if snapshot.grace_until else None,
            "next_payment_due_at": state.next_payment_due_at.isoformat() if state.next_payment_due_at else None,
        },
        "transaction": {
            "id": int(tx.id),
            "source": tx.source,
            "type": tx.type,
            "status": tx.status,
            "amount_minor": int(tx.amount_minor or 0),
            "days_added": int(tx.days_added or 0) if tx.days_added is not None else None,
            "period_from": tx.period_from.isoformat() if tx.period_from else None,
            "period_until": tx.period_until.isoformat() if tx.period_until else None,
            "comment": tx.comment,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
        },
        "event": {
            "id": int(event.id),
            "event_type": event.event_type,
            "old_status": event.old_status,
            "new_status": event.new_status,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        },
    }


@router.post("/venues/{venue_id}/billing/set-paid-until")
def set_admin_venue_billing_paid_until(
    venue_id: int,
    payload: BillingSetPaidUntilIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    venue = db.execute(select(Venue).where(Venue.id == int(venue_id))).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")

    state, tx, event = set_venue_billing_paid_until(
        db,
        venue_id=int(venue_id),
        paid_until=payload.paid_until,
        created_by_user_id=user.id,
        comment=payload.comment,
        amount_minor=int(payload.amount_minor or 0),
    )
    db.commit()
    db.refresh(state)
    db.refresh(tx)
    db.refresh(event)
    snapshot = get_billing_snapshot_for_state(state)

    paid_until_label = snapshot.paid_until.strftime("%d.%m.%Y") if snapshot.paid_until else "—"
    send_owner_billing_notification_once(
        db,
        venue_id=int(venue.id),
        notification_type="manual_set_paid_until",
        event_key=str(tx.id),
        text=f"Срок оплаты по заведению «{venue.name}» обновлён вручную. Новый paid until — {paid_until_label}.",
        button_text="Открыть заведение",
    )
    db.commit()

    return {
        "venue_id": int(venue.id),
        "venue_name": venue.name,
        "billing": {
            "status": snapshot.status,
            "paid_until": snapshot.paid_until.isoformat() if snapshot.paid_until else None,
            "grace_until": snapshot.grace_until.isoformat() if snapshot.grace_until else None,
            "next_payment_due_at": state.next_payment_due_at.isoformat() if state.next_payment_due_at else None,
        },
        "transaction": {
            "id": int(tx.id),
            "source": tx.source,
            "type": tx.type,
            "status": tx.status,
            "amount_minor": int(tx.amount_minor or 0),
            "period_from": tx.period_from.isoformat() if tx.period_from else None,
            "period_until": tx.period_until.isoformat() if tx.period_until else None,
            "comment": tx.comment,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
        },
        "event": {
            "id": int(event.id),
            "event_type": event.event_type,
            "old_status": event.old_status,
            "new_status": event.new_status,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        },
    }
