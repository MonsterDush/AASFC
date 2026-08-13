from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.venue_permissions import has_venue_permission
from app.core.db import get_db
from app.models.user import User
from app.routers.venue_access import (
    is_owner_or_super_admin as _is_owner_or_super_admin,
    require_active_member_or_admin as _require_active_member_or_admin,
    require_report_viewer as _require_report_viewer,
    require_revenue_viewer as _require_revenue_viewer,
)
from app.schemas.finance import DailyFinanceSummaryOut, FinanceSummaryOut, MonthlyFinanceSummaryOut
from app.services.finance.summary import get_day_finance_summary, get_finance_summary, get_monthly_finance_summary
from app.services.financial_privacy import sanitize_financial_payload_for_user


router = APIRouter()


def _finance_summary_access(db: Session, *, venue_id: int, user: User) -> dict[str, bool]:
    full_access = _is_owner_or_super_admin(db, venue_id=venue_id, user=user) or any(
        has_venue_permission(db, venue_id=venue_id, user=user, permission_code=code)
        for code in ("REPORTS_VIEW_PNL", "MONTHLY_SUMMARY_VIEW")
    )
    can_view_revenue = full_access or has_venue_permission(
        db, venue_id=venue_id, user=user, permission_code="REVENUE_VIEW"
    )
    can_view_expenses = full_access or has_venue_permission(
        db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW"
    )
    can_view_payroll = full_access or has_venue_permission(
        db, venue_id=venue_id, user=user, permission_code="PAYROLL_VIEW"
    )
    return {
        "can_view_revenue": can_view_revenue,
        "can_view_expenses": can_view_expenses,
        "can_view_payroll": can_view_payroll,
        "can_view_profit": can_view_revenue and can_view_expenses and can_view_payroll,
    }


def _restrict_finance_summary_payload(payload: dict, access: dict[str, bool]) -> dict:
    out = dict(payload or {})
    can_revenue = bool(access.get("can_view_revenue"))
    can_expenses = bool(access.get("can_view_expenses"))
    can_payroll = bool(access.get("can_view_payroll"))
    can_profit = bool(access.get("can_view_profit"))
    out.update(access)

    if not can_revenue:
        for key in ("revenue_minor", "adjustments_minor", "refunds_minor"):
            out[key] = None
    if not can_expenses:
        for key in ("expense_minor", "expense_without_payroll_minor"):
            out[key] = None
    if not can_payroll:
        for key in ("payroll_minor", "payroll_expense_minor"):
            out[key] = None
    if not (can_expenses and can_payroll):
        out["total_cost_minor"] = None
    if not can_profit:
        for key in ("profit_minor", "margin_bps"):
            out[key] = None
    if not (can_revenue and can_expenses):
        out["expense_ratio_bps"] = None
    if not (can_revenue and can_payroll):
        out["payroll_ratio_bps"] = None
    if not can_profit:
        out["total_cost_ratio_bps"] = None

    restricted_series: list[dict] = []
    for raw_point in out.get("daily_series") or []:
        point = dict(raw_point or {})
        if not can_revenue:
            for key in ("revenue_minor", "adjustments_minor", "refunds_minor"):
                point[key] = None
        if not can_expenses:
            point["expense_minor"] = None
        if not can_payroll:
            point["payroll_minor"] = None
        if not (can_expenses and can_payroll):
            point["total_cost_minor"] = None
        if not can_profit:
            point["profit_minor"] = None
        restricted_series.append(point)
    out["daily_series"] = restricted_series

    out["cost_structure"] = [
        dict(row)
        for row in (out.get("cost_structure") or [])
        if (
            (str((row or {}).get("key") or "") == "payroll" and can_payroll)
            or (str((row or {}).get("key") or "") != "payroll" and can_expenses)
        )
    ]
    return out


@router.get("/{venue_id}/summary/monthly", response_model=MonthlyFinanceSummaryOut)
def get_venue_monthly_finance_summary(
    venue_id: int,
    month: str | None = Query(None, description="YYYY-MM"),
    date_from: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    income_mode: str = Query("PAYMENTS", description="PAYMENTS|DEPARTMENTS"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    try:
        payload = get_monthly_finance_summary(
            db=db,
            venue_id=venue_id,
            month=month,
            date_from=date_from,
            date_to=date_to,
            income_mode=income_mode,
        )
        return sanitize_financial_payload_for_user(user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{venue_id}/summary/day", response_model=DailyFinanceSummaryOut)
def get_venue_day_finance_summary(
    venue_id: int,
    summary_date: date = Query(..., alias="date", description="YYYY-MM-DD"),
    income_mode: str = Query("PAYMENTS", description="PAYMENTS|DEPARTMENTS"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    shift_slot: str = Query("TOTAL", pattern="^(TOTAL|DAY|NIGHT)$"),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    try:
        payload = get_day_finance_summary(
            db=db,
            venue_id=venue_id,
            target_date=summary_date,
            income_mode=income_mode,
            shift_slot=shift_slot,
        )
        return sanitize_financial_payload_for_user(user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{venue_id}/finance/summary", response_model=FinanceSummaryOut)
def get_venue_finance_summary(
    venue_id: int,
    month: str | None = Query(None, description="YYYY-MM"),
    date_from: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD (inclusive)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    include_series: bool = False,
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    access = _finance_summary_access(db, venue_id=venue_id, user=user)
    if not any(access.values()):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        payload = get_finance_summary(
            db=db,
            venue_id=venue_id,
            month=month,
            date_from=date_from,
            date_to=date_to,
            include_series=include_series,
        )
        restricted = _restrict_finance_summary_payload(payload, access)
        return sanitize_financial_payload_for_user(user, restricted)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
