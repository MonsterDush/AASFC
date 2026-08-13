from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_current_user_optional
from app.auth.venue_permissions import require_venue_permission
from app.core.config import settings
from app.core.db import get_db
from app.core.i18n import user_locale
from app.models.balance_adjustment import BalanceAdjustment
from app.models.department import Department
from app.models.daily_report import DailyReport
from app.models.finance_entry import FinanceEntry
from app.models.payment_method import PaymentMethod
from app.models.payment_method_transfer import PaymentMethodTransfer
from app.models.user import User
from app.models.venue import Venue
from app.routers.venue_access import (
    is_owner_or_super_admin as _is_owner_or_super_admin,
    require_active_member_or_admin as _require_active_member_or_admin,
)
from app.routers.venue_catalogs import _get_payment_method_or_404
from app.routers.venue_common import (
    _load_user_for_signed_export,
    _require_financial_values_export_allowed,
)
from app.schemas.finance import (
    BalanceAdjustmentCreateIn,
    BalanceAdjustmentUpdateIn,
    PaymentMethodTransferCreateIn,
    PaymentMethodTransferUpdateIn,
)
from app.services.finance.balance_adjustments import (
    delete_balance_adjustment_entries,
    rebuild_balance_adjustment_entries,
)
from app.services.finance.payment_transfers import (
    delete_payment_method_transfer_entries,
    rebuild_payment_method_transfer_entries,
)
from app.services.finance.summary import resolve_finance_period
from app.services.finance.reconciliation import build_finance_reconciliation
from app.services.financial_privacy import sanitize_financial_payload_for_user
from app.services.signed_links import make_signed_token, verify_signed_token
from app.services.xlsx_export import build_finance_ledger_xlsx


router = APIRouter()


def _serialize_balance_adjustment(adjustment: BalanceAdjustment, payment_method: PaymentMethod | None = None) -> dict:
    pm = payment_method or getattr(adjustment, "payment_method", None)
    return {
        "id": adjustment.id,
        "venue_id": adjustment.venue_id,
        "payment_method_id": adjustment.payment_method_id,
        "adjustment_date": adjustment.adjustment_date.isoformat() if adjustment.adjustment_date else None,
        "delta_minor": int(adjustment.delta_minor or 0),
        "status": str(getattr(adjustment, "status", "CONFIRMED") or "CONFIRMED").upper(),
        "reason": adjustment.reason,
        "comment": adjustment.comment,
        "created_by_user_id": adjustment.created_by_user_id,
        "created_at": adjustment.created_at.isoformat() if adjustment.created_at else None,
        "updated_at": adjustment.updated_at.isoformat() if adjustment.updated_at else None,
        "payment_method": {
            "id": pm.id,
            "code": pm.code,
            "title": pm.title,
        }
        if pm is not None
        else None,
    }


def _serialize_payment_method_transfer(
    transfer: PaymentMethodTransfer,
    from_payment_method: PaymentMethod | None = None,
    to_payment_method: PaymentMethod | None = None,
) -> dict:
    from_pm = from_payment_method or getattr(transfer, "from_payment_method", None)
    to_pm = to_payment_method or getattr(transfer, "to_payment_method", None)
    return {
        "id": transfer.id,
        "venue_id": transfer.venue_id,
        "from_payment_method_id": transfer.from_payment_method_id,
        "to_payment_method_id": transfer.to_payment_method_id,
        "transfer_date": transfer.transfer_date.isoformat() if transfer.transfer_date else None,
        "amount_minor": int(transfer.amount_minor or 0),
        "status": str(getattr(transfer, "status", "CONFIRMED") or "CONFIRMED").upper(),
        "comment": transfer.comment,
        "created_by_user_id": transfer.created_by_user_id,
        "created_at": transfer.created_at.isoformat() if transfer.created_at else None,
        "updated_at": transfer.updated_at.isoformat() if transfer.updated_at else None,
        "from_payment_method": {
            "id": from_pm.id,
            "code": from_pm.code,
            "title": from_pm.title,
        }
        if from_pm is not None
        else None,
        "to_payment_method": {
            "id": to_pm.id,
            "code": to_pm.code,
            "title": to_pm.title,
        }
        if to_pm is not None
        else None,
    }


