from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO, StringIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.guards import require_super_admin
from app.core.db import get_db
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_billing_event import VenueBillingEvent
from app.models.venue_billing_transaction import VenueBillingTransaction
from app.models.venue_member import VenueMember
from app.services.billing import (
    ISSUE_STATUS_OPEN,
    create_refund_transaction,
    extend_venue_billing,
    get_billing_health_summary,
    get_billing_snapshot_for_state,
    get_or_create_billing_state,
    list_billing_events,
    list_billing_reconciliation_issues,
    list_billing_transactions,
    list_billing_transactions_global,
    send_owner_billing_notification_once,
    set_billing_reconciliation_issue_status,
    set_venue_billing_paid_until,
    sync_billing_reconciliation_issues,
)
from app.services.xlsx_export import build_billing_reconciliation_xlsx, build_billing_transactions_xlsx

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
    amount_minor: int | None = Field(default=None, ge=0)
    comment: str | None = Field(default=None, max_length=1000)
    revoke_access_hint: bool = False


class BillingExportParams(BaseModel):
    status: str | None = None
    tx_type: str | None = None
    source: str | None = None
    q: str | None = None
    venue_id: int | None = None


class BillingIssueActionIn(BaseModel):
    comment: str | None = Field(default=None, max_length=1000)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _month_range_utc(target: date | None = None) -> tuple[datetime, datetime]:
    base = target or _utc_now().date()
    start = datetime.combine(date(base.year, base.month, 1), time.min, tzinfo=timezone.utc)
    if base.month == 12:
        end = datetime.combine(date(base.year + 1, 1, 1), time.min, tzinfo=timezone.utc)
    else:
        end = datetime.combine(date(base.year, base.month + 1, 1), time.min, tzinfo=timezone.utc)
    return start, end


def _load_owner_labels(db: Session, venue_ids: list[int]) -> dict[int, dict[str, Any]]:
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
    out: dict[int, dict[str, Any]] = {}
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


def _billing_tx_stmt(
    *,
    venue_id: int | None = None,
    status: str | None = None,
    tx_type: str | None = None,
    source: str | None = None,
    q: str | None = None,
):
    stmt = select(VenueBillingTransaction, Venue.name).join(Venue, Venue.id == VenueBillingTransaction.venue_id)
    if venue_id is not None:
        stmt = stmt.where(VenueBillingTransaction.venue_id == int(venue_id))
    if status:
        stmt = stmt.where(VenueBillingTransaction.status == str(status).upper())
    if tx_type:
        stmt = stmt.where(VenueBillingTransaction.type == str(tx_type).upper())
    if source:
        stmt = stmt.where(VenueBillingTransaction.source == str(source).upper())
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Venue.name.ilike(term),
                VenueBillingTransaction.comment.ilike(term),
                VenueBillingTransaction.provider_invoice_id.ilike(term),
                VenueBillingTransaction.provider_payment_id.ilike(term),
            )
        )
    return stmt


def _billing_event_stmt(*, venue_id: int | None = None, q: str | None = None):
    stmt = select(VenueBillingEvent, Venue.name).join(Venue, Venue.id == VenueBillingEvent.venue_id)
    if venue_id is not None:
        stmt = stmt.where(VenueBillingEvent.venue_id == int(venue_id))
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Venue.name.ilike(term),
                VenueBillingEvent.event_type.ilike(term),
            )
        )
    return stmt


def _serialize_transaction(tx: VenueBillingTransaction, *, venue_name: str | None = None) -> dict[str, Any]:
    return {
        "id": int(tx.id),
        "venue_id": int(tx.venue_id),
        "venue_name": venue_name,
        "source": tx.source,
        "type": tx.type,
        "status": tx.status,
        "amount_minor": int(tx.amount_minor or 0),
        "amount_major": int(tx.amount_minor or 0) / 100.0,
        "days_added": int(tx.days_added or 0) if tx.days_added is not None else None,
        "period_from": tx.period_from,
        "period_until": tx.period_until,
        "provider_invoice_id": tx.provider_invoice_id,
        "provider_payment_id": tx.provider_payment_id,
        "comment": tx.comment,
        "created_by_user_id": tx.created_by_user_id,
        "created_at": tx.created_at,
        "updated_at": tx.updated_at,
    }


def _serialize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    payload = dict(issue)
    created_at = payload.get("created_at")
    if isinstance(created_at, datetime):
        payload["created_at"] = created_at.isoformat()
    return payload


