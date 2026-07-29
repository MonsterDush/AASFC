from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    DailyReport,
    DailyReportValue,
    DayEconomicsMonthPlan,
    DayEconomicsPlan,
    DayEconomicsPlanTemplate,
    Department,
    DepartmentDayPlan,
    DepartmentMonthPlan,
    PayComponent,
    PayProfile,
    PayProfileAssignment,
    Shift,
    ShiftAssignment,
    ShiftInterval,
    User,
)
from app.services.shifts.slots import normalize_shift_slot

from .component_calculations import (
    _component_boost_department_ids,
    _component_department_ids,
    interval_duration_minutes,
)
from .payroll_types import (
    PayrollKpiMetrics,
    PayrollMemberMetrics,
    PayrollRevenueMetrics,
    PayrollVenuePlanMetrics,
    PayrollWorkedShift,
)


def _load_venue_plan_metrics(
    db: Session,
    *,
    venue_id: int,
    month_start: date,
    month_end_excl: date,
) -> PayrollVenuePlanMetrics:
    month_plan = db.execute(
        select(DayEconomicsMonthPlan.revenue_plan_minor).where(
            DayEconomicsMonthPlan.venue_id == int(venue_id),
            DayEconomicsMonthPlan.month_start == month_start,
        )
    ).scalar_one_or_none()

    weekday_templates = {
        int(row.weekday): (int(row.revenue_plan_minor) if row.revenue_plan_minor is not None else None)
        for row in db.execute(
            select(DayEconomicsPlanTemplate.weekday, DayEconomicsPlanTemplate.revenue_plan_minor).where(
                DayEconomicsPlanTemplate.venue_id == int(venue_id),
            )
        ).all()
    }
    date_overrides = {
        row.target_date: (int(row.revenue_plan_minor) if row.revenue_plan_minor is not None else None)
        for row in db.execute(
            select(DayEconomicsPlan.target_date, DayEconomicsPlan.revenue_plan_minor).where(
                DayEconomicsPlan.venue_id == int(venue_id),
                DayEconomicsPlan.target_date >= month_start,
                DayEconomicsPlan.target_date < month_end_excl,
            )
        ).all()
    }

    day_targets: dict[date, int | None] = {}
    cursor = month_start
    while cursor < month_end_excl:
        if cursor in date_overrides:
            day_targets[cursor] = date_overrides[cursor]
        elif month_plan is not None:
            day_targets[cursor] = int(month_plan) if month_plan is not None else None
        else:
            day_targets[cursor] = weekday_templates.get(cursor.weekday())
        cursor += timedelta(days=1)

    department_month_targets = {
        int(row.department_id): (int(row.revenue_plan_minor) if row.revenue_plan_minor is not None else None)
        for row in db.execute(
            select(DepartmentMonthPlan.department_id, DepartmentMonthPlan.revenue_plan_minor).where(
                DepartmentMonthPlan.venue_id == int(venue_id),
                DepartmentMonthPlan.month_start == month_start,
            )
        ).all()
    }
    department_day_targets: dict[int, dict[date, int | None]] = {}
    for row in db.execute(
        select(DepartmentDayPlan.department_id, DepartmentDayPlan.target_date, DepartmentDayPlan.revenue_plan_minor).where(
            DepartmentDayPlan.venue_id == int(venue_id),
            DepartmentDayPlan.target_date >= month_start,
            DepartmentDayPlan.target_date < month_end_excl,
        )
    ).all():
        dep_id = int(row.department_id)
        per_day = department_day_targets.setdefault(dep_id, {})
        per_day[row.target_date] = int(row.revenue_plan_minor) if row.revenue_plan_minor is not None else None

    return PayrollVenuePlanMetrics(
        month_revenue_target_minor=int(month_plan) if month_plan is not None else None,
        day_revenue_target_by_date_minor=day_targets,
        department_month_revenue_target_minor=department_month_targets,
        department_day_revenue_target_by_date_minor=department_day_targets,
    )


def _assignment_overlaps_month(*, assignment: PayProfileAssignment, month_start: date, month_end_excl: date) -> bool:
    if not assignment.is_active:
        return False
    if assignment.start_date and assignment.start_date >= month_end_excl:
        return False
    if assignment.end_date and assignment.end_date < month_start:
        return False
    return True


def _pick_latest_assignments(assignments: list[tuple[PayProfileAssignment, PayProfile, User]], *, month_start: date, month_end_excl: date) -> list[tuple[PayProfileAssignment, PayProfile, User]]:
    selected: dict[int, tuple[date, int, tuple[PayProfileAssignment, PayProfile, User]]] = {}
    for assignment, profile, member_user in assignments:
        if not profile.is_active:
            continue
        if not _assignment_overlaps_month(assignment=assignment, month_start=month_start, month_end_excl=month_end_excl):
            continue
        key = (assignment.start_date or date.min, int(assignment.id or 0))
        current = selected.get(int(assignment.member_user_id))
        if current is None or key > (current[0], current[1]):
            selected[int(assignment.member_user_id)] = (key[0], key[1], (assignment, profile, member_user))
    return [item[2] for item in selected.values()]


