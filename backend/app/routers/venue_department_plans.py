from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.routers.venue_access import require_active_member_or_admin
from app.routers.venue_economics import _require_economics_view
from app.routers.venue_pay_profile_support import _require_pay_profiles_manage
from app.schemas.department_plans import DepartmentDaysBulkIn, DepartmentPlanValueIn
from app.services.finance.department_plans import bulk_day_plans, month_bounds, plan_calendar, save_plan
from app.services.financial_privacy import sanitize_financial_payload_for_user

router = APIRouter()


@router.get("/{venue_id}/department-plans/{department_id}/calendar")
def get_department_plan_calendar(
    venue_id: int, department_id: int, month: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _require_economics_view(db, venue_id=venue_id, user=user)
    return sanitize_financial_payload_for_user(user, plan_calendar(db, venue_id, department_id, month))


@router.put("/{venue_id}/department-plans/days/bulk")
def put_department_day_plans_bulk(
    venue_id: int, payload: DepartmentDaysBulkIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)
    result = bulk_day_plans(db, venue_id, payload)
    db.commit()
    return result


@router.put("/{venue_id}/department-plans/{department_id}/month")
def put_department_month_plan(
    venue_id: int,
    department_id: int,
    month: str,
    payload: DepartmentPlanValueIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)
    start, _ = month_bounds(month)
    save_plan(db, venue_id, department_id, start, payload.revenue_plan_minor, monthly=True)
    db.commit()
    return sanitize_financial_payload_for_user(user, plan_calendar(db, venue_id, department_id, month))


@router.put("/{venue_id}/department-plans/{department_id}/day")
def put_department_day_plan(
    venue_id: int,
    department_id: int,
    date: date,
    payload: DepartmentPlanValueIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_pay_profiles_manage(db, venue_id=venue_id, user=user)
    save_plan(db, venue_id, department_id, date, payload.revenue_plan_minor)
    db.commit()
    return {"date": date.isoformat(), "revenue_plan_minor": payload.revenue_plan_minor}
