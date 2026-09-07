"""Calendar plans; month and day targets intentionally remain independent."""

import calendar
import hashlib
import json
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.daily_report import DailyReport
from app.models.daily_report_value import DailyReportValue
from app.models.department import Department
from app.models.department_day_plan import DepartmentDayPlan
from app.models.department_month_plan import DepartmentMonthPlan
from app.schemas.department_plans import DepartmentDaysBulkIn


def require_department(db: Session, venue_id: int, department_id: int, *, lock: bool = False):
    query = select(Department).where(
        Department.id == department_id,
        Department.venue_id == venue_id,
        Department.is_active.is_(True),
    )
    if lock:
        query = query.with_for_update()
    department = db.scalar(query)
    if department is None:
        raise HTTPException(404, "Департамент не найден")
    return department


def positive_target(value):
    return int(value) if value is not None and int(value) > 0 else None


def month_bounds(month: str):
    try:
        start = date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise HTTPException(422, "Неверный месяц: используйте YYYY-MM") from exc
    return start, start.replace(day=calendar.monthrange(start.year, start.month)[1])


def plan_calendar(db: Session, venue_id: int, department_id: int, month: str):
    department = require_department(db, venue_id, department_id)
    start, end = month_bounds(month)
    monthly = db.scalar(
        select(DepartmentMonthPlan).where(
            DepartmentMonthPlan.venue_id == venue_id,
            DepartmentMonthPlan.department_id == department_id,
            DepartmentMonthPlan.month_start == start,
        )
    )
    plans = {
        row.target_date: row
        for row in db.scalars(
            select(DepartmentDayPlan).where(
                DepartmentDayPlan.venue_id == venue_id,
                DepartmentDayPlan.department_id == department_id,
                DepartmentDayPlan.target_date.between(start, end),
            )
        )
    }
    # A closed zero-revenue day is distinct from a day with no closed report.
    closed_dates = set(
        db.scalars(
            select(DailyReport.date).where(
                DailyReport.venue_id == venue_id,
                DailyReport.status == "CLOSED",
                DailyReport.date.between(start, end),
            )
        )
    )
    actuals = dict(
        db.execute(
            select(
                DailyReport.date,
                func.sum(DailyReportValue.value_numeric) * 100,
            )
            .join(DailyReportValue, DailyReportValue.report_id == DailyReport.id)
            .where(
                DailyReport.venue_id == venue_id,
                DailyReport.status == "CLOSED",
                DailyReport.date.between(start, end),
                DailyReportValue.kind == "DEPT",
                DailyReportValue.ref_id == department_id,
            )
            .group_by(DailyReport.date)
        ).all()
    )
    days = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        row = plans.get(day)
        target = positive_target(row.revenue_plan_minor) if row else None
        actual = int(actuals.get(day, 0)) if day in closed_dates else None
        days.append(
            {
                "date": day.isoformat(),
                "weekday": day.weekday(),
                "revenue_plan_minor": target,
                "actual_minor": actual,
                "revenue_achievement_bps": round(actual * 10000 / target) if target and actual is not None else None,
            }
        )
    target = positive_target(monthly.revenue_plan_minor) if monthly else None
    actual = sum(int(value) for value in actuals.values())
    return {
        "department_id": department_id,
        "department_title": department.title,
        "month": month,
        "revenue_plan_minor": target,
        "actual_minor": actual,
        "revenue_achievement_bps": round(actual * 10000 / target) if target else None,
        "remaining_minor": max(0, target - actual) if target else None,
        "closed_day_count": len(closed_dates),
        "days": days,
    }


def save_plan(db: Session, venue_id: int, department_id: int, day: date, value: int | None, *, monthly=False):
    require_department(db, venue_id, department_id, lock=True)
    if value is not None and value <= 0:
        raise HTTPException(422, "План должен быть положительным или не установлен")
    model = DepartmentMonthPlan if monthly else DepartmentDayPlan
    date_field = "month_start" if monthly else "target_date"
    target_date = day.replace(day=1) if monthly else day
    row = db.scalar(
        select(model).where(
            model.venue_id == venue_id,
            model.department_id == department_id,
            getattr(model, date_field) == target_date,
        )
    )
    if row is None:
        if value is None:
            return
        row = model(venue_id=venue_id, department_id=department_id, **{date_field: target_date})
        db.add(row)
    row.revenue_plan_minor = value
    row.updated_at = datetime.utcnow()
    db.flush()


def bulk_day_plans(db: Session, venue_id: int, payload: DepartmentDaysBulkIn):
    require_department(db, venue_id, payload.department_id, lock=True)
    existing = {
        row.target_date: row
        for row in db.scalars(
            select(DepartmentDayPlan).where(
                DepartmentDayPlan.venue_id == venue_id,
                DepartmentDayPlan.department_id == payload.department_id,
                DepartmentDayPlan.target_date.between(payload.date_from, payload.date_to),
            )
        )
    }
    weekdays = {row.weekday: row.revenue_plan_minor for row in payload.weekdays}
    changes, skipped, overwritten = [], 0, 0
    for offset in range((payload.date_to - payload.date_from).days + 1):
        day = payload.date_from + timedelta(days=offset)
        value = weekdays.get(day.weekday())
        if value is None:
            continue
        row = existing.get(day)
        previous = positive_target(row.revenue_plan_minor) if row else None
        if previous is not None and not payload.overwrite_existing:
            skipped += 1
            continue
        if previous == value:
            continue
        overwritten += int(previous is not None)
        changes.append((day, previous, value))
    token_data = [
        venue_id,
        payload.department_id,
        payload.overwrite_existing,
        [(day.isoformat(), old, new) for day, old, new in changes],
    ]
    token = hashlib.sha256(json.dumps(token_data).encode()).hexdigest()
    if not payload.dry_run:
        if overwritten and payload.preview_token != token:
            raise HTTPException(
                409,
                detail={
                    "code": "DEPARTMENT_PLANS_PREVIEW_REQUIRED",
                    "message": "Планы изменились. Проверьте количество дат и подтвердите перезапись ещё раз.",
                },
            )
        for day, _old, value in changes:
            row = existing.get(day)
            if row is None:
                row = DepartmentDayPlan(venue_id=venue_id, department_id=payload.department_id, target_date=day)
                db.add(row)
            row.revenue_plan_minor = value
            row.updated_at = datetime.utcnow()
        db.flush()
    return {
        "changed_count": len(changes),
        "overwritten_count": overwritten,
        "skipped_count": skipped,
        "preview_token": token,
        "dry_run": payload.dry_run,
    }