def _load_profile_components(db: Session, *, profile_ids: list[int]) -> dict[int, list[PayComponent]]:
    if not profile_ids:
        return {}
    rows = db.execute(
        select(PayComponent)
        .where(
            PayComponent.pay_profile_id.in_(profile_ids),
            PayComponent.is_active.is_(True),
        )
        .order_by(PayComponent.pay_profile_id.asc(), PayComponent.sort_order.asc(), PayComponent.id.asc())
    ).scalars().all()
    all_department_ids: set[int] = set()
    for component in rows:
        all_department_ids.update(_component_department_ids(component))
        all_department_ids.update(_component_boost_department_ids(component))
    department_titles_by_id: dict[int, str] = {}
    if all_department_ids:
        for dep_id, title in db.execute(
            select(Department.id, Department.title).where(Department.id.in_(sorted(all_department_ids)))
        ).all():
            department_titles_by_id[int(dep_id)] = str(title or f"#{dep_id}")

    out: dict[int, list[PayComponent]] = {}
    for component in rows:
        if department_titles_by_id:
            setattr(component, "_department_titles_by_id", department_titles_by_id)
        out.setdefault(int(component.pay_profile_id), []).append(component)
    return out


def _load_closed_report_dates(db: Session, *, venue_id: int, month_start: date, month_end_excl: date) -> set[date]:
    rows = db.execute(
        select(DailyReport.date)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= month_start,
            DailyReport.date < month_end_excl,
        )
    ).all()
    return {row[0] for row in rows if row and row[0] is not None}


def _load_closed_report_slots_by_date(db: Session, *, venue_id: int, month_start: date, month_end_excl: date) -> dict[date, set[str]]:
    rows = db.execute(
        select(DailyReport.date, DailyReport.shift_slot)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= month_start,
            DailyReport.date < month_end_excl,
        )
    ).all()
    out: dict[date, set[str]] = {}
    for report_date, shift_slot in rows:
        if report_date is None:
            continue
        out.setdefault(report_date, set()).add(normalize_shift_slot(shift_slot))
    return out



def _load_member_metrics(db: Session, *, venue_id: int, month_start: date, month_end_excl: date, member_user_ids: list[int]) -> dict[int, PayrollMemberMetrics]:
    if not member_user_ids:
        return {}

    out: dict[int, PayrollMemberMetrics] = {int(uid): PayrollMemberMetrics() for uid in member_user_ids}
    closed_slots_by_date = _load_closed_report_slots_by_date(db, venue_id=venue_id, month_start=month_start, month_end_excl=month_end_excl)
    if not closed_slots_by_date:
        return out
    closed_dates = set(closed_slots_by_date.keys())

    rows = db.execute(
        select(
            ShiftAssignment.member_user_id,
            Shift.id.label("shift_id"),
            Shift.date.label("shift_date"),
            ShiftInterval.start_time,
            ShiftInterval.end_time,
            Shift.shift_slot.label("shift_slot"),
        )
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .join(ShiftInterval, ShiftInterval.id == Shift.interval_id)
        .where(
            Shift.venue_id == int(venue_id),
            Shift.is_active.is_(True),
            Shift.date >= month_start,
            Shift.date < month_end_excl,
            Shift.date.in_(closed_dates),
            ShiftAssignment.member_user_id.in_(member_user_ids),
        )
    ).all()

    shift_sets: dict[int, set[int]] = {int(uid): set() for uid in member_user_ids}

    for row in rows:
        shift_slot = normalize_shift_slot(getattr(row, "shift_slot", None))
        if shift_slot not in closed_slots_by_date.get(row.shift_date, set()):
            continue
        member_user_id = int(row.member_user_id)
        shift_id = int(row.shift_id)
        metrics = out.setdefault(member_user_id, PayrollMemberMetrics())
        minutes = interval_duration_minutes(row.start_time, row.end_time)
        metrics.minutes_total += int(minutes)
        metrics.worked_dates.add(row.shift_date)
        member_shift_ids = shift_sets.setdefault(member_user_id, set())
        if shift_id not in member_shift_ids:
            metrics.worked_shifts.append(
                PayrollWorkedShift(
                    shift_id=shift_id,
                    shift_date=row.shift_date,
                    shift_slot=shift_slot,
                    minutes=int(minutes),
                )
            )
        member_shift_ids.add(shift_id)

    for member_user_id, shift_ids in shift_sets.items():
        out.setdefault(member_user_id, PayrollMemberMetrics()).shifts_count = len(shift_ids)
    return out