def _serialize_finance_entry(
    entry: FinanceEntry,
    payment_method: PaymentMethod | None = None,
    department: Department | None = None,
    report_shift_slot: str | None = None,
) -> dict:
    pm = payment_method or getattr(entry, "payment_method", None)
    dept = department or getattr(entry, "department", None)
    source_type = str(entry.source_type or "").lower()
    meta_json = dict(entry.meta_json or {})
    if source_type == "daily_report" and report_shift_slot:
        meta_json.setdefault("shift_slot", str(report_shift_slot).upper())
    return {
        "id": entry.id,
        "venue_id": entry.venue_id,
        "entry_date": entry.entry_date.isoformat() if entry.entry_date else None,
        "amount_minor": int(entry.amount_minor or 0),
        "direction": str(entry.direction or "").upper(),
        "kind": str(entry.kind or "").upper(),
        "source_type": source_type,
        "source_id": int(entry.source_id) if entry.source_id is not None else None,
        "meta_json": meta_json or None,
        "payment_method": {
            "id": pm.id,
            "code": pm.code,
            "title": pm.title,
        }
        if pm is not None
        else None,
        "department": {
            "id": dept.id,
            "code": dept.code,
            "title": dept.title,
        }
        if dept is not None
        else None,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _require_finance_ledger_view(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="FINANCE_LEDGER_VIEW")
        return
    except HTTPException:
        pass
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="REVENUE_VIEW")
        return
    except HTTPException:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")


def _require_finance_reconciliation_view(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    for permission_code in ("REPORTS_VIEW_PNL", "MONTHLY_SUMMARY_VIEW"):
        try:
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code=permission_code)
            return
        except HTTPException:
            pass
    for permission_code in ("REVENUE_VIEW", "EXPENSE_VIEW", "PAYROLL_VIEW"):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code=permission_code)


