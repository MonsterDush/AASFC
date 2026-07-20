from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.db import get_db
from app.models.pay_component import PayComponent
from app.models.pay_profile import PayProfile
from app.models.user import User
from app.routers.venue_access import (
    require_active_member_or_admin,
    require_owner_or_super_admin,
    require_report_viewer,
    require_revenue_viewer,
)
from app.schemas.venue_economics import (
    DayEconomicsMonthPlanCopyOut,
    DayEconomicsMonthPlanIn,
    DayEconomicsMonthPlanOut,
    DayEconomicsOut,
    DayEconomicsPlanIn,
    DayEconomicsPlanOut,
    DayEconomicsPlanTemplateIn,
    DayEconomicsPlanTemplateOut,
    DayEconomicsTemplateCopyIn,
    DayEconomicsTemplateCopyOut,
    DepartmentPlanAutofillOut,
    DepartmentPlanBulkIn,
    DepartmentPlanCopyOut,
    DepartmentPlanDayOut,
    DepartmentPlanMonthOut,
    VenueEconomicsRulesIn,
    VenueEconomicsRulesOut,
)
from app.services.finance.day_economics import (
    autofill_department_day_plans_from_history,
    autofill_department_month_plans_from_last_month,
    copy_day_economics_month_plan_from_previous_month,
    copy_day_economics_plan_templates,
    copy_department_day_plans_from_date,
    distribute_department_month_plans_from_venue_plan,
    get_day_economics,
    get_day_economics_month_plan,
    get_day_economics_plan,
    get_day_economics_plan_override,
    get_venue_economics_rules,
    list_day_economics_plan_templates,
    list_department_day_plans,
    list_department_month_plans,
    upsert_day_economics_month_plan,
    upsert_day_economics_plan,
    upsert_day_economics_plan_template,
    upsert_department_day_plans,
    upsert_department_month_plans,
    upsert_venue_economics_rules,
)
from app.services.financial_privacy import sanitize_financial_payload_for_user
from app.services.payroll.calculator import (
    BOOST_SOURCE_DEPARTMENT_DAY_PLAN,
    BOOST_SOURCE_DEPARTMENT_MONTH_PLAN,
    BOOST_SOURCE_VENUE_DAY_PLAN,
    BOOST_SOURCE_VENUE_MONTH_PLAN,
)


router = APIRouter()


def _empty_usage_counts() -> dict:
    return {"usage_component_count": 0, "usage_profile_count": 0}


def _build_percent_boost_usage_map(db: Session, *, venue_id: int) -> dict:
    rows = db.execute(
        select(
            PayComponent.boost_source_type,
            PayComponent.boost_department_id,
            func.count(PayComponent.id),
            func.count(func.distinct(PayComponent.pay_profile_id)),
        )
        .join(PayProfile, PayProfile.id == PayComponent.pay_profile_id)
        .where(
            PayComponent.venue_id == int(venue_id),
            PayComponent.is_active.is_(True),
            PayProfile.is_active.is_(True),
            PayComponent.component_type.in_(["PERCENT_TOTAL_REVENUE", "PERCENT_DEPARTMENT_REVENUE"]),
            PayComponent.boost_enabled.is_(True),
            PayComponent.boost_percent_bps.is_not(None),
            PayComponent.boost_source_type.in_(
                [
                    BOOST_SOURCE_VENUE_MONTH_PLAN,
                    BOOST_SOURCE_VENUE_DAY_PLAN,
                    BOOST_SOURCE_DEPARTMENT_MONTH_PLAN,
                    BOOST_SOURCE_DEPARTMENT_DAY_PLAN,
                ]
            ),
        )
        .group_by(PayComponent.boost_source_type, PayComponent.boost_department_id)
    ).all()
    result = {
        BOOST_SOURCE_VENUE_MONTH_PLAN: _empty_usage_counts(),
        BOOST_SOURCE_VENUE_DAY_PLAN: _empty_usage_counts(),
        BOOST_SOURCE_DEPARTMENT_MONTH_PLAN: {},
        BOOST_SOURCE_DEPARTMENT_DAY_PLAN: {},
    }
    for source_type, department_id, component_count, profile_count in rows:
        source_key = str(source_type or "").strip().upper()
        payload = {
            "usage_component_count": int(component_count or 0),
            "usage_profile_count": int(profile_count or 0),
        }
        if source_key in {BOOST_SOURCE_VENUE_MONTH_PLAN, BOOST_SOURCE_VENUE_DAY_PLAN}:
            result[source_key] = payload
        elif source_key in {BOOST_SOURCE_DEPARTMENT_MONTH_PLAN, BOOST_SOURCE_DEPARTMENT_DAY_PLAN}:
            department_key = int(department_id or 0)
            if department_key > 0:
                result[source_key][department_key] = payload
    return result


