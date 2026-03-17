from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import json

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import DailyReport, DailyReportValue, FinanceEntry, PayComponent, PayProfile, PayProfileAssignment, PayrollLine, PayrollRun, Shift, ShiftAssignment, ShiftInterval, User
from app.services.finance.ledger import create_finance_entry, delete_finance_entries_for_source


PAY_COMPONENT_TYPES = {
    "SALARY_FIXED_MONTH",
    "SALARY_HOURLY",
    "SALARY_PER_SHIFT",
    "PERCENT_TOTAL_REVENUE",
    "PERCENT_DEPARTMENT_REVENUE",
    "KPI_BONUS",
}


@dataclass
class PayrollMemberMetrics:
    minutes_total: int = 0
    shifts_count: int = 0


@dataclass
class PayrollRevenueMetrics:
    total_revenue_minor: int = 0
    department_revenue_minor: dict[int, int] = field(default_factory=dict)


@dataclass
class PayrollCalculationResult:
    run: PayrollRun
    lines: list[PayrollLine]


def parse_month_start(month: str) -> date:
    try:
        y_s, m_s = str(month or "").split("-")
        y = int(y_s)
        m = int(m_s)
        return date(y, m, 1)
    except Exception as exc:
        raise ValueError("Bad month format, expected YYYY-MM") from exc