def _derive_reconciliation_issues(db: Session, *, venue_id: int | None = None, q: str | None = None) -> list[dict[str, Any]]:
    now = _utc_now()
    issues: list[dict[str, Any]] = []

    tx_rows = db.execute(
        _billing_tx_stmt(venue_id=venue_id, q=q).order_by(VenueBillingTransaction.created_at.desc(), VenueBillingTransaction.id.desc()).limit(500)
    ).all()
    for tx, venue_name in tx_rows:
        status = str(tx.status or "").upper()
        tx_type_upper = str(tx.type or "").upper()
        payload = tx.provider_payload_json if isinstance(tx.provider_payload_json, dict) else {}
        created = _ensure_aware(tx.created_at) or now
        expires_at = None
        raw_expires = payload.get("checkout_expires_at")
        if raw_expires:
            try:
                expires_at = _ensure_aware(datetime.fromisoformat(str(raw_expires)))
            except Exception:
                expires_at = None
        if tx_type_upper == "PAYMENT" and status == "PENDING" and expires_at and expires_at <= now:
            issues.append({
                "severity": "warning",
                "issue_code": "STALE_PENDING_CHECKOUT",
                "message": "Checkout создан, но оплата не завершена вовремя.",
                "venue_id": int(tx.venue_id),
                "venue_name": venue_name,
                "transaction_id": int(tx.id),
                "event_id": None,
                "created_at": expires_at,
            })
        if tx_type_upper == "PAYMENT" and status == "SUCCEEDED" and not tx.period_until:
            issues.append({
                "severity": "critical",
                "issue_code": "SUCCEEDED_NOT_APPLIED",
                "message": "Оплата отмечена успешной, но период продления не записан.",
                "venue_id": int(tx.venue_id),
                "venue_name": venue_name,
                "transaction_id": int(tx.id),
                "event_id": None,
                "created_at": created,
            })
        if tx_type_upper == "PAYMENT" and status == "FAILED":
            issues.append({
                "severity": "info",
                "issue_code": "FAILED_PAYMENT",
                "message": tx.comment or "Платёж завершился ошибкой.",
                "venue_id": int(tx.venue_id),
                "venue_name": venue_name,
                "transaction_id": int(tx.id),
                "event_id": None,
                "created_at": created,
            })

    event_rows = db.execute(
        _billing_event_stmt(venue_id=venue_id, q=q).order_by(VenueBillingEvent.created_at.desc(), VenueBillingEvent.id.desc()).limit(500)
    ).all()
    for event, venue_name in event_rows:
        event_type = str(event.event_type or "").upper()
        meta = event.meta_json if isinstance(event.meta_json, dict) else {}
        if event_type == "ROBOKASSA_RESULT_SIGNATURE_INVALID":
            issues.append({
                "severity": "critical",
                "issue_code": "INVALID_SIGNATURE",
                "message": "Robokassa callback пришёл с неверной подписью.",
                "venue_id": int(event.venue_id),
                "venue_name": venue_name,
                "transaction_id": meta.get("transaction_id"),
                "event_id": int(event.id),
                "created_at": event.created_at,
            })
        elif event_type == "ROBOKASSA_AMOUNT_MISMATCH":
            issues.append({
                "severity": "critical",
                "issue_code": "AMOUNT_MISMATCH",
                "message": "Сумма callback не совпала с суммой транзакции.",
                "venue_id": int(event.venue_id),
                "venue_name": venue_name,
                "transaction_id": meta.get("transaction_id"),
                "event_id": int(event.id),
                "created_at": event.created_at,
            })
        elif event_type == "ROBOKASSA_RESULT_DUPLICATE":
            issues.append({
                "severity": "warning",
                "issue_code": "DUPLICATE_CALLBACK",
                "message": "Robokassa прислала повторный callback по уже обработанному счёту.",
                "venue_id": int(event.venue_id),
                "venue_name": venue_name,
                "transaction_id": meta.get("transaction_id"),
                "event_id": int(event.id),
                "created_at": event.created_at,
            })

    issues.sort(key=lambda item: (_ensure_aware(item.get("created_at")) or now), reverse=True)
    return issues


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "billing")).strip("_") or "billing"


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
    receipts_minor = sum(int(tx.amount_minor or 0) for tx in tx_rows if str(tx.type or "").upper() != "REFUND")
    refunds_minor = sum(int(tx.amount_minor or 0) for tx in tx_rows if str(tx.type or "").upper() == "REFUND")

    return {
        "totals": {
            "venues_total": len(venues),
            "active": active_count,
            "grace": grace_count,
            "suspended": suspended_count,
            "mrr_minor": int(mrr_minor),
            "receipts_current_month_minor": int(receipts_minor),
            "refunds_current_month_minor": int(refunds_minor),
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

        txs = list_billing_transactions(db, venue_id=int(venue.id), limit=3)
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
            "last_extension_transaction": _serialize_transaction(last_tx, venue_name=venue.name) if last_tx else None,
        })

    def _date_value(value):
        if value is None:
            return datetime(1970, 1, 1, tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except Exception:
                return datetime(1970, 1, 1, tzinfo=timezone.utc)
        return _ensure_aware(value) or datetime(1970, 1, 1, tzinfo=timezone.utc)

    sort_key = str(sort_by or "paid_until_asc").strip().lower()
    if sort_key == "paid_until_desc":
        result.sort(key=lambda item: _date_value(item.get("paid_until")), reverse=True)
    elif sort_key == "last_payment_desc":
        result.sort(key=lambda item: _date_value(item.get("last_payment_at")), reverse=True)
    elif sort_key == "name_asc":
        result.sort(key=lambda item: str(item.get("venue_name") or "").lower())
    elif sort_key == "name_desc":
        result.sort(key=lambda item: str(item.get("venue_name") or "").lower(), reverse=True)
    else:
        result.sort(key=lambda item: _date_value(item.get("paid_until")))

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
    venue_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    tx_type: str | None = Query(default=None),
    source: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    stmt = _billing_tx_stmt(venue_id=venue_id, status=status, tx_type=tx_type, source=source, q=q)
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    rows = db.execute(
        stmt.order_by(VenueBillingTransaction.created_at.desc(), VenueBillingTransaction.id.desc())
        .offset((int(page) - 1) * int(page_size))
        .limit(int(page_size))
    ).all()
    items = [_serialize_transaction(tx, venue_name=venue_name) for tx, venue_name in rows]
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "page": int(page),
        "page_size": int(page_size),
        "has_next": int(page) * int(page_size) < total,
    }