def _require_payment_transfers_manage(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYMENT_TRANSFERS_MANAGE")
        return
    except HTTPException:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")


def _resolve_ledger_period(
    *,
    month: str | None,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date] | None:
    if month and (date_from is not None or date_to is not None):
        raise HTTPException(status_code=400, detail="Use either month or date_from/date_to")
    if month is None and date_from is None and date_to is None:
        return None
    try:
        return resolve_finance_period(month=month, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _finance_entries_statement(
    *,
    venue_id: int,
    month: str | None,
    date_from: date | None,
    date_to: date | None,
    payment_method_id: int | None,
    direction: str | None,
    kind: str | None,
    source_type: str | None,
):
    stmt = (
        select(FinanceEntry, PaymentMethod, Department, DailyReport.shift_slot)
        .outerjoin(PaymentMethod, PaymentMethod.id == FinanceEntry.payment_method_id)
        .outerjoin(Department, Department.id == FinanceEntry.department_id)
        .outerjoin(
            DailyReport,
            and_(FinanceEntry.source_type == "daily_report", DailyReport.id == FinanceEntry.source_id),
        )
    )

    stmt = _apply_finance_entry_filters(
        stmt,
        venue_id=venue_id,
        month=month,
        date_from=date_from,
        date_to=date_to,
        payment_method_id=payment_method_id,
        direction=direction,
        kind=kind,
        source_type=source_type,
    )
    return stmt.order_by(FinanceEntry.entry_date.desc(), FinanceEntry.id.desc())


def _apply_finance_entry_filters(
    stmt,
    *,
    venue_id: int,
    month: str | None,
    date_from: date | None,
    date_to: date | None,
    payment_method_id: int | None,
    direction: str | None,
    kind: str | None,
    source_type: str | None,
):
    stmt = stmt.where(FinanceEntry.venue_id == venue_id)
    period = _resolve_ledger_period(month=month, date_from=date_from, date_to=date_to)
    if period is not None:
        start, end = period
        stmt = stmt.where(FinanceEntry.entry_date >= start, FinanceEntry.entry_date <= end)
    if payment_method_id is not None:
        stmt = stmt.where(FinanceEntry.payment_method_id == int(payment_method_id))
    if direction:
        stmt = stmt.where(FinanceEntry.direction == str(direction).upper())
    if kind:
        stmt = stmt.where(FinanceEntry.kind == str(kind).upper())
    if source_type:
        stmt = stmt.where(FinanceEntry.source_type == str(source_type).lower())
    return stmt


def _load_finance_entry_payload(
    db: Session,
    *,
    venue_id: int,
    month: str | None,
    date_from: date | None,
    date_to: date | None,
    payment_method_id: int | None,
    direction: str | None,
    kind: str | None,
    source_type: str | None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    stmt = _finance_entries_statement(
        venue_id=venue_id,
        month=month,
        date_from=date_from,
        date_to=date_to,
        payment_method_id=payment_method_id,
        direction=direction,
        kind=kind,
        source_type=source_type,
    )
    if offset > 0:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = db.execute(stmt).all()
    return [
        _serialize_finance_entry(entry, payment_method, department, report_shift_slot)
        for entry, payment_method, department, report_shift_slot in rows
    ]


def _load_finance_entry_analytics(
    db: Session,
    *,
    venue_id: int,
    month: str | None,
    date_from: date | None,
    date_to: date | None,
    payment_method_id: int | None,
    direction: str | None,
    kind: str | None,
    source_type: str | None,
) -> dict:
    income_amount = case(
        (FinanceEntry.direction == "INCOME", FinanceEntry.amount_minor),
        else_=0,
    )
    expense_amount = case(
        (FinanceEntry.direction == "EXPENSE", FinanceEntry.amount_minor),
        else_=0,
    )

    def filtered(stmt):
        return _apply_finance_entry_filters(
            stmt,
            venue_id=venue_id,
            month=month,
            date_from=date_from,
            date_to=date_to,
            payment_method_id=payment_method_id,
            direction=direction,
            kind=kind,
            source_type=source_type,
        )

    metrics_row = db.execute(
        filtered(
            select(
                func.coalesce(func.sum(income_amount), 0),
                func.coalesce(func.sum(expense_amount), 0),
                func.count(FinanceEntry.id),
            )
        )
    ).one()
    income_minor = int(metrics_row[0] or 0)
    expense_minor = int(metrics_row[1] or 0)

    daily_rows = db.execute(
        filtered(
            select(
                FinanceEntry.entry_date,
                func.coalesce(func.sum(income_amount), 0),
                func.coalesce(func.sum(expense_amount), 0),
                func.count(FinanceEntry.id),
            )
        )
        .group_by(FinanceEntry.entry_date)
        .order_by(FinanceEntry.entry_date)
    ).all()

    structure_rows = db.execute(
        filtered(
            select(
                FinanceEntry.direction,
                FinanceEntry.kind,
                func.coalesce(func.sum(FinanceEntry.amount_minor), 0),
                func.count(FinanceEntry.id),
            )
        )
        .where(FinanceEntry.direction.in_(("INCOME", "EXPENSE")))
        .group_by(
            FinanceEntry.direction,
            FinanceEntry.kind,
        )
    ).all()

    return {
        "metrics": {
            "income_minor": income_minor,
            "expense_minor": expense_minor,
            "net_minor": income_minor - expense_minor,
            "count": int(metrics_row[2] or 0),
        },
        "daily_series": [
            {
                "date": row[0].isoformat(),
                "income_minor": int(row[1] or 0),
                "expense_minor": int(row[2] or 0),
                "net_minor": int(row[1] or 0) - int(row[2] or 0),
                "count": int(row[3] or 0),
            }
            for row in daily_rows
        ],
        "structure": [
            {
                "direction": str(row[0] or "").upper(),
                "kind": str(row[1] or "").upper(),
                "amount_minor": int(row[2] or 0),
                "count": int(row[3] or 0),
            }
            for row in structure_rows
        ],
    }


@router.get("/{venue_id}/balance-adjustments")
def list_balance_adjustments(
    venue_id: int,
    month: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_finance_ledger_view(db, venue_id=venue_id, user=user)

    stmt = (
        select(BalanceAdjustment, PaymentMethod)
        .join(PaymentMethod, PaymentMethod.id == BalanceAdjustment.payment_method_id)
        .where(BalanceAdjustment.venue_id == venue_id)
    )

    period = _resolve_ledger_period(month=month, date_from=date_from, date_to=date_to)
    if period is not None:
        start, end = period
        stmt = stmt.where(BalanceAdjustment.adjustment_date >= start, BalanceAdjustment.adjustment_date <= end)

    rows = db.execute(stmt.order_by(BalanceAdjustment.adjustment_date.desc(), BalanceAdjustment.id.desc())).all()
    payload = [_serialize_balance_adjustment(adjustment, payment_method) for adjustment, payment_method in rows]
    return sanitize_financial_payload_for_user(user, payload)


@router.post("/{venue_id}/balance-adjustments")
def create_balance_adjustment(
    venue_id: int,
    payload: BalanceAdjustmentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.payment_method_id)
    if int(payload.delta_minor) == 0:
        raise HTTPException(status_code=400, detail="delta_minor must be non-zero")

    obj = BalanceAdjustment(
        venue_id=venue_id,
        payment_method_id=int(payload.payment_method_id),
        adjustment_date=payload.adjustment_date,
        delta_minor=int(payload.delta_minor),
        status=str(payload.status or "CONFIRMED").upper(),
        reason=(payload.reason or None),
        comment=(payload.comment or None),
        created_by_user_id=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    db.flush()
    rebuild_balance_adjustment_entries(db=db, adjustment=obj)
    db.commit()
    db.refresh(obj)
    return _serialize_balance_adjustment(obj, payment_method)


@router.patch("/{venue_id}/balance-adjustments/{adjustment_id}")
def update_balance_adjustment(
    venue_id: int,
    adjustment_id: int,
    payload: BalanceAdjustmentUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    obj = db.execute(
        select(BalanceAdjustment).where(BalanceAdjustment.id == adjustment_id, BalanceAdjustment.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Balance adjustment not found")

    if payload.payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.payment_method_id)
        obj.payment_method_id = int(payload.payment_method_id)
    if payload.adjustment_date is not None:
        obj.adjustment_date = payload.adjustment_date
    if payload.delta_minor is not None:
        if int(payload.delta_minor) == 0:
            raise HTTPException(status_code=400, detail="delta_minor must be non-zero")
        obj.delta_minor = int(payload.delta_minor)
    if payload.status is not None:
        obj.status = str(payload.status or "CONFIRMED").upper()
    if payload.reason is not None:
        obj.reason = payload.reason or None
    if payload.comment is not None:
        obj.comment = payload.comment or None
    obj.updated_at = datetime.utcnow()

    rebuild_balance_adjustment_entries(db=db, adjustment=obj)
    db.commit()
    db.refresh(obj)
    payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=obj.payment_method_id)
    return _serialize_balance_adjustment(obj, payment_method)


@router.delete("/{venue_id}/balance-adjustments/{adjustment_id}")
def delete_balance_adjustment(
    venue_id: int,
    adjustment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    obj = db.execute(
        select(BalanceAdjustment).where(BalanceAdjustment.id == adjustment_id, BalanceAdjustment.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Balance adjustment not found")
    delete_balance_adjustment_entries(db=db, adjustment_id=obj.id)
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.get("/{venue_id}/finance/entries")
def list_finance_entries(
    venue_id: int,
    month: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    payment_method_id: int | None = Query(default=None),
    direction: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_finance_ledger_view(db, venue_id=venue_id, user=user)
    payload = _load_finance_entry_payload(
        db,
        venue_id=venue_id,
        month=month,
        date_from=date_from,
        date_to=date_to,
        payment_method_id=payment_method_id,
        direction=direction,
        kind=kind,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    return sanitize_financial_payload_for_user(user, payload)


@router.get("/{venue_id}/finance/entries/analytics")
def get_finance_entries_analytics(
    venue_id: int,
    month: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    payment_method_id: int | None = Query(default=None),
    direction: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_finance_ledger_view(db, venue_id=venue_id, user=user)
    payload = _load_finance_entry_analytics(
        db,
        venue_id=venue_id,
        month=month,
        date_from=date_from,
        date_to=date_to,
        payment_method_id=payment_method_id,
        direction=direction,
        kind=kind,
        source_type=source_type,
    )
    return sanitize_financial_payload_for_user(user, payload)


@router.get("/{venue_id}/finance/reconciliation")
def get_finance_reconciliation(
    venue_id: int,
    month: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_finance_reconciliation_view(db, venue_id=venue_id, user=user)
    try:
        payload = build_finance_reconciliation(
            db=db,
            venue_id=venue_id,
            month=month,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return sanitize_financial_payload_for_user(user, payload)


@router.get("/{venue_id}/finance/entries/export-link")
def get_finance_entries_export_link(
    venue_id: int,
    request: Request,
    month: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    payment_method_id: int | None = Query(default=None),
    direction: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_finance_ledger_view(db, venue_id=venue_id, user=user)
    _require_financial_values_export_allowed(user)
    if _resolve_ledger_period(month=month, date_from=date_from, date_to=date_to) is None:
        raise HTTPException(status_code=400, detail="Export period is required")
    token = make_signed_token(
        {
            "action": "finance_entries_export",
            "venue_id": int(venue_id),
            "month": month or None,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "payment_method_id": int(payment_method_id) if payment_method_id is not None else None,
            "direction": str(direction).upper() if direction else None,
            "kind": str(kind).upper() if kind else None,
            "source_type": str(source_type).lower() if source_type else None,
            "user_id": int(user.id),
        }
    )
    query: list[str] = []
    for key, value in (
        ("month", month),
        ("date_from", date_from.isoformat() if date_from else None),
        ("date_to", date_to.isoformat() if date_to else None),
        ("payment_method_id", payment_method_id),
        ("direction", str(direction).upper() if direction else None),
        ("kind", str(kind).upper() if kind else None),
        ("source_type", str(source_type).lower() if source_type else None),
    ):
        if value is not None and value != "":
            query.append(f"{key}={quote(str(value))}")
    query.append(f"token={quote(token)}")
    base = str(request.base_url).rstrip("/")
    export_path = f"/venues/{venue_id}/finance/entries/export?{'&'.join(query)}"
    return {
        "export_path": export_path,
        "export_link": f"{base}{export_path}",
        "expires_in": int(getattr(settings, "EXPORT_LINK_TTL_SECONDS", 600) or 600),
    }


@router.get("/{venue_id}/finance/entries/export")
def export_finance_entries(
    venue_id: int,
    month: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    payment_method_id: int | None = Query(default=None),
    direction: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    token: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if token:
        try:
            signed = verify_signed_token(token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid export token")
        if str(signed.get("action") or "") != "finance_entries_export" or int(signed.get("venue_id") or 0) != int(
            venue_id
        ):
            raise HTTPException(status_code=401, detail="Invalid export token")
        month = signed.get("month") or None
        date_from = date.fromisoformat(signed["date_from"]) if signed.get("date_from") else None
        date_to = date.fromisoformat(signed["date_to"]) if signed.get("date_to") else None
        payment_method_id = int(signed["payment_method_id"]) if signed.get("payment_method_id") is not None else None
        direction = signed.get("direction") or None
        kind = signed.get("kind") or None
        source_type = signed.get("source_type") or None
        export_user = _load_user_for_signed_export(db, signed)
        _require_financial_values_export_allowed(export_user)
    else:
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        _require_active_member_or_admin(db, venue_id=venue_id, user=user)
        _require_finance_ledger_view(db, venue_id=venue_id, user=user)
        _require_financial_values_export_allowed(user)
        export_user = user

    period = _resolve_ledger_period(month=month, date_from=date_from, date_to=date_to)
    if period is None:
        raise HTTPException(status_code=400, detail="Export period is required")
    period_start, period_end = period
    rows = _load_finance_entry_payload(
        db,
        venue_id=venue_id,
        month=month,
        date_from=date_from,
        date_to=date_to,
        payment_method_id=payment_method_id,
        direction=direction,
        kind=kind,
        source_type=source_type,
    )
    venue_name = (
        db.execute(select(Venue.name).where(Venue.id == int(venue_id))).scalar_one_or_none() or f"Заведение {venue_id}"
    )
    filters: list[tuple[str, str]] = []
    if payment_method_id is not None:
        payment_title = db.execute(
            select(PaymentMethod.title).where(
                PaymentMethod.id == int(payment_method_id),
                PaymentMethod.venue_id == int(venue_id),
            )
        ).scalar_one_or_none()
        filters.append(("Тип оплаты", payment_title or f"ID {payment_method_id}"))
    if direction:
        filters.append(("Направление", "Приход" if str(direction).upper() == "INCOME" else "Списание"))
    if kind:
        filters.append(("Вид движения", str(kind).upper()))
    if source_type:
        filters.append(("Источник", str(source_type).lower()))
    xlsx_bytes = build_finance_ledger_xlsx(
        venue_name=str(venue_name),
        period_start=period_start,
        period_end=period_end,
        rows=rows,
        filters=filters,
        locale=user_locale(export_user),
    )
    filename = f"finance_ledger_{venue_id}_{period_start.isoformat()}_{period_end.isoformat()}.xlsx"
    return StreamingResponse(
        BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": (f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}")},
    )


@router.get("/{venue_id}/payment-method-transfers")
def list_payment_method_transfers(
    venue_id: int,
    month: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_finance_ledger_view(db, venue_id=venue_id, user=user)

    from_pm = PaymentMethod.__table__.alias("from_pm")
    to_pm = PaymentMethod.__table__.alias("to_pm")
    stmt = (
        select(
            PaymentMethodTransfer,
            from_pm.c.id,
            from_pm.c.code,
            from_pm.c.title,
            to_pm.c.id,
            to_pm.c.code,
            to_pm.c.title,
        )
        .join(from_pm, from_pm.c.id == PaymentMethodTransfer.from_payment_method_id)
        .join(to_pm, to_pm.c.id == PaymentMethodTransfer.to_payment_method_id)
        .where(PaymentMethodTransfer.venue_id == venue_id)
    )

    period = _resolve_ledger_period(month=month, date_from=date_from, date_to=date_to)
    if period is not None:
        start, end = period
        stmt = stmt.where(PaymentMethodTransfer.transfer_date >= start, PaymentMethodTransfer.transfer_date <= end)

    rows = db.execute(stmt.order_by(PaymentMethodTransfer.transfer_date.desc(), PaymentMethodTransfer.id.desc())).all()
    out = []
    for row in rows:
        transfer = row[0]
        from_payment_method = type("PM", (), {"id": row[1], "code": row[2], "title": row[3]})()
        to_payment_method = type("PM", (), {"id": row[4], "code": row[5], "title": row[6]})()
        out.append(_serialize_payment_method_transfer(transfer, from_payment_method, to_payment_method))
    return sanitize_financial_payload_for_user(user, out)


@router.post("/{venue_id}/payment-method-transfers")
def create_payment_method_transfer(
    venue_id: int,
    payload: PaymentMethodTransferCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_payment_transfers_manage(db, venue_id=venue_id, user=user)
    from_payment_method = _get_payment_method_or_404(
        db, venue_id=venue_id, payment_method_id=payload.from_payment_method_id
    )
    to_payment_method = _get_payment_method_or_404(
        db, venue_id=venue_id, payment_method_id=payload.to_payment_method_id
    )
    if int(payload.from_payment_method_id) == int(payload.to_payment_method_id):
        raise HTTPException(status_code=400, detail="Transfer methods must be different")

    obj = PaymentMethodTransfer(
        venue_id=venue_id,
        from_payment_method_id=int(payload.from_payment_method_id),
        to_payment_method_id=int(payload.to_payment_method_id),
        transfer_date=payload.transfer_date,
        amount_minor=int(payload.amount_minor),
        status=str(payload.status or "CONFIRMED").upper(),
        comment=(payload.comment or None),
        created_by_user_id=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    db.flush()
    rebuild_payment_method_transfer_entries(db=db, transfer=obj)
    db.commit()
    db.refresh(obj)
    return _serialize_payment_method_transfer(obj, from_payment_method, to_payment_method)


@router.patch("/{venue_id}/payment-method-transfers/{transfer_id}")
def update_payment_method_transfer(
    venue_id: int,
    transfer_id: int,
    payload: PaymentMethodTransferUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_payment_transfers_manage(db, venue_id=venue_id, user=user)
    obj = db.execute(
        select(PaymentMethodTransfer).where(
            PaymentMethodTransfer.id == transfer_id, PaymentMethodTransfer.venue_id == venue_id
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Payment method transfer not found")

    if payload.from_payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.from_payment_method_id)
        obj.from_payment_method_id = int(payload.from_payment_method_id)
    if payload.to_payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.to_payment_method_id)
        obj.to_payment_method_id = int(payload.to_payment_method_id)
    if int(obj.from_payment_method_id) == int(obj.to_payment_method_id):
        raise HTTPException(status_code=400, detail="Transfer methods must be different")
    if payload.transfer_date is not None:
        obj.transfer_date = payload.transfer_date
    if payload.amount_minor is not None:
        obj.amount_minor = int(payload.amount_minor)
    if payload.status is not None:
        obj.status = str(payload.status or "CONFIRMED").upper()
    if payload.comment is not None:
        obj.comment = payload.comment or None
    obj.updated_at = datetime.utcnow()

    rebuild_payment_method_transfer_entries(db=db, transfer=obj)
    db.commit()
    db.refresh(obj)
    from_payment_method = _get_payment_method_or_404(
        db, venue_id=venue_id, payment_method_id=obj.from_payment_method_id
    )
    to_payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=obj.to_payment_method_id)
    return _serialize_payment_method_transfer(obj, from_payment_method, to_payment_method)


@router.delete("/{venue_id}/payment-method-transfers/{transfer_id}")
def delete_payment_method_transfer(
    venue_id: int,
    transfer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_payment_transfers_manage(db, venue_id=venue_id, user=user)
    obj = db.execute(
        select(PaymentMethodTransfer).where(
            PaymentMethodTransfer.id == transfer_id, PaymentMethodTransfer.venue_id == venue_id
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Payment method transfer not found")
    delete_payment_method_transfer_entries(db=db, transfer_id=obj.id)
    db.delete(obj)
    db.commit()
    return {"ok": True}