def next_month_start(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def interval_duration_minutes(start_time: time, end_time: time) -> int:
    start_dt = datetime.combine(date(2000, 1, 1), start_time)
    end_dt = datetime.combine(date(2000, 1, 1), end_time)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return int((end_dt - start_dt).total_seconds() // 60)


def calculate_component_amount_minor(
    component: PayComponent,
    *,
    minutes_total: int,
    shifts_count: int,
    total_revenue_minor: int = 0,
    department_revenue_minor: int = 0,
) -> int:
    component_type = str(component.component_type or "").strip().upper()
    if component_type not in PAY_COMPONENT_TYPES:
        raise ValueError(f"Unsupported pay component type: {component.component_type}")

    if component_type == "SALARY_FIXED_MONTH":
        return int(component.amount_minor or 0)

    if component_type == "SALARY_HOURLY":
        rate_minor = int(component.rate_minor or 0)
        return int((rate_minor * int(minutes_total) + 30) // 60)

    if component_type == "SALARY_PER_SHIFT":
        amount_minor = int(component.amount_minor or 0)
        return int(amount_minor * int(shifts_count))

    if component_type == "PERCENT_TOTAL_REVENUE":
        percent_bps = int(component.percent_bps or 0)
        return int((int(total_revenue_minor) * percent_bps + 5000) // 10000)

    if component_type == "PERCENT_DEPARTMENT_REVENUE":
        percent_bps = int(component.percent_bps or 0)
        return int((int(department_revenue_minor) * percent_bps + 5000) // 10000)

    # 5.3 KPI bonuses are scaffolded in schema, but are not calculated yet.
    return 0


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
    out: dict[int, list[PayComponent]] = {}
    for component in rows:
        out.setdefault(int(component.pay_profile_id), []).append(component)
    return out


def _load_member_metrics(db: Session, *, venue_id: int, month_start: date, month_end_excl: date, member_user_ids: list[int]) -> dict[int, PayrollMemberMetrics]:
    if not member_user_ids:
        return {}

    rows = db.execute(
        select(
            ShiftAssignment.member_user_id,
            Shift.id.label("shift_id"),
            ShiftInterval.start_time,
            ShiftInterval.end_time,
        )
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .join(ShiftInterval, ShiftInterval.id == Shift.interval_id)
        .where(
            Shift.venue_id == int(venue_id),
            Shift.is_active.is_(True),
            Shift.date >= month_start,
            Shift.date < month_end_excl,
            ShiftAssignment.member_user_id.in_(member_user_ids),
        )
    ).all()

    out: dict[int, PayrollMemberMetrics] = {int(uid): PayrollMemberMetrics() for uid in member_user_ids}
    shift_sets: dict[int, set[int]] = {int(uid): set() for uid in member_user_ids}

    for row in rows:
        member_user_id = int(row.member_user_id)
        metrics = out.setdefault(member_user_id, PayrollMemberMetrics())
        metrics.minutes_total += interval_duration_minutes(row.start_time, row.end_time)
        shift_sets.setdefault(member_user_id, set()).add(int(row.shift_id))

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

    return PayrollRevenueMetrics(
        total_revenue_minor=total_revenue_minor,
        department_revenue_minor=department_revenue_minor,
    )


def calculate_payroll_for_month(
    *,
    db: Session,
    venue_id: int,
    month: str,
    calculated_by_user_id: int | None = None,
) -> PayrollCalculationResult:
    month_start = parse_month_start(month)
    month_end_excl = next_month_start(month_start)

    run = db.execute(
        select(PayrollRun).where(
            PayrollRun.venue_id == int(venue_id),
            PayrollRun.period_month == month_start,
        )
    ).scalar_one_or_none()
    if run is None:
        run = PayrollRun(
            venue_id=int(venue_id),
            period_month=month_start,
            calculated_by_user_id=int(calculated_by_user_id) if calculated_by_user_id is not None else None,
            calculated_at=datetime.utcnow(),
            total_amount_minor=0,
            lines_count=0,
        )
        db.add(run)
        db.flush()
    else:
        run.calculated_by_user_id = int(calculated_by_user_id) if calculated_by_user_id is not None else run.calculated_by_user_id
        run.calculated_at = datetime.utcnow()
        db.execute(delete(PayrollLine).where(PayrollLine.payroll_run_id == int(run.id)))
        delete_finance_entries_for_source(db=db, source_type="payroll_run", source_id=int(run.id))
        db.flush()

    assignment_rows = db.execute(
        select(PayProfileAssignment, PayProfile, User)
        .join(PayProfile, PayProfile.id == PayProfileAssignment.pay_profile_id)
        .join(User, User.id == PayProfileAssignment.member_user_id)
        .where(PayProfileAssignment.venue_id == int(venue_id))
    ).all()
    selected_assignments = _pick_latest_assignments(list(assignment_rows), month_start=month_start, month_end_excl=month_end_excl)

    member_user_ids = [int(assignment.member_user_id) for assignment, _profile, _user in selected_assignments]
    profile_ids = sorted({int(profile.id) for _assignment, profile, _user in selected_assignments})
    components_by_profile = _load_profile_components(db, profile_ids=profile_ids)
    metrics_by_member = _load_member_metrics(
        db,
        venue_id=int(venue_id),
        month_start=month_start,
        month_end_excl=month_end_excl,
        member_user_ids=member_user_ids,
    )
    revenue_metrics = _load_revenue_metrics(
        db,
        venue_id=int(venue_id),
        month_start=month_start,
        month_end_excl=month_end_excl,
    )

    lines: list[PayrollLine] = []
    total_amount_minor = 0

    for assignment, profile, member_user in selected_assignments:
        metrics = metrics_by_member.get(int(member_user.id), PayrollMemberMetrics())
        components = components_by_profile.get(int(profile.id), [])
        breakdown_items: list[dict] = []
        line_total = 0

        for component in components:
            component_type = str(component.component_type or "").strip().upper()
            department_base_minor = 0
            if component.department_id is not None:
                department_base_minor = int(revenue_metrics.department_revenue_minor.get(int(component.department_id), 0))
            amount_minor = calculate_component_amount_minor(
                component,
                minutes_total=int(metrics.minutes_total),
                shifts_count=int(metrics.shifts_count),
                total_revenue_minor=int(revenue_metrics.total_revenue_minor),
                department_revenue_minor=int(department_base_minor),
            )
            breakdown_item = {
                "component_id": int(component.id),
                "component_type": component.component_type,
                "title": component.title,
                "amount_minor": int(amount_minor),
                "minutes_total": int(metrics.minutes_total),
                "hours_total": round(int(metrics.minutes_total) / 60.0, 2),
                "shifts_count": int(metrics.shifts_count),
            }
            if component_type == "PERCENT_TOTAL_REVENUE":
                breakdown_item["percent_bps"] = int(component.percent_bps or 0)
                breakdown_item["base_amount_minor"] = int(revenue_metrics.total_revenue_minor)
            elif component_type == "PERCENT_DEPARTMENT_REVENUE":
                breakdown_item["percent_bps"] = int(component.percent_bps or 0)
                breakdown_item["department_id"] = int(component.department_id) if component.department_id is not None else None
                breakdown_item["department_title"] = component.department.title if getattr(component, "department", None) is not None else None
                breakdown_item["base_amount_minor"] = int(department_base_minor)
            breakdown_items.append(breakdown_item)
            line_total += int(amount_minor)

        breakdown_payload = {
            "member_user_id": int(member_user.id),
            "member_name": member_user.short_name or member_user.full_name or member_user.tg_username or f"user #{member_user.id}",
            "pay_profile_id": int(profile.id),
            "pay_profile_title": profile.title,
            "metrics": {
                "minutes_total": int(metrics.minutes_total),
                "hours_total": round(int(metrics.minutes_total) / 60.0, 2),
                "shifts_count": int(metrics.shifts_count),
            },
            "revenue_metrics": {
                "total_revenue_minor": int(revenue_metrics.total_revenue_minor),
            },
            "components": breakdown_items,
        }

        line = PayrollLine(
            payroll_run_id=int(run.id),
            venue_id=int(venue_id),
            member_user_id=int(member_user.id),
            pay_profile_id=int(profile.id),
            amount_minor=int(line_total),
            breakdown_json=json.dumps(breakdown_payload, ensure_ascii=False),
        )
        db.add(line)
        lines.append(line)
        total_amount_minor += int(line_total)

    db.flush()

    for line in lines:
        if int(line.amount_minor or 0) <= 0:
            continue
        create_finance_entry(
            db=db,
            venue_id=int(venue_id),
            entry_date=month_start,
            amount_minor=int(line.amount_minor),
            direction="EXPENSE",
            kind="PAYROLL",
            source_type="payroll_run",
            source_id=int(run.id),
            meta_json={
                "member_user_id": int(line.member_user_id),
                "pay_profile_id": int(line.pay_profile_id) if line.pay_profile_id is not None else None,
                "payroll_line_id": int(line.id),
                "period_month": month_start.strftime("%Y-%m"),
            },
        )

    run.total_amount_minor = int(total_amount_minor)
    run.lines_count = len(lines)
    db.flush()

    return PayrollCalculationResult(run=run, lines=lines)