@router.get("/billing/reconciliation")
def get_admin_billing_reconciliation(
    venue_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    status: str = Query(default=ISSUE_STATUS_OPEN),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    sync_billing_reconciliation_issues(db, venue_id=venue_id)
    db.commit()
    items, total = list_billing_reconciliation_issues(db, venue_id=venue_id, search=q, status=status, page=page, page_size=page_size)
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "page": int(page),
        "page_size": int(page_size),
        "has_next": int(page) * int(page_size) < total,
    }


@router.get("/billing/health")
def get_admin_billing_health(
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    sync_billing_reconciliation_issues(db)
    db.commit()
    return get_billing_health_summary(db)


@router.get("/billing/transactions/export")
def export_admin_billing_transactions(
    venue_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    tx_type: str | None = Query(default=None),
    source: str | None = Query(default=None),
    q: str | None = Query(default=None),
    fmt: str = Query(default="xlsx"),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    rows, _ = list_billing_transactions_global(db, venue_id=venue_id, status=status, tx_type=tx_type, source=source, page=1, page_size=500)
    venue_map = {int(v.id): v.name for v in db.execute(select(Venue).where(Venue.id.in_([int(tx.venue_id) for tx in rows] or [-1]))).scalars().all()}
    items = [_serialize_transaction(tx, venue_name=venue_map.get(int(tx.venue_id))) for tx in rows if not q or q.strip().lower() in str(venue_map.get(int(tx.venue_id), "")).lower() or q.strip().lower() in str(tx.comment or "").lower() or q.strip().lower() in str(tx.provider_invoice_id or "").lower()]
    filters = [("Venue ID", venue_id or "Все"), ("Status", status or "Все"), ("Type", tx_type or "Все"), ("Source", source or "Все"), ("Search", q or "—")]
    fmt_norm = str(fmt or "xlsx").lower().strip()
    if fmt_norm == "csv":
        out = StringIO()
        writer = csv.writer(out)
        writer.writerow(["created_at", "venue_name", "status", "type", "source", "amount_minor", "days_added", "period_from", "period_until", "provider_invoice_id", "provider_payment_id", "comment"])
        for row in items:
            writer.writerow([row.get("created_at"), row.get("venue_name"), row.get("status"), row.get("type"), row.get("source"), row.get("amount_minor"), row.get("days_added"), row.get("period_from"), row.get("period_until"), row.get("provider_invoice_id"), row.get("provider_payment_id"), row.get("comment")])
        data = out.getvalue().encode("utf-8-sig")
        filename = "billing_transactions.csv"
        return StreamingResponse(BytesIO(data), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    xlsx = build_billing_transactions_xlsx(title="Axelio · Реестр billing-операций", rows=items, filters=filters)
    return StreamingResponse(BytesIO(xlsx), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="billing_transactions.xlsx"'})


@router.get("/billing/reconciliation/export")
def export_admin_billing_reconciliation(
    venue_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    status: str = Query(default=ISSUE_STATUS_OPEN),
    fmt: str = Query(default="xlsx"),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    sync_billing_reconciliation_issues(db, venue_id=venue_id)
    db.commit()
    issues, _ = list_billing_reconciliation_issues(db, venue_id=venue_id, search=q, status=status, page=1, page_size=1000)
    filters = [("Venue ID", venue_id or "Все"), ("Status", status or "Все"), ("Search", q or "—")]
    fmt_norm = str(fmt or "xlsx").lower().strip()
    if fmt_norm == "csv":
        out = StringIO()
        writer = csv.writer(out)
        writer.writerow(["created_at", "last_seen_at", "resolved_at", "status", "severity", "issue_code", "venue_name", "transaction_id", "event_id", "message", "resolution_comment"])
        for row in issues:
            writer.writerow([row.get("created_at") or row.get("first_detected_at"), row.get("last_seen_at"), row.get("resolved_at"), row.get("status"), row.get("severity"), row.get("issue_code"), row.get("venue_name"), row.get("transaction_id"), row.get("event_id"), row.get("message"), row.get("resolution_comment")])
        data = out.getvalue().encode("utf-8-sig")
        return StreamingResponse(BytesIO(data), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="billing_reconciliation.csv"'})
    xlsx = build_billing_reconciliation_xlsx(title="Axelio · Billing reconciliation", rows=issues, filters=filters)
    return StreamingResponse(BytesIO(xlsx), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="billing_reconciliation.xlsx"'})


@router.post("/billing/reconciliation/{issue_id}/resolve")
def resolve_billing_reconciliation_issue(
    issue_id: int,
    payload: BillingIssueActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    issue = set_billing_reconciliation_issue_status(db, issue_id=int(issue_id), new_status="RESOLVED", acted_by_user_id=int(user.id), comment=payload.comment)
    db.commit()
    return {"ok": True, "issue_id": int(issue.id), "status": issue.status}


@router.post("/billing/reconciliation/{issue_id}/ignore")
def ignore_billing_reconciliation_issue(
    issue_id: int,
    payload: BillingIssueActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    issue = set_billing_reconciliation_issue_status(db, issue_id=int(issue_id), new_status="IGNORED", acted_by_user_id=int(user.id), comment=payload.comment)
    db.commit()
    return {"ok": True, "issue_id": int(issue.id), "status": issue.status}


@router.post("/billing/reconciliation/{issue_id}/reopen")
def reopen_billing_reconciliation_issue(
    issue_id: int,
    payload: BillingIssueActionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    issue = set_billing_reconciliation_issue_status(db, issue_id=int(issue_id), new_status="OPEN", acted_by_user_id=int(user.id), comment=payload.comment)
    db.commit()
    return {"ok": True, "issue_id": int(issue.id), "status": issue.status}


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
        "transaction": _serialize_transaction(tx, venue_name=venue.name),
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
        "transaction": _serialize_transaction(tx, venue_name=venue.name),
        "event": {
            "id": int(event.id),
            "event_type": event.event_type,
            "old_status": event.old_status,
            "new_status": event.new_status,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        },
    }


@router.post("/venues/{venue_id}/billing/refund")
def create_admin_billing_refund(
    venue_id: int,
    payload: BillingRefundIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    venue = db.execute(select(Venue).where(Venue.id == int(venue_id))).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    state = get_or_create_billing_state(db, venue_id=int(venue_id))
    amount_minor = int(payload.amount_minor if payload.amount_minor is not None else (state.price_minor or 0))
    if amount_minor <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    tx, event = create_refund_transaction(
        db,
        venue_id=int(venue_id),
        amount_minor=amount_minor,
        created_by_user_id=user.id,
        comment=payload.comment,
        revoke_access_hint=bool(payload.revoke_access_hint),
    )
    db.commit()
    send_owner_billing_notification_once(
        db,
        venue_id=int(venue.id),
        notification_type="refund_created",
        event_key=str(tx.id),
        text=f"По заведению «{venue.name}» зафиксирован возврат на сумму {amount_minor / 100:.2f} ₽.",
        button_text="Открыть подписку",
    )
    db.commit()
    return {
        "venue_id": int(venue.id),
        "venue_name": venue.name,
        "transaction": _serialize_transaction(tx, venue_name=venue.name),
        "event": {
            "id": int(event.id),
            "event_type": event.event_type,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        },
    }
