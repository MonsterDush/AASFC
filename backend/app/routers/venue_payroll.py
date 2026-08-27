from fastapi import APIRouter

from app.routers.venue_core import (
    Depends,
    HTTPException,
    PayrollRecalculationLog,
    Query,
    Session,
    User,
    _require_active_member_or_admin,
    calculate_payroll_for_month,
    date,
    get_current_user,
    get_db,
    parse_month_start,
    resolve_salary_period,
    sanitize_financial_payload_for_user,
    select,
)
from app.schemas.venue_payroll import (
    PayrollCalculateIn,
    PayrollPaymentDraftGenerateIn,
    PayrollPaymentSettingsIn,
)
from app.routers.venue_pay_profile_support import _require_payroll_calculate, _require_payroll_view
from app.routers.venue_payroll_support import (
    _build_venue_payroll_period_payload,
    _create_payroll_recalculation_log,
    _load_payroll_payload,
    _payroll_recalculation_logs_table_exists,
    _serialize_payroll_recalculation_log,
)
from app.services.venue_member_names import apply_payroll_owner_display_names


router = APIRouter()


def _apply_payroll_member_display_names(
    db: Session,
    *,
    venue_id: int,
    user: User,
    payload: dict,
) -> dict:
    return apply_payroll_owner_display_names(db, venue_id=venue_id, viewer=user, payload=payload)


def _payment_window_payload(window) -> dict:
    return {
        "payment_date": window.payment_date.isoformat(),
        "period_start": window.period_start.isoformat(),
        "period_end": window.period_end.isoformat(),
    }


@router.get("/{venue_id}/payroll/payment-settings")
def get_payroll_payment_settings(
    venue_id: int,
    month: str | None = Query(default=None, description="Месяц дат выплаты, YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models import PayrollPaymentSettings
    from app.services.payroll.payments import (
        build_payment_windows,
        parse_monthly_rules,
        payment_windows_for_settings,
        serialize_payment_settings,
    )

    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_payroll_view(db, venue_id=venue_id, user=user)
    schedule_month = parse_month_start(month or date.today().strftime("%Y-%m"))
    settings = db.execute(
        select(PayrollPaymentSettings).where(PayrollPaymentSettings.venue_id == int(venue_id))
    ).scalar_one_or_none()
    if settings is None:
        payload = serialize_payment_settings(None)
        windows = build_payment_windows(
            schedule_month=schedule_month,
            cadence=payload["cadence"],
            weekly_payment_weekday=payload["weekly_payment_weekday"],
            monthly_rules=payload["monthly_rules"],
        )
    else:
        payload = serialize_payment_settings(settings)
        payload["monthly_rules"] = parse_monthly_rules(settings)
        windows = payment_windows_for_settings(settings, schedule_month=schedule_month)
    return {
        **payload,
        "preview_month": schedule_month.strftime("%Y-%m"),
        "preview": [_payment_window_payload(item) for item in windows],
    }


@router.put("/{venue_id}/payroll/payment-settings")
def update_payroll_payment_settings(
    venue_id: int,
    payload: PayrollPaymentSettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    import json
    from datetime import datetime

    from app.models import PaymentMethod, PayrollPaymentSettings, PayrollRun
    from app.services.finance.ledger import delete_finance_entries_for_source
    from app.services.payroll.payments import build_payment_windows, normalize_monthly_rules, serialize_payment_settings

    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_payroll_calculate(db, venue_id=venue_id, user=user)
    payment_method = db.execute(
        select(PaymentMethod).where(
            PaymentMethod.id == int(payload.payment_method_id),
            PaymentMethod.venue_id == int(venue_id),
            PaymentMethod.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if payment_method is None:
        raise HTTPException(status_code=404, detail="Payment method not found")

    cadence = str(payload.cadence or "MONTHLY").upper()
    try:
        rules = (
            normalize_monthly_rules([item.model_dump() for item in payload.monthly_rules])
            if cadence == "MONTHLY"
            else []
        )
        build_payment_windows(
            schedule_month=date.today().replace(day=1),
            cadence=cadence,
            weekly_payment_weekday=payload.weekly_payment_weekday,
            monthly_rules=rules,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    settings = db.execute(
        select(PayrollPaymentSettings).where(PayrollPaymentSettings.venue_id == int(venue_id))
    ).scalar_one_or_none()
    if settings is None:
        settings = PayrollPaymentSettings(venue_id=int(venue_id), created_at=datetime.utcnow())
        db.add(settings)
    settings.payment_method_id = int(payment_method.id)
    settings.cadence = cadence
    settings.weekly_payment_weekday = int(payload.weekly_payment_weekday or 0) if cadence == "WEEKLY" else None
    settings.monthly_rules_json = json.dumps(rules, ensure_ascii=False) if cadence == "MONTHLY" else None
    settings.is_active = bool(payload.is_active)
    settings.updated_at = datetime.utcnow()
    payroll_run_ids = db.execute(select(PayrollRun.id).where(PayrollRun.venue_id == int(venue_id))).all()
    for (payroll_run_id,) in payroll_run_ids:
        delete_finance_entries_for_source(
            db=db,
            source_type="payroll_run",
            source_id=int(payroll_run_id),
        )
    db.commit()
    db.refresh(settings)
    return serialize_payment_settings(settings)


@router.post("/{venue_id}/payroll/payment-drafts/generate")
def generate_payroll_payment_drafts(
    venue_id: int,
    payload: PayrollPaymentDraftGenerateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models import PayrollPaymentSettings
    from app.services.payroll.payments import generate_payroll_draft_expenses

    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_payroll_calculate(db, venue_id=venue_id, user=user)
    schedule_month = parse_month_start(payload.month)
    settings = db.execute(
        select(PayrollPaymentSettings).where(PayrollPaymentSettings.venue_id == int(venue_id))
    ).scalar_one_or_none()
    if settings is None:
        raise HTTPException(status_code=400, detail="Сначала сохраните настройки выплаты ФОТ")
    try:
        result = generate_payroll_draft_expenses(
            db,
            settings=settings,
            schedule_month=schedule_month,
            created_by_user_id=int(user.id),
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return {
        **result,
        "schedule_month": result["schedule_month"].strftime("%Y-%m"),
        "items": [
            {
                **item,
                "payment_date": item["payment_date"].isoformat(),
                "period_start": item["period_start"].isoformat(),
                "period_end": item["period_end"].isoformat(),
            }
            for item in result["items"]
        ],
    }


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
    result = _load_payroll_payload(db, venue_id=venue_id, month=payload.month)
    result = _apply_payroll_member_display_names(db, venue_id=venue_id, user=user, payload=result)
    return sanitize_financial_payload_for_user(user, result)


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
        payload = _apply_payroll_member_display_names(db, venue_id=venue_id, user=user, payload=payload)
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
        rows = (
            db.execute(
                select(PayrollRecalculationLog)
                .where(
                    PayrollRecalculationLog.venue_id == int(venue_id),
                    PayrollRecalculationLog.period_month == month_start,
                )
                .order_by(PayrollRecalculationLog.created_at.desc(), PayrollRecalculationLog.id.desc())
                .limit(int(limit))
            )
            .scalars()
            .all()
        )

    return {
        "month": month,
        "items": [_serialize_payroll_recalculation_log(row) for row in rows],
    }


# ---------- Daily reports ----------
