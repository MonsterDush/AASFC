from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.routers.venue_access import (
    require_active_member_or_admin as _require_active_member_or_admin,
    require_report_viewer as _require_report_viewer,
    require_revenue_viewer as _require_revenue_viewer,
)
from app.schemas.finance import DailyFinanceSummaryOut, FinanceSummaryOut, MonthlyFinanceSummaryOut
from app.services.finance.summary import get_day_finance_summary, get_finance_summary, get_monthly_finance_summary
from app.services.financial_privacy import sanitize_financial_payload_for_user


router = APIRouter()


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
    _require_revenue_viewer(db, venue_id=venue_id, user=user)
    _require_report_viewer(db, venue_id=venue_id, user=user)
    try:
        payload = get_finance_summary(
            db=db,
            venue_id=venue_id,
            month=month,
            date_from=date_from,
            date_to=date_to,
            include_series=include_series,
        )
        return sanitize_financial_payload_for_user(user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
