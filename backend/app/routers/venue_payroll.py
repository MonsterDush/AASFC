from fastapi import APIRouter

from app.routers.venue_core import (
    Depends,
    HTTPException,
    PayrollCalculateIn,
    PayrollRecalculationLog,
    Query,
    Session,
    User,
    _build_venue_payroll_period_payload,
    _create_payroll_recalculation_log,
    _load_payroll_payload,
    _payroll_recalculation_logs_table_exists,
    _require_active_member_or_admin,
    _require_payroll_calculate,
    _require_payroll_view,
    _serialize_payroll_recalculation_log,
    calculate_payroll_for_month,
    date,
    get_current_user,
    get_db,
    parse_month_start,
    resolve_salary_period,
    sanitize_financial_payload_for_user,
    select,
)


router = APIRouter()


@router.post("/{venue_id}/payroll/calculate")
def calculate_payroll(
    venue_id: int,
    payload: PayrollCalculateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_payroll_calculate(db, venue_id=venue_id, user=user)

    try:
        calculate_payroll_for_month(
            db=db,
            venue_id=venue_id,
            month=payload.month,
            calculated_by_user_id=user.id,
        )
        _create_payroll_recalculation_log(
            db,
            venue_id=int(venue_id),
            period_month=parse_month_start(payload.month),
            trigger_reason="manual_calculation",
            triggered_by_user_id=int(user.id),
            target_dates=[],
            details={"source": "manual_payroll_calculate"},
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    db.commit()
    return sanitize_financial_payload_for_user(user, _load_payroll_payload(db, venue_id=venue_id, month=payload.month))


@router.get("/{venue_id}/payroll")
def get_payroll(
    venue_id: int,
    month: str | None = Query(default=None, description="YYYY-MM"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_payroll_view(db, venue_id=venue_id, user=user)

    try:
        period_start, period_end, period_meta = resolve_salary_period(month=month, date_from=date_from, date_to=date_to)
        if period_meta.get("mode") == "month":
            payload = _load_payroll_payload(db, venue_id=venue_id, month=str(period_meta.get("month") or month))
        else:
            payload = _build_venue_payroll_period_payload(
                db,
                venue_id=venue_id,
                period_start=period_start,
                period_end=period_end,
                period_meta=period_meta,
            )
        return sanitize_financial_payload_for_user(user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{venue_id}/payroll/recalculation-log")
def get_payroll_recalculation_log(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_payroll_view(db, venue_id=venue_id, user=user)

    try:
        month_start = parse_month_start(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not _payroll_recalculation_logs_table_exists(db):
        rows = []
    else:
        rows = db.execute(
            select(PayrollRecalculationLog)
            .where(
                PayrollRecalculationLog.venue_id == int(venue_id),
                PayrollRecalculationLog.period_month == month_start,
            )
            .order_by(PayrollRecalculationLog.created_at.desc(), PayrollRecalculationLog.id.desc())
            .limit(int(limit))
        ).scalars().all()

    return {
        "month": month,
        "items": [_serialize_payroll_recalculation_log(row) for row in rows],
    }


# ---------- Daily reports ----------