def _attach_usage_to_day_plan(plan: dict, usage_counts: dict | None) -> dict:
    payload = dict(plan or {})
    counts = usage_counts or _empty_usage_counts()
    payload["usage_component_count"] = int(counts.get("usage_component_count", 0) or 0)
    payload["usage_profile_count"] = int(counts.get("usage_profile_count", 0) or 0)
    return payload


def _attach_usage_to_department_plan_payload(payload: dict, usage_map: dict[int, dict] | None) -> dict:
    result = dict(payload or {})
    items = []
    for item in list(result.get("items") or []):
        row = dict(item or {})
        department_id = int(row.get("department_id") or 0)
        counts = (usage_map or {}).get(department_id) or _empty_usage_counts()
        row["usage_component_count"] = int(counts.get("usage_component_count", 0) or 0)
        row["usage_profile_count"] = int(counts.get("usage_profile_count", 0) or 0)
        items.append(row)
    result["items"] = items
    return result


def _usage_counts_for_effective_plan(plan: dict, usage_map: dict) -> dict:
    source = str((plan or {}).get("source") or "").strip().upper()
    if source == "DATE_OVERRIDE":
        return dict((usage_map or {}).get(BOOST_SOURCE_VENUE_DAY_PLAN) or _empty_usage_counts())
    if source == "MONTH_TEMPLATE":
        return dict((usage_map or {}).get(BOOST_SOURCE_VENUE_MONTH_PLAN) or _empty_usage_counts())
    return _empty_usage_counts()


def _require_economics_view(db: Session, *, venue_id: int, user: User) -> None:
    require_active_member_or_admin(db, venue_id=venue_id, user=user)
    require_revenue_viewer(db, venue_id=venue_id, user=user)
    require_report_viewer(db, venue_id=venue_id, user=user)


