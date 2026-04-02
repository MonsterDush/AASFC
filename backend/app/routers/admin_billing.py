from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.guards import require_super_admin
from app.core.db import get_db
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_billing_event import VenueBillingEvent
from app.models.venue_billing_transaction import VenueBillingTransaction
from app.models.venue_member import VenueMember
from app.services.billing import (
    create_refund_transaction,
    extend_venue_billing,
    get_billing_snapshot_for_state,
    get_checkout_expires_at,
    get_or_create_billing_state,
    list_billing_events,
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


class BillingRefundIn(BaseModel):
    amount_minor: int = Field(..., ge=1)
    comment: str | None = Field(default=None, max_length=1000)
    related_transaction_id: int | None = Field(default=None, ge=1)
    revoke_access_hint: bool = Field(default=False)


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


def _load_venue_map(db: Session, venue_ids: list[int]) -> dict[int, Venue]:
    if not venue_ids:
        return {}
    rows = db.execute(select(Venue).where(Venue.id.in_(venue_ids))).scalars().all()
    return {int(v.id): v for v in rows}


def _serialize_billing_transaction(tx: VenueBillingTransaction, *, venue_name: str | None = None, owner: dict | None = None) -> dict[str, Any]:
    payload = tx.provider_payload_json if isinstance(tx.provider_payload_json, dict) else (tx.provider_payload_json or {})
    return {
        "id": int(tx.id),
        "venue_id": int(tx.venue_id),
        "venue_name": venue_name,
        "owner": owner or {},
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
        "provider_payload_json": payload,
        "created_by_user_id": tx.created_by_user_id,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
        "updated_at": tx.updated_at.isoformat() if tx.updated_at else None,
    }


def _serialize_billing_event(event: VenueBillingEvent, *, venue_name: str | None = None, owner: dict | None = None) -> dict[str, Any]:
    meta = event.meta_json if isinstance(event.meta_json, dict) else (event.meta_json or {})
    return {
        "id": int(event.id),
        "venue_id": int(event.venue_id),
        "venue_name": venue_name,
        "owner": owner or {},
        "event_type": event.event_type,
        "old_status": event.old_status,
        "new_status": event.new_status,
        "meta": meta,
        "created_by_user_id": event.created_by_user_id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _to_datetime(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            base = datetime.fromisoformat(raw)
            if end_of_day:
                base = datetime.combine(base.date(), time.max)
        else:
            base = datetime.fromisoformat(raw)
    except Exception:
        return None
    if base.tzinfo is None:
        return base.replace(tzinfo=timezone.utc)
    return base.astimezone(timezone.utc)


def _paginate(items: list[dict[str, Any]], *, page: int, page_size: int) -> dict[str, Any]:
    page = max(1, int(page))
    page_size = max(1, int(page_size))
    total = len(items)
    offset = (page - 1) * page_size
    return {
        "items": items[offset: offset + page_size],
        "count": min(page_size, max(total - offset, 0)),
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": offset + page_size < total,
    }


def _build_reconciliation_items(db: Session, *, q: str | None = None, issue_type: str | None = None, days_back: int = 120) -> list[dict[str, Any]]:
    now = _utc_now()
    since_dt = now - timedelta(days=max(1, int(days_back or 120)))
    txs = db.execute(
        select(VenueBillingTransaction).where(VenueBillingTransaction.created_at >= since_dt)
    ).scalars().all()
    events = db.execute(
        select(VenueBillingEvent).where(VenueBillingEvent.created_at >= since_dt)
    ).scalars().all()
    venue_ids = sorted({int(tx.venue_id) for tx in txs} | {int(ev.venue_id) for ev in events})
    venue_map = _load_venue_map(db, venue_ids)
    owner_map = _load_owner_labels(db, venue_ids)
    items: list[dict[str, Any]] = []

    for tx in txs:
        venue = venue_map.get(int(tx.venue_id))
        venue_name = venue.name if venue else f"Venue #{int(tx.venue_id)}"
        owner = owner_map.get(int(tx.venue_id)) or {}
        created_at = tx.created_at.astimezone(timezone.utc) if tx.created_at and tx.created_at.tzinfo else (tx.created_at.replace(tzinfo=timezone.utc) if tx.created_at else now)
        status = str(tx.status or "").upper()
        tx_type = str(tx.type or "").upper()
        if tx_type == "PAYMENT" and status == "PENDING":
            expires_at = get_checkout_expires_at(tx)
            if expires_at and expires_at <= now:
                items.append({
                    "issue_type": "STALE_PENDING_CHECKOUT",
                    "severity": "high",
                    "venue_id": int(tx.venue_id),
                    "venue_name": venue_name,
                    "owner": owner,
                    "transaction_id": int(tx.id),
                    "event_id": None,
                    "status": status,
                    "amount_minor": int(tx.amount_minor or 0),
                    "occurred_at": expires_at.isoformat(),
                    "description": f"Checkout просрочен и всё ещё находится в статусе PENDING.",
                })
        if tx_type == "PAYMENT" and status == "SUCCEEDED" and (tx.period_from is None or tx.period_until is None):
            items.append({
                "issue_type": "SUCCEEDED_NOT_APPLIED",
                "severity": "critical",
                "venue_id": int(tx.venue_id),
                "venue_name": venue_name,
                "owner": owner,
                "transaction_id": int(tx.id),
                "event_id": None,
                "status": status,
                "amount_minor": int(tx.amount_minor or 0),
                "occurred_at": created_at.isoformat(),
                "description": "Платёж отмечен как SUCCEEDED, но период продления не записан.",
            })
        if tx_type == "PAYMENT" and status == "FAILED":
            items.append({
                "issue_type": "FAILED_PAYMENT",
                "severity": "medium",
                "venue_id": int(tx.venue_id),
                "venue_name": venue_name,
                "owner": owner,
                "transaction_id": int(tx.id),
                "event_id": None,
                "status": status,
                "amount_minor": int(tx.amount_minor or 0),
                "occurred_at": created_at.isoformat(),
                "description": tx.comment or "Платёж завершился ошибкой.",
            })

    for event in events:
        et = str(event.event_type or "").upper()
        if et not in {"ROBOKASSA_RESULT_SIGNATURE_INVALID", "ROBOKASSA_AMOUNT_MISMATCH", "ROBOKASSA_RESULT_DUPLICATE"}:
            continue
        venue = venue_map.get(int(event.venue_id))
        venue_name = venue.name if venue else f"Venue #{int(event.venue_id)}"
        owner = owner_map.get(int(event.venue_id)) or {}
        meta = event.meta_json if isinstance(event.meta_json, dict) else {}
        if et == "ROBOKASSA_RESULT_SIGNATURE_INVALID":
            item_type = "INVALID_SIGNATURE"
            severity = "critical"
            description = "Robokassa callback пришёл с неверной подписью."
        elif et == "ROBOKASSA_AMOUNT_MISMATCH":
            item_type = "AMOUNT_MISMATCH"
            severity = "critical"
            description = "Сумма в callback не совпала с ожидаемой суммой счета."
        else:
            item_type = "DUPLICATE_CALLBACK"
            severity = "low"
            description = "Повторный callback по уже обработанному счёту."
        items.append({
            "issue_type": item_type,
            "severity": severity,
            "venue_id": int(event.venue_id),
            "venue_name": venue_name,
            "owner": owner,
            "transaction_id": int(meta.get("transaction_id") or 0) if meta.get("transaction_id") else None,
            "event_id": int(event.id),
            "status": None,
            "amount_minor": None,
            "occurred_at": event.created_at.isoformat() if event.created_at else None,
            "description": description,
        })

    if q:
        needle = str(q).strip().lower()
        items = [item for item in items if needle in str(item.get("venue_name") or "").lower() or needle in str(item.get("description") or "").lower()]
    if issue_type:
        issue_upper = str(issue_type).strip().upper()
        items = [item for item in items if str(item.get("issue_type") or "").upper() == issue_upper]
    items.sort(key=lambda item: str(item.get("occurred_at") or ""), reverse=True)
    return items


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
    reconciliation_items = _build_reconciliation_items(db)

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
            "unresolved_issues": len(reconciliation_items),
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


@router.get("/billing/transactions")
def get_admin_billing_transactions(
    q: str | None = Query(default=None),
    venue_id: int | None = Query(default=None),
    tx_type: str | None = Query(default=None),
    tx_status: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    stmt = select(VenueBillingTransaction).order_by(VenueBillingTransaction.created_at.desc(), VenueBillingTransaction.id.desc())
    if venue_id:
        stmt = stmt.where(VenueBillingTransaction.venue_id == int(venue_id))
    txs = db.execute(stmt).scalars().all()
    venue_ids = sorted({int(tx.venue_id) for tx in txs})
    venue_map = _load_venue_map(db, venue_ids)
    owner_map = _load_owner_labels(db, venue_ids)
    type_upper = str(tx_type or "").strip().upper()
    status_upper = str(tx_status or "").strip().upper()
    from_dt = _to_datetime(date_from)
    to_dt = _to_datetime(date_to, end_of_day=True)
    needle = str(q or "").strip().lower()

    items: list[dict[str, Any]] = []
    for tx in txs:
        created_at = tx.created_at.astimezone(timezone.utc) if tx.created_at and tx.created_at.tzinfo else (tx.created_at.replace(tzinfo=timezone.utc) if tx.created_at else None)
        if type_upper and str(tx.type or "").upper() != type_upper:
            continue
        if status_upper and str(tx.status or "").upper() != status_upper:
            continue
        if from_dt and created_at and created_at < from_dt:
            continue
        if to_dt and created_at and created_at > to_dt:
            continue
        venue = venue_map.get(int(tx.venue_id))
        venue_name = venue.name if venue else f"Venue #{int(tx.venue_id)}"
        if needle:
            haystack = " ".join([
                venue_name,
                str(tx.comment or ""),
                str(tx.provider_invoice_id or ""),
                str(tx.provider_payment_id or ""),
                str(tx.type or ""),
                str(tx.source or ""),
            ]).lower()
            if needle not in haystack:
                continue
        items.append(_serialize_billing_transaction(tx, venue_name=venue_name, owner=owner_map.get(int(tx.venue_id)) or {}))
    return _paginate(items, page=page, page_size=page_size)


@router.get("/billing/reconciliation")
def get_admin_billing_reconciliation(
    q: str | None = Query(default=None),
    issue_type: str | None = Query(default=None),
    days_back: int = Query(default=120, ge=1, le=3650),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    items = _build_reconciliation_items(db, q=q, issue_type=issue_type, days_back=days_back)
    out = _paginate(items, page=page, page_size=page_size)
    out["summary"] = {
        "critical": sum(1 for item in items if item.get("severity") == "critical"),
        "high": sum(1 for item in items if item.get("severity") == "high"),
        "medium": sum(1 for item in items if item.get("severity") == "medium"),
        "low": sum(1 for item in items if item.get("severity") == "low"),
    }
    return out


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
        "ok": True,
        "venue_id": int(venue.id),
        "transaction": _serialize_billing_transaction(tx, venue_name=venue.name),
        "event": _serialize_billing_event(event, venue_name=venue.name),
        "billing": {
            "status": snapshot.status,
            "paid_until": snapshot.paid_until.isoformat() if snapshot.paid_until else None,
            "grace_until": snapshot.grace_until.isoformat() if snapshot.grace_until else None,
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
        "ok": True,
        "venue_id": int(venue.id),
        "transaction": _serialize_billing_transaction(tx, venue_name=venue.name),
        "event": _serialize_billing_event(event, venue_name=venue.name),
        "billing": {
            "status": snapshot.status,
            "paid_until": snapshot.paid_until.isoformat() if snapshot.paid_until else None,
            "grace_until": snapshot.grace_until.isoformat() if snapshot.grace_until else None,
        },
    }


@router.post("/venues/{venue_id}/billing/refund")
def refund_admin_venue_billing(
    venue_id: int,
    payload: BillingRefundIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    venue = db.execute(select(Venue).where(Venue.id == int(venue_id))).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")

    latest_payment = db.execute(
        select(VenueBillingTransaction)
        .where(
            VenueBillingTransaction.venue_id == int(venue_id),
            VenueBillingTransaction.status == "SUCCEEDED",
            VenueBillingTransaction.type.in_(["PAYMENT", "EXTEND", "SET_PAID_UNTIL"]),
        )
        .order_by(VenueBillingTransaction.created_at.desc(), VenueBillingTransaction.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    latest_amount = int(latest_payment.amount_minor or 0) if latest_payment else 0
    if latest_amount and int(payload.amount_minor or 0) > latest_amount:
        raise HTTPException(status_code=400, detail="Сумма возврата больше последней успешной операции")

    state, tx, event = create_refund_transaction(
        db,
        venue_id=int(venue_id),
        amount_minor=int(payload.amount_minor),
        created_by_user_id=user.id,
        comment=payload.comment,
        related_transaction_id=payload.related_transaction_id or (int(latest_payment.id) if latest_payment else None),
        revoke_access_hint=bool(payload.revoke_access_hint),
    )
    db.commit()
    db.refresh(tx)
    db.refresh(event)
    snapshot = get_billing_snapshot_for_state(state)

    send_owner_billing_notification_once(
        db,
        venue_id=int(venue.id),
        notification_type="billing_refund",
        event_key=str(tx.id),
        text=f"По заведению «{venue.name}» оформлен возврат на сумму {int(payload.amount_minor or 0) / 100:.2f} ₽. Доступ не менялся автоматически.",
        button_text="Открыть заведение",
    )
    db.commit()

    return {
        "ok": True,
        "venue_id": int(venue.id),
        "transaction": _serialize_billing_transaction(tx, venue_name=venue.name),
        "event": _serialize_billing_event(event, venue_name=venue.name),
        "billing": {
            "status": snapshot.status,
            "paid_until": snapshot.paid_until.isoformat() if snapshot.paid_until else None,
            "grace_until": snapshot.grace_until.isoformat() if snapshot.grace_until else None,
            "revoke_access_hint": bool(payload.revoke_access_hint),
        },
    }