def _load_revenue_metrics(db: Session, *, venue_id: int, month_start: date, month_end_excl: date) -> PayrollRevenueMetrics:
    total_revenue_minor = int(
        db.execute(
            select(func.coalesce(func.sum(DailyReport.revenue_total), 0)).where(
                DailyReport.venue_id == int(venue_id),
                DailyReport.status == "CLOSED",
                DailyReport.date >= month_start,
                DailyReport.date < month_end_excl,
            )
        ).scalar()
        or 0
    ) * 100

    total_daily_rows = db.execute(
        select(
            DailyReport.date.label("report_date"),
            func.coalesce(func.sum(DailyReport.revenue_total), 0).label("amount"),
        )
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= month_start,
            DailyReport.date < month_end_excl,
        )
        .group_by(DailyReport.date)
    ).all()
    total_revenue_by_date_minor: dict[date, int] = {
        row.report_date: int(row.amount or 0) * 100
        for row in total_daily_rows
        if row and row.report_date is not None
    }

    dept_rows = db.execute(
        select(
            DailyReportValue.ref_id,
            func.coalesce(func.sum(DailyReportValue.value_numeric), 0).label("amount"),
        )
        .join(DailyReport, DailyReport.id == DailyReportValue.report_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= month_start,
            DailyReport.date < month_end_excl,
            DailyReportValue.kind == "DEPT",
        )
        .group_by(DailyReportValue.ref_id)
    ).all()

    department_revenue_minor: dict[int, int] = {}
    for row in dept_rows:
        department_revenue_minor[int(row.ref_id)] = int(row.amount or 0) * 100

    dept_daily_rows = db.execute(
        select(
            DailyReport.date.label("report_date"),
            DailyReportValue.ref_id,
            func.coalesce(func.sum(DailyReportValue.value_numeric), 0).label("amount"),
        )
        .join(DailyReport, DailyReport.id == DailyReportValue.report_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= month_start,
            DailyReport.date < month_end_excl,
            DailyReportValue.kind == "DEPT",
        )
        .group_by(DailyReport.date, DailyReportValue.ref_id)
    ).all()

    department_revenue_by_date_minor: dict[int, dict[date, int]] = {}
    for row in dept_daily_rows:
        dep_id = int(row.ref_id)
        by_date = department_revenue_by_date_minor.setdefault(dep_id, {})
        by_date[row.report_date] = int(row.amount or 0) * 100

    return PayrollRevenueMetrics(
        total_revenue_minor=total_revenue_minor,
        total_revenue_by_date_minor=total_revenue_by_date_minor,
        department_revenue_minor=department_revenue_minor,
        department_revenue_by_date_minor=department_revenue_by_date_minor,
    )



def _load_kpi_metrics(db: Session, *, venue_id: int, month_start: date, month_end_excl: date) -> PayrollKpiMetrics:
    rows = db.execute(
        select(
            DailyReportValue.ref_id,
            func.coalesce(func.sum(DailyReportValue.value_numeric), 0).label("value_total"),
        )
        .join(DailyReport, DailyReport.id == DailyReportValue.report_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= month_start,
            DailyReport.date < month_end_excl,
            DailyReportValue.kind == "KPI",
        )
        .group_by(DailyReportValue.ref_id)
    ).all()

    totals_by_metric_id: dict[int, int] = {}
    for row in rows:
        totals_by_metric_id[int(row.ref_id)] = int(row.value_total or 0)

    slot_rows = db.execute(
        select(
            DailyReportValue.ref_id,
            DailyReport.date,
            DailyReport.shift_slot,
            func.coalesce(func.sum(DailyReportValue.value_numeric), 0).label("value_total"),
        )
        .join(DailyReport, DailyReport.id == DailyReportValue.report_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= month_start,
            DailyReport.date < month_end_excl,
            DailyReportValue.kind == "KPI",
        )
        .group_by(DailyReportValue.ref_id, DailyReport.date, DailyReport.shift_slot)
    ).all()
    values_by_metric_date_slot: dict[int, dict[tuple[date, str], int]] = {}
    for row in slot_rows:
        metric_values = values_by_metric_date_slot.setdefault(int(row.ref_id), {})
        report_key = (row.date, normalize_shift_slot(row.shift_slot))
        metric_values[report_key] = int(row.value_total or 0)
    return PayrollKpiMetrics(
        totals_by_metric_id=totals_by_metric_id,
        values_by_metric_date_slot=values_by_metric_date_slot,
    )


def _sum_kpi_for_worked_shifts(
    kpi_metrics: PayrollKpiMetrics,
    *,
    metric_id: int,
    metrics: PayrollMemberMetrics,
) -> int:
    values = kpi_metrics.values_by_metric_date_slot.get(int(metric_id), {})
    report_keys = {
        (shift.shift_date, normalize_shift_slot(shift.shift_slot))
        for shift in metrics.worked_shifts
    }
    return int(sum(int(values.get(key, 0) or 0) for key in report_keys))


def _sum_department_revenue_for_worked_dates(
    department_revenue_by_date_minor: dict[date, int] | None,
    worked_dates: set[date] | None,
) -> int:
    if not department_revenue_by_date_minor or not worked_dates:
        return 0
    return int(sum(int(department_revenue_by_date_minor.get(day) or 0) for day in worked_dates))