@router.get("/{venue_id}/economics/day", response_model=DayEconomicsOut)
def get_venue_day_economics(
    venue_id: int,
    economics_date: date = Query(..., alias="date", description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_economics_view(db, venue_id=venue_id, user=user)
    try:
        payload = get_day_economics(db=db, venue_id=venue_id, target_date=economics_date)
        return sanitize_financial_payload_for_user(user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{venue_id}/economics/plan", response_model=DayEconomicsPlanOut)
def get_venue_day_economics_plan_route(
    venue_id: int,
    economics_date: date = Query(..., alias="date", description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_economics_view(db, venue_id=venue_id, user=user)
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    plan = get_day_economics_plan(db=db, venue_id=venue_id, target_date=economics_date)
    return _attach_usage_to_day_plan(plan, _usage_counts_for_effective_plan(plan, usage_map))


@router.get("/{venue_id}/economics/plan-month", response_model=DayEconomicsMonthPlanOut)
def get_venue_day_economics_month_plan_route(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_economics_view(db, venue_id=venue_id, user=user)
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    plan = _attach_usage_to_day_plan(
        get_day_economics_month_plan(db=db, venue_id=venue_id, month_value=month),
        usage_map.get(BOOST_SOURCE_VENUE_MONTH_PLAN),
    )
    return {"month": month, **plan}


@router.get("/{venue_id}/economics/plan/override", response_model=DayEconomicsPlanOut)
def get_venue_day_economics_plan_override_route(
    venue_id: int,
    economics_date: date = Query(..., alias="date", description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_economics_view(db, venue_id=venue_id, user=user)
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    plan = get_day_economics_plan_override(db=db, venue_id=venue_id, target_date=economics_date)
    return _attach_usage_to_day_plan(plan, usage_map.get(BOOST_SOURCE_VENUE_DAY_PLAN))


@router.put("/{venue_id}/economics/plan", response_model=DayEconomicsPlanOut)
def put_venue_day_economics_plan(
    venue_id: int,
    payload: DayEconomicsPlanIn,
    economics_date: date = Query(..., alias="date", description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    plan = upsert_day_economics_plan(
        db=db,
        venue_id=venue_id,
        target_date=economics_date,
        revenue_plan_minor=payload.revenue_plan_minor,
        profit_plan_minor=payload.profit_plan_minor,
        revenue_per_assigned_plan_minor=payload.revenue_per_assigned_plan_minor,
        assigned_user_target=payload.assigned_user_target,
        day_kind=payload.day_kind,
        title=payload.title,
        notes=payload.notes,
    )
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    return _attach_usage_to_day_plan(plan, usage_map.get(BOOST_SOURCE_VENUE_DAY_PLAN))


@router.put("/{venue_id}/economics/plan-month", response_model=DayEconomicsMonthPlanOut)
def put_venue_day_economics_month_plan(
    venue_id: int,
    payload: DayEconomicsMonthPlanIn,
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    plan = upsert_day_economics_month_plan(
        db=db,
        venue_id=venue_id,
        month_value=month,
        revenue_plan_minor=payload.revenue_plan_minor,
        profit_plan_minor=payload.profit_plan_minor,
        revenue_per_assigned_plan_minor=payload.revenue_per_assigned_plan_minor,
        assigned_user_target=payload.assigned_user_target,
        notes=payload.notes,
    )
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    plan = _attach_usage_to_day_plan(plan, usage_map.get(BOOST_SOURCE_VENUE_MONTH_PLAN))
    return {"month": month, **plan}


@router.post("/{venue_id}/economics/plan-month/copy-previous", response_model=DayEconomicsMonthPlanCopyOut)
def post_venue_day_economics_month_plan_copy_previous(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    overwrite: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = copy_day_economics_month_plan_from_previous_month(
            db=db,
            venue_id=venue_id,
            month_value=month,
            overwrite=overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    plan = _attach_usage_to_day_plan(
        result.get("plan") or {},
        usage_map.get(BOOST_SOURCE_VENUE_MONTH_PLAN),
    )
    return {
        "copied": bool(result["copied"]),
        "copied_from_month": result["copied_from_month"],
        "plan": {"month": month, **plan},
    }


@router.get("/{venue_id}/economics/plan-templates", response_model=list[DayEconomicsPlanTemplateOut])
def get_venue_day_economics_plan_templates_route(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_economics_view(db, venue_id=venue_id, user=user)
    return list_day_economics_plan_templates(db=db, venue_id=venue_id)


@router.put("/{venue_id}/economics/plan-templates/{weekday}", response_model=DayEconomicsPlanTemplateOut)
def put_venue_day_economics_plan_template(
    venue_id: int,
    weekday: int,
    payload: DayEconomicsPlanTemplateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        row = upsert_day_economics_plan_template(
            db=db,
            venue_id=venue_id,
            weekday=weekday,
            revenue_plan_minor=payload.revenue_plan_minor,
            profit_plan_minor=payload.profit_plan_minor,
            revenue_per_assigned_plan_minor=payload.revenue_per_assigned_plan_minor,
            assigned_user_target=payload.assigned_user_target,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return row


@router.post("/{venue_id}/economics/plan-templates/copy", response_model=DayEconomicsTemplateCopyOut)
def post_venue_day_economics_plan_templates_copy(
    venue_id: int,
    payload: DayEconomicsTemplateCopyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = copy_day_economics_plan_templates(
            db=db,
            venue_id=venue_id,
            source_weekday=payload.source_weekday,
            target_weekdays=payload.target_weekdays,
            overwrite=payload.overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return result


@router.get("/{venue_id}/economics/department-plan-month", response_model=DepartmentPlanMonthOut)
def get_venue_department_month_plans(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_economics_view(db, venue_id=venue_id, user=user)
    try:
        payload = list_department_month_plans(db=db, venue_id=venue_id, month_value=month)
        usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
        payload = _attach_usage_to_department_plan_payload(
            payload,
            usage_map.get(BOOST_SOURCE_DEPARTMENT_MONTH_PLAN),
        )
        return sanitize_financial_payload_for_user(user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{venue_id}/economics/department-plan-month", response_model=DepartmentPlanMonthOut)
def put_venue_department_month_plans(
    venue_id: int,
    payload: DepartmentPlanBulkIn,
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = upsert_department_month_plans(
            db=db,
            venue_id=venue_id,
            month_value=month,
            items=[item.model_dump() for item in payload.items],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    return _attach_usage_to_department_plan_payload(
        result,
        usage_map.get(BOOST_SOURCE_DEPARTMENT_MONTH_PLAN),
    )


@router.post(
    "/{venue_id}/economics/department-plan-month/autofill-from-last-month",
    response_model=DepartmentPlanAutofillOut,
)
def post_venue_department_month_plans_autofill(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    overwrite: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = autofill_department_month_plans_from_last_month(
            db=db,
            venue_id=venue_id,
            month_value=month,
            overwrite=overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    result["plan"] = _attach_usage_to_department_plan_payload(
        result.get("plan") or {},
        usage_map.get(BOOST_SOURCE_DEPARTMENT_MONTH_PLAN),
    )
    return result


@router.post(
    "/{venue_id}/economics/department-plan-month/distribute-from-venue-plan",
    response_model=DepartmentPlanAutofillOut,
)
def post_venue_department_month_plans_distribute(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    overwrite: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = distribute_department_month_plans_from_venue_plan(
            db=db,
            venue_id=venue_id,
            month_value=month,
            overwrite=overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    result["plan"] = _attach_usage_to_department_plan_payload(
        result.get("plan") or {},
        usage_map.get(BOOST_SOURCE_DEPARTMENT_MONTH_PLAN),
    )
    return result


@router.get("/{venue_id}/economics/department-plan-day", response_model=DepartmentPlanDayOut)
def get_venue_department_day_plans(
    venue_id: int,
    date: date = Query(..., description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_economics_view(db, venue_id=venue_id, user=user)
    try:
        payload = list_department_day_plans(db=db, venue_id=venue_id, target_date=date)
        usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
        payload = _attach_usage_to_department_plan_payload(
            payload,
            usage_map.get(BOOST_SOURCE_DEPARTMENT_DAY_PLAN),
        )
        return sanitize_financial_payload_for_user(user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{venue_id}/economics/department-plan-day", response_model=DepartmentPlanDayOut)
def put_venue_department_day_plans(
    venue_id: int,
    payload: DepartmentPlanBulkIn,
    date: date = Query(..., description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = upsert_department_day_plans(
            db=db,
            venue_id=venue_id,
            target_date=date,
            items=[item.model_dump() for item in payload.items],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    return _attach_usage_to_department_plan_payload(
        result,
        usage_map.get(BOOST_SOURCE_DEPARTMENT_DAY_PLAN),
    )


@router.post("/{venue_id}/economics/department-plan-day/copy-from-date", response_model=DepartmentPlanCopyOut)
def post_venue_department_day_plans_copy_from_date(
    venue_id: int,
    source_date: date = Query(..., description="YYYY-MM-DD"),
    target_date: date = Query(..., description="YYYY-MM-DD"),
    overwrite: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = copy_department_day_plans_from_date(
            db=db,
            venue_id=venue_id,
            source_date=source_date,
            target_date=target_date,
            overwrite=overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    result["plan"] = _attach_usage_to_department_plan_payload(
        result.get("plan") or {},
        usage_map.get(BOOST_SOURCE_DEPARTMENT_DAY_PLAN),
    )
    return result


@router.post(
    "/{venue_id}/economics/department-plan-day/autofill-from-history",
    response_model=DepartmentPlanAutofillOut,
)
def post_venue_department_day_plans_autofill_from_history(
    venue_id: int,
    target_date: date = Query(..., description="YYYY-MM-DD"),
    mode: str = Query("SAME_WEEKDAY_AVG"),
    overwrite: bool = Query(True),
    lookback_weeks: int = Query(4, ge=1, le=12),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    try:
        result = autofill_department_day_plans_from_history(
            db=db,
            venue_id=venue_id,
            target_date=target_date,
            mode=mode,
            overwrite=overwrite,
            lookback_weeks=lookback_weeks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    usage_map = _build_percent_boost_usage_map(db, venue_id=venue_id)
    result["plan"] = _attach_usage_to_department_plan_payload(
        result.get("plan") or {},
        usage_map.get(BOOST_SOURCE_DEPARTMENT_DAY_PLAN),
    )
    return result


@router.get("/{venue_id}/economics/rules", response_model=VenueEconomicsRulesOut)
def get_venue_day_economics_rules_route(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_economics_view(db, venue_id=venue_id, user=user)
    return get_venue_economics_rules(db=db, venue_id=venue_id)


@router.put("/{venue_id}/economics/rules", response_model=VenueEconomicsRulesOut)
def put_venue_day_economics_rules(
    venue_id: int,
    payload: VenueEconomicsRulesIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_owner_or_super_admin(db, venue_id=venue_id, user=user)
    rules = upsert_venue_economics_rules(
        db=db,
        venue_id=venue_id,
        max_expense_ratio_bps=payload.max_expense_ratio_bps,
        max_payroll_ratio_bps=payload.max_payroll_ratio_bps,
        min_revenue_per_assigned_minor=payload.min_revenue_per_assigned_minor,
        min_assigned_shift_coverage_bps=payload.min_assigned_shift_coverage_bps,
        min_profit_minor=payload.min_profit_minor,
        warn_on_draft_expenses=payload.warn_on_draft_expenses,
    )
    db.commit()
    return rules
