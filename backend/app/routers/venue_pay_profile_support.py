from __future__ import annotations

from datetime import datetime, date
import json
from fastapi import HTTPException
from sqlalchemy import select
import sqlalchemy as sa
from sqlalchemy.orm import Session
from app.core.permission_codes import parse_permission_codes, normalize_known_permission_codes
from app.services.payroll.calculator import (
    BASE_SCOPE_FULL_PERIOD,
    BASE_SCOPE_WORKED_DATES,
    BOOST_RECALC_EXCESS_ONLY,
    BOOST_RECALC_REPLACE_ALL,
    BOOST_SOURCE_DEPARTMENT_DAY_PLAN,
    BOOST_SOURCE_DEPARTMENT_MONTH_PLAN,
    BOOST_SOURCE_KPI_METRIC,
    BOOST_SOURCE_NONE,
    BOOST_SOURCE_VENUE_DAY_PLAN,
    BOOST_SOURCE_VENUE_MONTH_PLAN,
    MINIMUM_GUARANTEE_DAY,
    MINIMUM_GUARANTEE_MONTH,
    MINIMUM_GUARANTEE_SHIFT,
)
from app.services.payroll.payroll_types import KPI_CALCULATION_FIXED, KPI_CALCULATION_PERCENT
from app.routers.venue_access import (
    _is_owner_or_super_admin,
)
from app.models.user import User
from app.models.department import Department
from app.models.pay_profile import PayProfile
from app.models.pay_profile_assignment import PayProfileAssignment
from app.models.pay_component import PayComponent
from app.auth.venue_permissions import require_venue_permission

from app.routers.venue_common import (
    BASE_SCOPE_TITLES,
    BOOST_RECALC_TITLES,
    BOOST_SOURCE_TITLES,
    MINIMUM_GUARANTEE_SCOPE_TITLES,
)
from app.routers.venue_membership_support import _build_user_auth_snapshot_map, _display_name


def _parse_position_permission_codes(raw: str | None) -> list[str]:
    return parse_permission_codes(raw)


def _normalize_permission_codes(db: Session, codes: list[str] | None) -> list[str]:
    return normalize_known_permission_codes(db, codes)


def _require_pay_profiles_view(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAY_PROFILES_VIEW")
        return
    except HTTPException:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAY_PROFILES_MANAGE")


def _require_pay_profiles_manage(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAY_PROFILES_MANAGE")


def _require_payroll_view(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYROLL_VIEW")
        return
    except HTTPException:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYROLL_CALCULATE")


def _require_payroll_calculate(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYROLL_CALCULATE")


def _parse_json_text(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _get_pay_profile_or_404(db: Session, *, venue_id: int, profile_id: int) -> PayProfile:
    obj = db.execute(
        select(PayProfile).where(PayProfile.id == profile_id, PayProfile.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Pay profile not found")
    return obj


def _get_pay_profile_assignment_or_404(db: Session, *, venue_id: int, assignment_id: int) -> PayProfileAssignment:
    obj = db.execute(
        select(PayProfileAssignment).where(
            PayProfileAssignment.id == assignment_id,
            PayProfileAssignment.venue_id == venue_id,
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Pay profile assignment not found")
    return obj


def _get_member_active_pay_profile_assignment(
    db: Session,
    *,
    venue_id: int,
    member_user_id: int,
    on_date: date | None = None,
) -> tuple[PayProfileAssignment, PayProfile] | tuple[None, None]:
    target_date = on_date or date.today()
    row = db.execute(
        select(PayProfileAssignment, PayProfile)
        .join(PayProfile, PayProfile.id == PayProfileAssignment.pay_profile_id)
        .where(
            PayProfileAssignment.venue_id == int(venue_id),
            PayProfileAssignment.member_user_id == int(member_user_id),
            PayProfileAssignment.is_active.is_(True),
            PayProfile.is_active.is_(True),
            sa.or_(PayProfileAssignment.start_date.is_(None), PayProfileAssignment.start_date <= target_date),
            sa.or_(PayProfileAssignment.end_date.is_(None), PayProfileAssignment.end_date >= target_date),
        )
        .order_by(
            PayProfileAssignment.start_date.desc().nullslast(),
            PayProfileAssignment.updated_at.desc().nullslast(),
            PayProfileAssignment.id.desc(),
        )
    ).first()
    if row is None:
        return None, None
    return row[0], row[1]


def _sync_member_pay_profile_assignment(
    db: Session,
    *,
    venue_id: int,
    member_user_id: int,
    pay_profile_id: int | None,
) -> tuple[PayProfileAssignment | None, PayProfile | None]:
    today = date.today()
    current_assignment, current_profile = _get_member_active_pay_profile_assignment(
        db, venue_id=venue_id, member_user_id=member_user_id, on_date=today
    )

    target_profile = None
    target_profile_id = int(pay_profile_id) if pay_profile_id else None
    if target_profile_id is not None:
        target_profile = _get_pay_profile_or_404(db, venue_id=venue_id, profile_id=target_profile_id)

    if (
        target_profile_id is not None
        and current_assignment is not None
        and int(current_assignment.pay_profile_id) == target_profile_id
    ):
        return current_assignment, current_profile

    if current_assignment is not None:
        if current_assignment.start_date is None and current_assignment.end_date is None:
            db.delete(current_assignment)
        else:
            if current_assignment.start_date and current_assignment.start_date > today:
                current_assignment.is_active = False
                current_assignment.end_date = current_assignment.start_date
            else:
                current_assignment.end_date = today
                current_assignment.is_active = False
            current_assignment.updated_at = datetime.utcnow()
            db.add(current_assignment)

    if target_profile is None:
        return None, None

    assignment = PayProfileAssignment(
        venue_id=int(venue_id),
        pay_profile_id=int(target_profile.id),
        member_user_id=int(member_user_id),
        start_date=today,
        end_date=None,
        is_active=True,
        updated_at=datetime.utcnow(),
    )
    db.add(assignment)
    db.flush()
    return assignment, target_profile


def _get_pay_component_or_404(db: Session, *, venue_id: int, component_id: int) -> PayComponent:
    obj = db.execute(
        select(PayComponent).where(PayComponent.id == component_id, PayComponent.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Pay component not found")
    return obj


def _normalize_int_ids(value: object) -> list[int]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except Exception:
            return []
    if not isinstance(value, list):
        return []
    result: list[int] = []
    seen: set[int] = set()
    for item in value:
        try:
            item_id = int(item)
        except Exception:
            continue
        if item_id <= 0 or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item_id)
    return result


def _dump_int_ids(value: object) -> str | None:
    ids = _normalize_int_ids(value)
    return json.dumps(ids, ensure_ascii=False) if ids else None


def _component_department_ids(component: PayComponent) -> list[int]:
    ids = _normalize_int_ids(getattr(component, "department_ids_json", None))
    legacy_id = int(getattr(component, "department_id", 0) or 0)
    if legacy_id > 0 and legacy_id not in ids:
        ids.insert(0, legacy_id)
    return ids


def _component_boost_department_ids(component: PayComponent) -> list[int]:
    ids = _normalize_int_ids(getattr(component, "boost_department_ids_json", None))
    legacy_id = int(getattr(component, "boost_department_id", 0) or 0)
    if legacy_id > 0 and legacy_id not in ids:
        ids.insert(0, legacy_id)
    return ids


def _department_titles_for_ids(db_departments: list[Department] | None, ids: list[int]) -> list[str]:
    if not ids:
        return []
    by_id = {int(dep.id): dep.title for dep in (db_departments or []) if dep is not None}
    return [str(by_id.get(int(dep_id)) or f"#{dep_id}") for dep_id in ids]


def _normalize_minimum_guarantee_scope(value: object) -> str:
    raw = str(value or "").strip().upper()
    if raw == MINIMUM_GUARANTEE_DAY:
        return MINIMUM_GUARANTEE_DAY
    if raw == MINIMUM_GUARANTEE_SHIFT:
        return MINIMUM_GUARANTEE_SHIFT
    return MINIMUM_GUARANTEE_MONTH


def _ensure_department_ids_in_venue(db: Session, *, venue_id: int, ids: list[int], detail: str) -> None:
    normalized = _normalize_int_ids(ids)
    if not normalized:
        return
    found = set(
        int(item)
        for item in db.execute(
            select(Department.id).where(
                Department.venue_id == int(venue_id),
                Department.id.in_(normalized),
            )
        )
        .scalars()
        .all()
    )
    missing = [dep_id for dep_id in normalized if dep_id not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f"{detail}: {', '.join(str(dep_id) for dep_id in missing)}")


def _effective_component_base_scope(component: PayComponent) -> str:
    raw = str(getattr(component, "base_scope", "") or "").strip().upper()
    if raw in {BASE_SCOPE_FULL_PERIOD, BASE_SCOPE_WORKED_DATES}:
        return raw
    component_type = str(getattr(component, "component_type", "") or "").strip().upper()
    if component_type == "PERCENT_DEPARTMENT_REVENUE":
        return BASE_SCOPE_WORKED_DATES
    return BASE_SCOPE_FULL_PERIOD


def _effective_component_boost_source_type(component: PayComponent) -> str:
    raw = str(getattr(component, "boost_source_type", "") or "").strip().upper()
    if raw in {
        BOOST_SOURCE_NONE,
        BOOST_SOURCE_VENUE_MONTH_PLAN,
        BOOST_SOURCE_VENUE_DAY_PLAN,
        BOOST_SOURCE_DEPARTMENT_MONTH_PLAN,
        BOOST_SOURCE_DEPARTMENT_DAY_PLAN,
        BOOST_SOURCE_KPI_METRIC,
    }:
        return raw
    return BOOST_SOURCE_NONE


def _effective_component_boost_recalc_mode(component: PayComponent) -> str:
    raw = str(getattr(component, "boost_recalc_mode", "") or "").strip().upper()
    if raw == BOOST_RECALC_EXCESS_ONLY:
        return BOOST_RECALC_EXCESS_ONLY
    return BOOST_RECALC_REPLACE_ALL


def _serialize_pay_component(component: PayComponent) -> dict:
    department = getattr(component, "department", None)
    department_ids = _component_department_ids(component)
    boost_department_ids = _component_boost_department_ids(component)
    kpi_metric = getattr(component, "kpi_metric", None)
    boost_department = getattr(component, "boost_department", None)
    boost_kpi_metric = getattr(component, "boost_kpi_metric", None)
    effective_base_scope = _effective_component_base_scope(component)
    effective_boost_source_type = _effective_component_boost_source_type(component)
    effective_boost_recalc_mode = _effective_component_boost_recalc_mode(component)
    return {
        "id": int(component.id),
        "pay_profile_id": int(component.pay_profile_id),
        "component_type": component.component_type,
        "title": component.title,
        "amount_minor": component.amount_minor,
        "rate_minor": component.rate_minor,
        "percent_bps": component.percent_bps,
        "department_id": component.department_id,
        "department_ids": department_ids,
        "department_title": department.title if department is not None else None,
        "department_titles": [department.title]
        if department is not None and int(component.department_id or 0) in department_ids
        else [],
        "kpi_metric_id": component.kpi_metric_id,
        "kpi_metric_title": kpi_metric.title if kpi_metric is not None else None,
        "threshold_value": component.threshold_value,
        "steps": _parse_json_text(component.steps_json),
        "kpi_calculation_mode": str(component.kpi_calculation_mode or KPI_CALCULATION_FIXED).upper(),
        "salary_accrual_day": component.salary_accrual_day,
        "base_scope": component.base_scope,
        "effective_base_scope": effective_base_scope,
        "effective_base_scope_title": BASE_SCOPE_TITLES.get(effective_base_scope, effective_base_scope),
        "boost_enabled": bool(component.boost_enabled),
        "boost_percent_bps": component.boost_percent_bps,
        "boost_source_type": component.boost_source_type,
        "effective_boost_source_type": effective_boost_source_type,
        "effective_boost_source_title": BOOST_SOURCE_TITLES.get(
            effective_boost_source_type, effective_boost_source_type
        ),
        "boost_recalc_mode": component.boost_recalc_mode,
        "effective_boost_recalc_mode": effective_boost_recalc_mode,
        "effective_boost_recalc_mode_title": BOOST_RECALC_TITLES.get(
            effective_boost_recalc_mode, effective_boost_recalc_mode
        ),
        "boost_department_id": component.boost_department_id,
        "boost_department_ids": boost_department_ids,
        "boost_department_title": boost_department.title if boost_department is not None else None,
        "boost_department_titles": [boost_department.title]
        if boost_department is not None and int(component.boost_department_id or 0) in boost_department_ids
        else [],
        "boost_kpi_metric_id": component.boost_kpi_metric_id,
        "boost_kpi_metric_title": boost_kpi_metric.title if boost_kpi_metric is not None else None,
        "boost_threshold_value": component.boost_threshold_value,
        "minimum_guarantee_minor": component.minimum_guarantee_minor,
        "minimum_guarantee_scope": component.minimum_guarantee_scope,
        "effective_minimum_guarantee_scope": _normalize_minimum_guarantee_scope(component.minimum_guarantee_scope),
        "effective_minimum_guarantee_scope_title": MINIMUM_GUARANTEE_SCOPE_TITLES.get(
            _normalize_minimum_guarantee_scope(component.minimum_guarantee_scope), "за месяц"
        ),
        "maximum_cap_minor": component.maximum_cap_minor,
        "sort_order": int(component.sort_order or 0),
        "is_active": bool(component.is_active),
    }


def _validate_pay_component_fields(
    *,
    component_type: str,
    amount_minor: int | None,
    rate_minor: int | None,
    percent_bps: int | None,
    department_id: int | None,
    department_ids: list[int] | None = None,
    kpi_metric_id: int | None = None,
    threshold_value: int | None = None,
    steps_json: dict | list | None = None,
    kpi_calculation_mode: str | None = None,
    kpi_metric_unit: str | None = None,
    salary_accrual_day: int | None = None,
    base_scope: str | None = None,
    boost_enabled: bool = False,
    boost_percent_bps: int | None = None,
    boost_source_type: str | None = None,
    boost_recalc_mode: str | None = None,
    boost_department_id: int | None = None,
    boost_department_ids: list[int] | None = None,
    boost_kpi_metric_id: int | None = None,
    boost_threshold_value: int | None = None,
    minimum_guarantee_minor: int | None = None,
    minimum_guarantee_scope: str | None = None,
    maximum_cap_minor: int | None = None,
) -> None:
    component_type = str(component_type or "").strip().upper()
    normalized_base_scope = str(base_scope or "").strip().upper() if base_scope is not None else None
    normalized_kpi_calculation_mode = str(kpi_calculation_mode or KPI_CALCULATION_FIXED).strip().upper()
    normalized_boost_source_type = (
        str(boost_source_type or "").strip().upper() if boost_source_type is not None else BOOST_SOURCE_NONE
    )
    normalized_boost_recalc_mode = (
        str(boost_recalc_mode or "").strip().upper() if boost_recalc_mode is not None else BOOST_RECALC_REPLACE_ALL
    )
    is_percent_component = component_type in {"PERCENT_TOTAL_REVENUE", "PERCENT_DEPARTMENT_REVENUE"}
    normalized_department_ids = _normalize_int_ids(department_ids)
    normalized_boost_department_ids = _normalize_int_ids(boost_department_ids)
    raw_minimum_scope = str(minimum_guarantee_scope or "").strip().upper()
    if component_type == "MINIMUM_PAYOUT":
        if minimum_guarantee_scope is not None and raw_minimum_scope not in {
            MINIMUM_GUARANTEE_MONTH,
            MINIMUM_GUARANTEE_SHIFT,
            MINIMUM_GUARANTEE_DAY,
        }:
            raise HTTPException(
                status_code=400, detail="minimum_guarantee_scope must be MONTH or SHIFT for MINIMUM_PAYOUT"
            )
    elif minimum_guarantee_scope is not None and raw_minimum_scope not in {
        MINIMUM_GUARANTEE_MONTH,
        MINIMUM_GUARANTEE_DAY,
    }:
        raise HTTPException(status_code=400, detail="minimum_guarantee_scope must be MONTH or DAY")
    if (
        minimum_guarantee_minor is not None
        and maximum_cap_minor is not None
        and minimum_guarantee_minor > maximum_cap_minor
    ):
        raise HTTPException(status_code=400, detail="minimum_guarantee_minor must be <= maximum_cap_minor")
    if component_type == "SALARY_FIXED_MONTH":
        if amount_minor is None:
            raise HTTPException(status_code=400, detail="amount_minor is required for SALARY_FIXED_MONTH")
        if salary_accrual_day is not None and not 1 <= int(salary_accrual_day) <= 31:
            raise HTTPException(status_code=400, detail="salary_accrual_day must be between 1 and 31")
        return
    if salary_accrual_day is not None:
        raise HTTPException(status_code=400, detail="salary_accrual_day is supported only for SALARY_FIXED_MONTH")
    if component_type == "SALARY_HOURLY":
        if rate_minor is None:
            raise HTTPException(status_code=400, detail="rate_minor is required for SALARY_HOURLY")
        return
    if component_type == "SALARY_PER_SHIFT":
        if amount_minor is None:
            raise HTTPException(status_code=400, detail="amount_minor is required for SALARY_PER_SHIFT")
        return
    if component_type == "MINIMUM_PAYOUT":
        if amount_minor is None:
            raise HTTPException(status_code=400, detail="amount_minor is required for MINIMUM_PAYOUT")
        return
    if component_type == "PERCENT_TOTAL_REVENUE":
        if percent_bps is None:
            raise HTTPException(status_code=400, detail="percent_bps is required for PERCENT_TOTAL_REVENUE")
    if component_type == "PERCENT_DEPARTMENT_REVENUE":
        if percent_bps is None:
            raise HTTPException(status_code=400, detail="percent_bps is required for PERCENT_DEPARTMENT_REVENUE")
        if department_id is None and not normalized_department_ids:
            raise HTTPException(
                status_code=400, detail="department_id or department_ids is required for PERCENT_DEPARTMENT_REVENUE"
            )
    if is_percent_component:
        if normalized_base_scope is not None and normalized_base_scope not in {
            BASE_SCOPE_FULL_PERIOD,
            BASE_SCOPE_WORKED_DATES,
        }:
            raise HTTPException(status_code=400, detail="base_scope must be FULL_PERIOD or WORKED_DATES")
        if boost_enabled:
            if boost_percent_bps is None:
                raise HTTPException(status_code=400, detail="boost_percent_bps is required when boost is enabled")
            if percent_bps is not None and boost_percent_bps < percent_bps:
                raise HTTPException(status_code=400, detail="boost_percent_bps must be >= percent_bps")
            if normalized_boost_source_type not in {
                BOOST_SOURCE_VENUE_MONTH_PLAN,
                BOOST_SOURCE_VENUE_DAY_PLAN,
                BOOST_SOURCE_DEPARTMENT_MONTH_PLAN,
                BOOST_SOURCE_DEPARTMENT_DAY_PLAN,
                BOOST_SOURCE_KPI_METRIC,
            }:
                raise HTTPException(status_code=400, detail="boost_source_type is required when boost is enabled")
            if normalized_boost_recalc_mode not in {BOOST_RECALC_REPLACE_ALL, BOOST_RECALC_EXCESS_ONLY}:
                raise HTTPException(status_code=400, detail="boost_recalc_mode must be REPLACE_ALL or EXCESS_ONLY")
            if normalized_boost_source_type == BOOST_SOURCE_KPI_METRIC:
                if boost_kpi_metric_id is None:
                    raise HTTPException(status_code=400, detail="boost_kpi_metric_id is required for KPI boost")
                if boost_threshold_value is None:
                    raise HTTPException(status_code=400, detail="boost_threshold_value is required for KPI boost")
                if normalized_boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY:
                    raise HTTPException(status_code=400, detail="EXCESS_ONLY is not supported for KPI boost")
            if (
                normalized_boost_source_type in {BOOST_SOURCE_DEPARTMENT_MONTH_PLAN, BOOST_SOURCE_DEPARTMENT_DAY_PLAN}
                and boost_department_id is None
                and not normalized_boost_department_ids
            ):
                raise HTTPException(
                    status_code=400,
                    detail="boost_department_id or boost_department_ids is required for department plan boost",
                )
        return
    if component_type == "KPI_BONUS":
        if kpi_metric_id is None:
            raise HTTPException(status_code=400, detail="kpi_metric_id is required for KPI_BONUS")
        if normalized_kpi_calculation_mode not in {KPI_CALCULATION_FIXED, KPI_CALCULATION_PERCENT}:
            raise HTTPException(status_code=400, detail="kpi_calculation_mode must be FIXED or PERCENT")
        if normalized_kpi_calculation_mode == KPI_CALCULATION_PERCENT:
            if str(kpi_metric_unit or "").strip().upper() != "RUB":
                raise HTTPException(status_code=400, detail="PERCENT KPI bonus requires a KPI metric with RUB unit")
            if percent_bps is None:
                raise HTTPException(status_code=400, detail="percent_bps is required for percentage KPI_BONUS")
            if steps_json:
                raise HTTPException(status_code=400, detail="steps_json is not supported for percentage KPI_BONUS")
            return
        has_steps = False
        if isinstance(steps_json, list):
            has_steps = len(steps_json) > 0
        elif isinstance(steps_json, dict):
            raw_steps = steps_json.get("steps") if steps_json is not None else None
            has_steps = isinstance(raw_steps, list) and len(raw_steps) > 0
        if has_steps:
            return
        if amount_minor is None:
            raise HTTPException(status_code=400, detail="amount_minor is required for KPI_BONUS without steps_json")
        return


def _serialize_pay_profile_assignment(
    assignment: PayProfileAssignment,
    member: User | None = None,
    *,
    auth_snapshot: dict | None = None,
) -> dict:
    member_obj = None
    if member is not None:
        phone = str((auth_snapshot or {}).get("phone") or "").strip() or None
        member_obj = {
            "user_id": int(member.id),
            "tg_user_id": member.tg_user_id,
            "tg_username": member.tg_username,
            "full_name": member.full_name,
            "short_name": member.short_name,
            "phone": phone,
            "display_name": _display_name(
                short_name=member.short_name,
                full_name=member.full_name,
                tg_username=member.tg_username,
                phone=phone,
                user_id=int(member.id),
            ),
        }
    return {
        "id": int(assignment.id),
        "pay_profile_id": int(assignment.pay_profile_id),
        "member_user_id": int(assignment.member_user_id),
        "start_date": assignment.start_date.isoformat() if assignment.start_date else None,
        "end_date": assignment.end_date.isoformat() if assignment.end_date else None,
        "is_active": bool(assignment.is_active),
        "member": member_obj,
    }


def _serialize_pay_profile(
    profile: PayProfile, *, components_count: int | None = None, assignments_count: int | None = None
) -> dict:
    payload = {
        "id": int(profile.id),
        "venue_id": int(profile.venue_id),
        "title": profile.title,
        "description": profile.description,
        "is_active": bool(profile.is_active),
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
    if components_count is not None:
        payload["components_count"] = int(components_count)
    if assignments_count is not None:
        payload["assignments_count"] = int(assignments_count)
    return payload


def _load_pay_profile_detail(db: Session, *, venue_id: int, profile_id: int) -> dict:
    profile = _get_pay_profile_or_404(db, venue_id=venue_id, profile_id=profile_id)
    components = (
        db.execute(
            select(PayComponent)
            .where(PayComponent.venue_id == venue_id, PayComponent.pay_profile_id == profile_id)
            .order_by(PayComponent.sort_order.asc(), PayComponent.id.asc())
        )
        .scalars()
        .all()
    )
    assignment_rows = db.execute(
        select(PayProfileAssignment, User)
        .join(User, User.id == PayProfileAssignment.member_user_id)
        .where(
            PayProfileAssignment.venue_id == venue_id,
            PayProfileAssignment.pay_profile_id == profile_id,
        )
        .order_by(
            PayProfileAssignment.is_active.desc(),
            PayProfileAssignment.start_date.desc(),
            PayProfileAssignment.id.desc(),
        )
    ).all()
    member_auth_map = _build_user_auth_snapshot_map(db, [int(member.id) for _assignment, member in assignment_rows])
    payload = _serialize_pay_profile(profile)
    payload["components"] = [_serialize_pay_component(component) for component in components]
    payload["assignments"] = [
        _serialize_pay_profile_assignment(
            assignment,
            member=member,
            auth_snapshot=member_auth_map.get(int(member.id)),
        )
        for assignment, member in assignment_rows
    ]
    return payload
