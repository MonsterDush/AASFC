from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import (
    DailyReport,
    DailyReportValue,
    Department,
    DepartmentDayPlan,
    DepartmentMonthPlan,
    KpiMetric,
    Shift,
    ShiftAssignment,
)
from app.models.day_economics_month_plan import DayEconomicsMonthPlan
from app.models.day_economics_plan import DayEconomicsPlan
from app.models.day_economics_plan_template import DayEconomicsPlanTemplate
from app.models.venue_economics_rule import VenueEconomicsRule
from app.services.finance.summary import (
    _active_finance_shift_slots,
    _amount_share_for_slot,
    _group_revenue_breakdown,
    get_day_finance_summary,
)


WEEKDAY_TITLES = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}

DAY_KIND_TITLES = {
    "SPECIAL": "Спец-день",
    "HOLIDAY": "Праздник",
}


def _normalize_economics_shift_slot(value: str | None) -> str:
    slot = str(value or "TOTAL").strip().upper()
    if slot in {"DAY", "NIGHT"}:
        return slot
    return "TOTAL"


def _is_slot_specific(value: str | None) -> bool:
    return _normalize_economics_shift_slot(value) in {"DAY", "NIGHT"}


def _month_start(target_date: date) -> date:
    return target_date.replace(day=1)


def _month_title_ru(month_start: date) -> str:
    months = {
        1: "январь",
        2: "февраль",
        3: "март",
        4: "апрель",
        5: "май",
        6: "июнь",
        7: "июль",
        8: "август",
        9: "сентябрь",
        10: "октябрь",
        11: "ноябрь",
        12: "декабрь",
    }
    return f"{months.get(month_start.month, month_start.strftime('%m'))} {month_start.year}"


def _format_minor_as_rub_text(value_minor: int | None) -> str:
    minor = int(value_minor or 0)
    sign = "-" if minor < 0 else ""
    rub = abs(minor) / 100
    return f"{sign}{rub:,.2f} ₽".replace(",", " ")


def _normalize_day_kind(value: str | None) -> str | None:
    raw = str(value or "").strip().upper()
    if not raw:
        return None
    if raw not in DAY_KIND_TITLES:
        raise ValueError("Bad day_kind, expected SPECIAL or HOLIDAY")
    return raw


def _day_kind_title(day_kind: str | None) -> str | None:
    key = _normalize_day_kind(day_kind) if day_kind is not None and str(day_kind).strip() else None
    return DAY_KIND_TITLES.get(key) if key else None


def _serialize_single_report_state(report: DailyReport | None, *, shift_slot: str) -> dict:
    if report is None:
        return {
            "exists": False,
            "report_id": None,
            "status": "MISSING",
            "shift_slot": shift_slot,
            "closed_at": None,
            "closed_by_user_id": None,
            "comment": None,
            "revenue_total_minor": 0,
            "tips_total_minor": 0,
        }
    return {
        "exists": True,
        "report_id": int(report.id),
        "status": str(report.status or "DRAFT").upper(),
        "shift_slot": shift_slot,
        "closed_at": report.closed_at,
        "closed_by_user_id": int(report.closed_by_user_id) if report.closed_by_user_id is not None else None,
        "comment": report.comment,
        "revenue_total_minor": int(report.revenue_total or 0) * 100,
        "tips_total_minor": int(report.tips_total or 0) * 100,
    }


def _get_report_state(*, db: Session, venue_id: int, target_date: date, shift_slot: str = "TOTAL") -> dict:
    slot = _normalize_economics_shift_slot(shift_slot)
    stmt = select(DailyReport).where(
        DailyReport.venue_id == int(venue_id),
        DailyReport.date == target_date,
    )
    if slot in {"DAY", "NIGHT"}:
        report = db.execute(stmt.where(DailyReport.shift_slot == slot)).scalar_one_or_none()
        return _serialize_single_report_state(report, shift_slot=slot)

    reports = db.execute(stmt).scalars().all()
    if not reports:
        return _serialize_single_report_state(None, shift_slot="TOTAL")

    closed_reports = [r for r in reports if str(r.status or "").upper() == "CLOSED"]
    if closed_reports:
        status = "CLOSED"
    elif any(str(r.status or "").upper() == "DRAFT" for r in reports):
        status = "DRAFT"
    else:
        status = str(reports[0].status or "DRAFT").upper()

    latest_closed_at = None
    latest_closed_by = None
    for report in closed_reports:
        if report.closed_at is not None and (latest_closed_at is None or report.closed_at > latest_closed_at):
            latest_closed_at = report.closed_at
            latest_closed_by = report.closed_by_user_id

    comments = [str(r.comment or "").strip() for r in reports if str(r.comment or "").strip()]
    revenue_total = sum(int(r.revenue_total or 0) for r in closed_reports)
    tips_total = sum(int(r.tips_total or 0) for r in closed_reports)

    return {
        "exists": True,
        "report_id": None,
        "status": status,
        "shift_slot": "TOTAL",
        "closed_at": latest_closed_at,
        "closed_by_user_id": int(latest_closed_by) if latest_closed_by is not None else None,
        "comment": " · ".join(comments) if comments else None,
        "revenue_total_minor": int(revenue_total) * 100,
        "tips_total_minor": int(tips_total) * 100,
    }


def _shift_scope_filters(shift_slot: str | None) -> list:
    slot = _normalize_economics_shift_slot(shift_slot)
    if slot in {"DAY", "NIGHT"}:
        return [Shift.shift_slot == slot]
    return []


def _report_scope_filters(shift_slot: str | None) -> list:
    slot = _normalize_economics_shift_slot(shift_slot)
    if slot in {"DAY", "NIGHT"}:
        return [DailyReport.shift_slot == slot]
    return []


def _get_team_snapshot(*, db: Session, venue_id: int, target_date: date, shift_slot: str = "TOTAL") -> dict:
    shift_filters = _shift_scope_filters(shift_slot)

    total_shift_count = int(
        db.execute(
            select(func.count(Shift.id)).where(
                Shift.venue_id == int(venue_id),
                Shift.date == target_date,
                Shift.is_active.is_(True),
                *shift_filters,
            )
        ).scalar()
        or 0
    )
    assignment_count = int(
        db.execute(
            select(func.count(ShiftAssignment.id))
            .select_from(ShiftAssignment)
            .join(Shift, Shift.id == ShiftAssignment.shift_id)
            .where(
                Shift.venue_id == int(venue_id),
                Shift.date == target_date,
                Shift.is_active.is_(True),
                *shift_filters,
            )
        ).scalar()
        or 0
    )
    assigned_user_count = int(
        db.execute(
            select(func.count(distinct(ShiftAssignment.member_user_id)))
            .select_from(ShiftAssignment)
            .join(Shift, Shift.id == ShiftAssignment.shift_id)
            .where(
                Shift.venue_id == int(venue_id),
                Shift.date == target_date,
                Shift.is_active.is_(True),
                *shift_filters,
            )
        ).scalar()
        or 0
    )
    assigned_shift_count = int(
        db.execute(
            select(func.count(distinct(ShiftAssignment.shift_id)))
            .select_from(ShiftAssignment)
            .join(Shift, Shift.id == ShiftAssignment.shift_id)
            .where(
                Shift.venue_id == int(venue_id),
                Shift.date == target_date,
                Shift.is_active.is_(True),
                *shift_filters,
            )
        ).scalar()
        or 0
    )
    unassigned_shift_count = max(total_shift_count - assigned_shift_count, 0)
    return {
        "total_shift_count": total_shift_count,
        "assignment_count": assignment_count,
        "assigned_user_count": assigned_user_count,
        "assigned_shift_count": assigned_shift_count,
        "unassigned_shift_count": unassigned_shift_count,
    }


def _get_kpi_breakdown(*, db: Session, venue_id: int, target_date: date, shift_slot: str = "TOTAL") -> list[dict]:
    report_ids = (
        db.execute(
            select(DailyReport.id).where(
                DailyReport.venue_id == int(venue_id),
                DailyReport.date == target_date,
                DailyReport.status == "CLOSED",
                *_report_scope_filters(shift_slot),
            )
        )
        .scalars()
        .all()
    )
    if not report_ids:
        return []

    rows = db.execute(
        select(DailyReportValue.ref_id, func.coalesce(func.sum(DailyReportValue.value_numeric), 0))
        .where(
            DailyReportValue.report_id.in_([int(x) for x in report_ids]),
            DailyReportValue.kind == "KPI",
        )
        .group_by(DailyReportValue.ref_id)
    ).all()
    if not rows:
        return []

    metric_rows = db.execute(
        select(KpiMetric.id, KpiMetric.code, KpiMetric.title, KpiMetric.unit).where(KpiMetric.venue_id == int(venue_id))
    ).all()
    metric_map = {int(row[0]): row for row in metric_rows}
    out = []
    for row in rows:
        ref_id = int(row[0])
        metric = metric_map.get(ref_id)
        out.append(
            {
                "metric_id": ref_id,
                "code": metric[1] if metric else None,
                "title": metric[2] if metric else f"KPI {ref_id}",
                "unit": metric[3] if metric else "QTY",
                "value_numeric": int(row[1] or 0),
            }
        )
    out.sort(key=lambda item: str(item["title"]))
    return out


def _safe_ratio_bps(*, numerator_minor: int, denominator_minor: int) -> int | None:
    if int(denominator_minor or 0) <= 0:
        return None
    return int((int(numerator_minor or 0) * 10000) / int(denominator_minor))


def _build_share_breakdown(rows: list[dict]) -> list[dict]:
    total_minor = int(sum(int(item.get("amount_minor") or 0) for item in rows))
    out: list[dict] = []
    for item in rows:
        amount_minor = int(item.get("amount_minor") or 0)
        share_bps = int((amount_minor * 10000) / total_minor) if total_minor > 0 else None
        out.append(
            {
                "title": item.get("title"),
                "code": item.get("code"),
                "amount_minor": amount_minor,
                "share_bps": share_bps,
            }
        )
    return out


def _build_kpi_summary(kpi_breakdown: list[dict]) -> dict:
    metric_count = len(kpi_breakdown)
    nonzero_metric_count = sum(1 for item in kpi_breakdown if int(item.get("value_numeric") or 0) != 0)
    total_value_numeric = int(sum(int(item.get("value_numeric") or 0) for item in kpi_breakdown))
    return {
        "metric_count": metric_count,
        "nonzero_metric_count": nonzero_metric_count,
        "total_value_numeric": total_value_numeric,
    }


def _empty_plan(
    *, target_date: date, source: str = "NONE", template_weekday: int | None = None, template_month: str | None = None
) -> dict:
    return {
        "date": target_date,
        "source": source,
        "template_weekday": template_weekday,
        "template_weekday_title": WEEKDAY_TITLES.get(template_weekday) if template_weekday is not None else None,
        "template_month": template_month,
        "template_month_title": _month_title_ru(date.fromisoformat(f"{template_month}-01")) if template_month else None,
        "revenue_plan_minor": None,
        "profit_plan_minor": None,
        "revenue_per_assigned_plan_minor": None,
        "assigned_user_target": None,
        "day_kind": None,
        "day_kind_title": None,
        "title": None,
        "notes": None,
    }


def _serialize_plan(
    plan: DayEconomicsPlan | DayEconomicsMonthPlan | DayEconomicsPlanTemplate | None,
    *,
    target_date: date,
    source: str = "DATE_OVERRIDE",
    template_weekday: int | None = None,
    template_month: str | None = None,
) -> dict:
    if plan is None:
        return _empty_plan(
            target_date=target_date, source=source, template_weekday=template_weekday, template_month=template_month
        )
    weekday = (
        template_weekday if template_weekday is not None else (int(plan.weekday) if hasattr(plan, "weekday") else None)
    )
    month_value = template_month
    if month_value is None and hasattr(plan, "month_start") and getattr(plan, "month_start") is not None:
        month_value = getattr(plan, "month_start").strftime("%Y-%m")
    day_kind = getattr(plan, "day_kind", None) if plan is not None else None
    day_kind = _normalize_day_kind(day_kind) if day_kind else None
    return {
        "date": target_date,
        "source": source,
        "template_weekday": weekday,
        "template_weekday_title": WEEKDAY_TITLES.get(weekday) if weekday is not None else None,
        "template_month": month_value,
        "template_month_title": _month_title_ru(date.fromisoformat(f"{month_value}-01")) if month_value else None,
        "revenue_plan_minor": int(plan.revenue_plan_minor) if plan.revenue_plan_minor is not None else None,
        "profit_plan_minor": int(plan.profit_plan_minor) if plan.profit_plan_minor is not None else None,
        "revenue_per_assigned_plan_minor": int(plan.revenue_per_assigned_plan_minor)
        if plan.revenue_per_assigned_plan_minor is not None
        else None,
        "assigned_user_target": int(plan.assigned_user_target) if plan.assigned_user_target is not None else None,
        "day_kind": day_kind,
        "day_kind_title": _day_kind_title(day_kind),
        "title": getattr(plan, "title", None),
        "notes": plan.notes,
    }


def _get_date_override_plan_model(*, db: Session, venue_id: int, target_date: date) -> DayEconomicsPlan | None:
    return db.execute(
        select(DayEconomicsPlan).where(
            DayEconomicsPlan.venue_id == int(venue_id),
            DayEconomicsPlan.target_date == target_date,
        )
    ).scalar_one_or_none()


def _get_month_plan_model(*, db: Session, venue_id: int, target_date: date) -> DayEconomicsMonthPlan | None:
    return db.execute(
        select(DayEconomicsMonthPlan).where(
            DayEconomicsMonthPlan.venue_id == int(venue_id),
            DayEconomicsMonthPlan.month_start == _month_start(target_date),
        )
    ).scalar_one_or_none()


def _get_weekday_template_model(*, db: Session, venue_id: int, weekday: int) -> DayEconomicsPlanTemplate | None:
    return db.execute(
        select(DayEconomicsPlanTemplate).where(
            DayEconomicsPlanTemplate.venue_id == int(venue_id),
            DayEconomicsPlanTemplate.weekday == int(weekday),
        )
    ).scalar_one_or_none()


def get_day_economics_plan(*, db: Session, venue_id: int, target_date: date) -> dict:
    override = _get_date_override_plan_model(db=db, venue_id=venue_id, target_date=target_date)
    if override is not None:
        return _serialize_plan(override, target_date=target_date, source="DATE_OVERRIDE")
    month_plan = _get_month_plan_model(db=db, venue_id=venue_id, target_date=target_date)
    if month_plan is not None:
        return _serialize_plan(
            month_plan,
            target_date=target_date,
            source="MONTH_TEMPLATE",
            template_month=_month_start(target_date).strftime("%Y-%m"),
        )
    template = _get_weekday_template_model(db=db, venue_id=venue_id, weekday=target_date.weekday())
    if template is not None:
        return _serialize_plan(
            template, target_date=target_date, source="WEEKDAY_TEMPLATE", template_weekday=target_date.weekday()
        )
    return _empty_plan(
        target_date=target_date,
        source="NONE",
        template_weekday=target_date.weekday(),
        template_month=_month_start(target_date).strftime("%Y-%m"),
    )


def get_day_economics_plan_override(*, db: Session, venue_id: int, target_date: date) -> dict:
    override = _get_date_override_plan_model(db=db, venue_id=venue_id, target_date=target_date)
    if override is None:
        return _empty_plan(target_date=target_date, source="DATE_OVERRIDE", template_weekday=target_date.weekday())
    return _serialize_plan(override, target_date=target_date, source="DATE_OVERRIDE")


def upsert_day_economics_plan(
    *,
    db: Session,
    venue_id: int,
    target_date: date,
    revenue_plan_minor: int | None,
    profit_plan_minor: int | None,
    revenue_per_assigned_plan_minor: int | None,
    assigned_user_target: int | None,
    day_kind: str | None,
    title: str | None,
    notes: str | None,
) -> dict:
    plan = _get_date_override_plan_model(db=db, venue_id=venue_id, target_date=target_date)
    if plan is None:
        plan = DayEconomicsPlan(venue_id=int(venue_id), target_date=target_date)
        db.add(plan)
    plan.revenue_plan_minor = revenue_plan_minor
    plan.profit_plan_minor = profit_plan_minor
    plan.revenue_per_assigned_plan_minor = revenue_per_assigned_plan_minor
    plan.assigned_user_target = assigned_user_target
    plan.day_kind = _normalize_day_kind(day_kind)
    plan.title = (title or "").strip() or None
    plan.notes = notes or None
    db.flush()
    return _serialize_plan(plan, target_date=target_date, source="DATE_OVERRIDE")


def get_day_economics_month_plan(*, db: Session, venue_id: int, month_value: str) -> dict:
    month_date = date.fromisoformat(f"{month_value}-01")
    plan = _get_month_plan_model(db=db, venue_id=venue_id, target_date=month_date)
    if plan is None:
        return _empty_plan(target_date=month_date, source="MONTH_TEMPLATE", template_month=month_date.strftime("%Y-%m"))
    return _serialize_plan(
        plan, target_date=month_date, source="MONTH_TEMPLATE", template_month=month_date.strftime("%Y-%m")
    )


def upsert_day_economics_month_plan(
    *,
    db: Session,
    venue_id: int,
    month_value: str,
    revenue_plan_minor: int | None,
    profit_plan_minor: int | None,
    revenue_per_assigned_plan_minor: int | None,
    assigned_user_target: int | None,
    notes: str | None,
) -> dict:
    month_date = date.fromisoformat(f"{month_value}-01")
    plan = _get_month_plan_model(db=db, venue_id=venue_id, target_date=month_date)
    if plan is None:
        plan = DayEconomicsMonthPlan(venue_id=int(venue_id), month_start=month_date)
        db.add(plan)
    plan.revenue_plan_minor = revenue_plan_minor
    plan.profit_plan_minor = profit_plan_minor
    plan.revenue_per_assigned_plan_minor = revenue_per_assigned_plan_minor
    plan.assigned_user_target = assigned_user_target
    plan.notes = notes or None
    db.flush()
    return _serialize_plan(
        plan, target_date=month_date, source="MONTH_TEMPLATE", template_month=month_date.strftime("%Y-%m")
    )


def copy_day_economics_month_plan_from_previous_month(
    *, db: Session, venue_id: int, month_value: str, overwrite: bool = True
) -> dict:
    month_date = date.fromisoformat(f"{month_value}-01")
    previous_month_date = (month_date - timedelta(days=1)).replace(day=1)
    source = _get_month_plan_model(db=db, venue_id=venue_id, target_date=previous_month_date)
    if source is None:
        raise ValueError("Нет плана за предыдущий месяц для копирования")
    existing = _get_month_plan_model(db=db, venue_id=venue_id, target_date=month_date)
    if existing is not None and not overwrite:
        return {
            "copied": False,
            "copied_from_month": previous_month_date.strftime("%Y-%m"),
            "plan": _serialize_plan(
                existing, target_date=month_date, source="MONTH_TEMPLATE", template_month=month_date.strftime("%Y-%m")
            ),
        }
    target = existing
    if target is None:
        target = DayEconomicsMonthPlan(venue_id=int(venue_id), month_start=month_date)
        db.add(target)
    target.revenue_plan_minor = source.revenue_plan_minor
    target.profit_plan_minor = source.profit_plan_minor
    target.revenue_per_assigned_plan_minor = source.revenue_per_assigned_plan_minor
    target.assigned_user_target = source.assigned_user_target
    target.notes = source.notes
    db.flush()
    return {
        "copied": True,
        "copied_from_month": previous_month_date.strftime("%Y-%m"),
        "plan": _serialize_plan(
            target, target_date=month_date, source="MONTH_TEMPLATE", template_month=month_date.strftime("%Y-%m")
        ),
    }


def list_day_economics_plan_templates(*, db: Session, venue_id: int) -> list[dict]:
    rows = (
        db.execute(select(DayEconomicsPlanTemplate).where(DayEconomicsPlanTemplate.venue_id == int(venue_id)))
        .scalars()
        .all()
    )
    by_weekday = {int(item.weekday): item for item in rows}
    result: list[dict] = []
    for weekday in range(7):
        template = by_weekday.get(weekday)
        result.append(
            {
                "weekday": weekday,
                "weekday_title": WEEKDAY_TITLES[weekday],
                **_serialize_plan(
                    template,
                    target_date=date(2000, 1, 3) + timedelta(days=weekday),
                    source="WEEKDAY_TEMPLATE",
                    template_weekday=weekday,
                ),
            }
        )
    return result


def upsert_day_economics_plan_template(
    *,
    db: Session,
    venue_id: int,
    weekday: int,
    revenue_plan_minor: int | None,
    profit_plan_minor: int | None,
    revenue_per_assigned_plan_minor: int | None,
    assigned_user_target: int | None,
    notes: str | None,
) -> dict:
    if int(weekday) < 0 or int(weekday) > 6:
        raise ValueError("Bad weekday, expected 0..6")
    template = _get_weekday_template_model(db=db, venue_id=venue_id, weekday=weekday)
    if template is None:
        template = DayEconomicsPlanTemplate(venue_id=int(venue_id), weekday=int(weekday))
        db.add(template)
    template.revenue_plan_minor = revenue_plan_minor
    template.profit_plan_minor = profit_plan_minor
    template.revenue_per_assigned_plan_minor = revenue_per_assigned_plan_minor
    template.assigned_user_target = assigned_user_target
    template.notes = notes or None
    db.flush()
    return {
        "weekday": int(weekday),
        "weekday_title": WEEKDAY_TITLES[int(weekday)],
        **_serialize_plan(
            template,
            target_date=date(2000, 1, 3) + timedelta(days=int(weekday)),
            source="WEEKDAY_TEMPLATE",
            template_weekday=int(weekday),
        ),
    }


def copy_day_economics_plan_templates(
    *,
    db: Session,
    venue_id: int,
    source_weekday: int,
    target_weekdays: list[int],
    overwrite: bool = True,
) -> dict:
    if int(source_weekday) < 0 or int(source_weekday) > 6:
        raise ValueError("Bad source_weekday, expected 0..6")
    source = _get_weekday_template_model(db=db, venue_id=venue_id, weekday=source_weekday)
    if source is None:
        raise ValueError("Нет исходного шаблона для копирования")
    normalized_targets = []
    for weekday in target_weekdays:
        w = int(weekday)
        if w < 0 or w > 6:
            raise ValueError("Bad target_weekdays, expected values 0..6")
        if w != int(source_weekday) and w not in normalized_targets:
            normalized_targets.append(w)
    copied_rows = []
    skipped = []
    for weekday in normalized_targets:
        existing = _get_weekday_template_model(db=db, venue_id=venue_id, weekday=weekday)
        if existing is not None and not overwrite:
            skipped.append({"weekday": weekday, "weekday_title": WEEKDAY_TITLES[weekday], "reason": "already_exists"})
            continue
        target = existing
        if target is None:
            target = DayEconomicsPlanTemplate(venue_id=int(venue_id), weekday=weekday)
            db.add(target)
        target.revenue_plan_minor = source.revenue_plan_minor
        target.profit_plan_minor = source.profit_plan_minor
        target.revenue_per_assigned_plan_minor = source.revenue_per_assigned_plan_minor
        target.assigned_user_target = source.assigned_user_target
        target.notes = source.notes
        db.flush()
        copied_rows.append(
            {
                "weekday": weekday,
                "weekday_title": WEEKDAY_TITLES[weekday],
                **_serialize_plan(
                    target,
                    target_date=date(2000, 1, 3) + timedelta(days=weekday),
                    source="WEEKDAY_TEMPLATE",
                    template_weekday=weekday,
                ),
            }
        )
    return {
        "source_weekday": int(source_weekday),
        "source_weekday_title": WEEKDAY_TITLES[int(source_weekday)],
        "copied_count": len(copied_rows),
        "copied": copied_rows,
        "skipped_count": len(skipped),
        "skipped": skipped,
    }


def _serialize_rules(rule: VenueEconomicsRule | None) -> dict:
    if rule is None:
        return {
            "max_expense_ratio_bps": None,
            "max_payroll_ratio_bps": None,
            "min_revenue_per_assigned_minor": None,
            "min_assigned_shift_coverage_bps": None,
            "min_profit_minor": None,
            "warn_on_draft_expenses": True,
        }
    return {
        "max_expense_ratio_bps": int(rule.max_expense_ratio_bps) if rule.max_expense_ratio_bps is not None else None,
        "max_payroll_ratio_bps": int(rule.max_payroll_ratio_bps) if rule.max_payroll_ratio_bps is not None else None,
        "min_revenue_per_assigned_minor": int(rule.min_revenue_per_assigned_minor)
        if rule.min_revenue_per_assigned_minor is not None
        else None,
        "min_assigned_shift_coverage_bps": int(rule.min_assigned_shift_coverage_bps)
        if rule.min_assigned_shift_coverage_bps is not None
        else None,
        "min_profit_minor": int(rule.min_profit_minor) if rule.min_profit_minor is not None else None,
        "warn_on_draft_expenses": bool(rule.warn_on_draft_expenses),
    }


def get_venue_economics_rules(*, db: Session, venue_id: int) -> dict:
    rule = db.execute(
        select(VenueEconomicsRule).where(VenueEconomicsRule.venue_id == int(venue_id))
    ).scalar_one_or_none()
    return _serialize_rules(rule)


def upsert_venue_economics_rules(
    *,
    db: Session,
    venue_id: int,
    max_expense_ratio_bps: int | None,
    max_payroll_ratio_bps: int | None,
    min_revenue_per_assigned_minor: int | None,
    min_assigned_shift_coverage_bps: int | None,
    min_profit_minor: int | None,
    warn_on_draft_expenses: bool,
) -> dict:
    rule = db.execute(
        select(VenueEconomicsRule).where(VenueEconomicsRule.venue_id == int(venue_id))
    ).scalar_one_or_none()
    if rule is None:
        rule = VenueEconomicsRule(venue_id=int(venue_id))
        db.add(rule)
    rule.max_expense_ratio_bps = max_expense_ratio_bps
    rule.max_payroll_ratio_bps = max_payroll_ratio_bps
    rule.min_revenue_per_assigned_minor = min_revenue_per_assigned_minor
    rule.min_assigned_shift_coverage_bps = min_assigned_shift_coverage_bps
    rule.min_profit_minor = min_profit_minor
    rule.warn_on_draft_expenses = bool(warn_on_draft_expenses)
    db.flush()
    return _serialize_rules(rule)


def _build_plan_fact(
    *,
    summary: dict,
    metrics: dict,
    team: dict,
    plan: dict,
    comparison_available: bool = True,
) -> dict:
    revenue_fact_minor = int(summary.get("revenue_minor") or 0)
    profit_fact_minor = int(summary.get("profit_minor") or 0)
    revenue_per_assigned_fact_minor = metrics.get("revenue_per_assigned_minor")
    assigned_user_fact = int(team.get("assigned_user_count") or 0)

    revenue_plan_minor = plan.get("revenue_plan_minor") if comparison_available else None
    profit_plan_minor = plan.get("profit_plan_minor") if comparison_available else None
    revenue_per_assigned_plan_minor = plan.get("revenue_per_assigned_plan_minor") if comparison_available else None
    assigned_user_target = plan.get("assigned_user_target") if comparison_available else None

    return {
        "comparison_available": bool(comparison_available),
        "revenue_fact_minor": revenue_fact_minor,
        "revenue_plan_minor": revenue_plan_minor,
        "revenue_delta_minor": (revenue_fact_minor - int(revenue_plan_minor))
        if revenue_plan_minor is not None
        else None,
        "revenue_progress_bps": _safe_ratio_bps(
            numerator_minor=revenue_fact_minor, denominator_minor=int(revenue_plan_minor)
        )
        if revenue_plan_minor
        else None,
        "profit_fact_minor": profit_fact_minor,
        "profit_plan_minor": profit_plan_minor,
        "profit_delta_minor": (profit_fact_minor - int(profit_plan_minor)) if profit_plan_minor is not None else None,
        "revenue_per_assigned_fact_minor": revenue_per_assigned_fact_minor,
        "revenue_per_assigned_plan_minor": revenue_per_assigned_plan_minor,
        "revenue_per_assigned_delta_minor": (
            int(revenue_per_assigned_fact_minor) - int(revenue_per_assigned_plan_minor)
        )
        if revenue_per_assigned_fact_minor is not None and revenue_per_assigned_plan_minor is not None
        else None,
        "assigned_user_fact": assigned_user_fact,
        "assigned_user_target": assigned_user_target,
        "assigned_user_delta": (assigned_user_fact - int(assigned_user_target))
        if assigned_user_target is not None
        else None,
    }


def _allocate_common_plan_to_slot(
    *,
    plan: dict,
    shift_slot: str,
    active_slots: list[str],
) -> dict:
    slot = _normalize_economics_shift_slot(shift_slot)
    payload = dict(plan or {})
    payload["shift_slot"] = slot
    payload["allocated_from_total"] = slot in {"DAY", "NIGHT"}
    if slot not in {"DAY", "NIGHT"}:
        return payload
    for key in ("revenue_plan_minor", "profit_plan_minor", "assigned_user_target"):
        value = payload.get(key)
        if value is None:
            continue
        payload[key] = _amount_share_for_slot(
            amount_minor=int(value),
            slots=active_slots,
            shift_slot=slot,
        )
    return payload


def _build_alerts(
    *, report: dict, summary: dict, metrics: dict, plan_fact: dict, rules: dict, shift_slot: str = "TOTAL"
) -> list[dict]:
    alerts: list[dict] = []
    slot_specific = _is_slot_specific(shift_slot)

    report_status = str(report.get("status") or "MISSING").upper()
    if report_status != "CLOSED":
        alerts.append(
            {
                "severity": "WARN",
                "code": "REPORT_NOT_CLOSED",
                "title": "День не закрыт",
                "detail": "Экономика дня может быть неполной, пока отчёт не закрыт.",
            }
        )

    if bool(rules.get("warn_on_draft_expenses", True)) and int(summary.get("draft_expense_count") or 0) > 0:
        alerts.append(
            {
                "severity": "WARN",
                "code": "DRAFT_EXPENSES",
                "title": "Есть черновые расходы",
                "detail": f"{int(summary.get('draft_expense_count') or 0)} черновик(ов) на сумму {_format_minor_as_rub_text(summary.get('draft_expense_total_minor'))}.",
            }
        )

    if slot_specific and not bool(summary.get("slot_costs_available", True)):
        alerts.append(
            {
                "severity": "INFO",
                "code": "SLOT_COSTS_NOT_ALLOCATED",
                "title": "Расходы и ФОТ показаны в «Итого»",
                "detail": "Текущие расходы, корректировки и ФОТ пока хранятся на уровне даты, поэтому не распределяются между дневной и ночной сменой.",
            }
        )

    if bool(summary.get("slot_profit_available", True)):
        if int(summary.get("profit_minor") or 0) < 0:
            alerts.append(
                {
                    "severity": "CRITICAL",
                    "code": "LOSS_DAY",
                    "title": "День убыточный",
                    "detail": "Фактическая прибыль дня ушла в минус.",
                }
            )

        max_expense_ratio_bps = rules.get("max_expense_ratio_bps")
        expense_ratio_bps = metrics.get("expense_ratio_bps")
        if (
            max_expense_ratio_bps is not None
            and expense_ratio_bps is not None
            and int(expense_ratio_bps) > int(max_expense_ratio_bps)
        ):
            alerts.append(
                {
                    "severity": "WARN",
                    "code": "EXPENSE_RATIO_HIGH",
                    "title": "Расходы выше нормы",
                    "detail": f"Расходы к выручке: {expense_ratio_bps / 100:.2f}% при лимите {int(max_expense_ratio_bps) / 100:.2f}%.",
                }
            )

        max_payroll_ratio_bps = rules.get("max_payroll_ratio_bps")
        payroll_ratio_bps = metrics.get("payroll_ratio_bps")
        if (
            max_payroll_ratio_bps is not None
            and payroll_ratio_bps is not None
            and int(payroll_ratio_bps) > int(max_payroll_ratio_bps)
        ):
            alerts.append(
                {
                    "severity": "WARN",
                    "code": "PAYROLL_RATIO_HIGH",
                    "title": "ФОТ выше нормы",
                    "detail": f"ФОТ к выручке: {payroll_ratio_bps / 100:.2f}% при лимите {int(max_payroll_ratio_bps) / 100:.2f}%.",
                }
            )

        min_revenue_per_assigned_minor = rules.get("min_revenue_per_assigned_minor")
        revenue_per_assigned_minor = metrics.get("revenue_per_assigned_minor")
        if (
            min_revenue_per_assigned_minor is not None
            and revenue_per_assigned_minor is not None
            and int(revenue_per_assigned_minor) < int(min_revenue_per_assigned_minor)
        ):
            alerts.append(
                {
                    "severity": "WARN",
                    "code": "REVENUE_PER_ASSIGNED_LOW",
                    "title": "Низкая выручка на сотрудника",
                    "detail": "Выручка на сотрудника ниже заданной нормы.",
                }
            )

    min_assigned_shift_coverage_bps = rules.get("min_assigned_shift_coverage_bps")
    coverage_bps = metrics.get("assigned_shift_coverage_bps")
    if (
        min_assigned_shift_coverage_bps is not None
        and coverage_bps is not None
        and int(coverage_bps) < int(min_assigned_shift_coverage_bps)
    ):
        alerts.append(
            {
                "severity": "WARN",
                "code": "SHIFT_COVERAGE_LOW",
                "title": "Низкое покрытие смен",
                "detail": f"Покрытие смен: {coverage_bps / 100:.2f}% при целевом значении {int(min_assigned_shift_coverage_bps) / 100:.2f}%.",
            }
        )

    if bool(summary.get("slot_profit_available", True)):
        min_profit_minor = rules.get("min_profit_minor")
        if min_profit_minor is not None and int(summary.get("profit_minor") or 0) < int(min_profit_minor):
            alerts.append(
                {
                    "severity": "WARN",
                    "code": "PROFIT_BELOW_TARGET",
                    "title": "Прибыль ниже порога",
                    "detail": "Фактическая прибыль дня ниже заданного минимального порога.",
                }
            )

        if plan_fact.get("revenue_delta_minor") is not None and int(plan_fact["revenue_delta_minor"]) < 0:
            alerts.append(
                {
                    "severity": "INFO",
                    "code": "REVENUE_PLAN_MISSED",
                    "title": "План по выручке не выполнен",
                    "detail": "Фактическая выручка ниже плана дня.",
                }
            )

        if plan_fact.get("profit_delta_minor") is not None and int(plan_fact["profit_delta_minor"]) < 0:
            alerts.append(
                {
                    "severity": "INFO",
                    "code": "PROFIT_PLAN_MISSED",
                    "title": "План по прибыли не выполнен",
                    "detail": "Фактическая прибыль ниже плана дня.",
                }
            )

    return alerts


def _build_rollup(*, db: Session, venue_id: int, target_date: date, shift_slot: str = "TOTAL") -> dict:
    month_start = target_date.replace(day=1)
    profit_available = True
    cursor = month_start
    days: list[dict] = []
    avg_revenue_per_assigned_parts: list[int] = []
    closed_day_count = 0

    while cursor <= target_date:
        summary = get_day_finance_summary(
            db=db, venue_id=venue_id, target_date=cursor, income_mode="PAYMENTS", shift_slot=shift_slot
        )
        team = _get_team_snapshot(db=db, venue_id=venue_id, target_date=cursor, shift_slot=shift_slot)
        report = _get_report_state(db=db, venue_id=venue_id, target_date=cursor, shift_slot=shift_slot)
        if str(report.get("status") or "").upper() == "CLOSED":
            closed_day_count += 1
        if (
            int(summary.get("revenue_minor") or 0) > 0
            or int(summary.get("expense_minor") or 0) > 0
            or report.get("exists")
        ):
            profit_minor = int(summary.get("profit_minor") or 0)
            revenue_minor = int(summary.get("revenue_minor") or 0)
            assigned_users = int(team.get("assigned_user_count") or 0)
            if assigned_users > 0:
                avg_revenue_per_assigned_parts.append(int(revenue_minor / assigned_users))
            days.append(
                {
                    "date": cursor,
                    "profit_minor": profit_minor,
                    "revenue_minor": revenue_minor,
                }
            )
        cursor += timedelta(days=1)

    profit_total_minor = int(sum(int(item["profit_minor"]) for item in days)) if profit_available and days else 0
    avg_profit_minor = int(profit_total_minor / len(days)) if profit_available and days else None
    avg_revenue_per_assigned_minor = (
        int(sum(avg_revenue_per_assigned_parts) / len(avg_revenue_per_assigned_parts))
        if avg_revenue_per_assigned_parts
        else None
    )
    profitable_day_count = sum(1 for item in days if int(item["profit_minor"]) > 0) if profit_available else 0
    loss_day_count = sum(1 for item in days if int(item["profit_minor"]) < 0) if profit_available else 0
    best_day = max(days, key=lambda item: int(item["profit_minor"])) if profit_available and days else None
    worst_day = min(days, key=lambda item: int(item["profit_minor"])) if profit_available and days else None

    return {
        "month": month_start.strftime("%Y-%m"),
        "profit_available": profit_available,
        "days_in_period": (target_date - month_start).days + 1,
        "evaluated_day_count": len(days),
        "closed_day_count": closed_day_count,
        "profit_total_minor": profit_total_minor,
        "avg_profit_minor": avg_profit_minor,
        "avg_revenue_per_assigned_minor": avg_revenue_per_assigned_minor,
        "profitable_day_count": profitable_day_count,
        "loss_day_count": loss_day_count,
        "best_day": best_day,
        "worst_day": worst_day,
    }


def _build_metrics(
    *, summary: dict, report: dict, team: dict, department_share_breakdown: list[dict], kpi_breakdown: list[dict]
) -> dict:
    revenue_minor = int(summary.get("revenue_minor") or 0)
    point_expense_minor = int(summary.get("point_expense_minor") or 0)
    recurring_expense_minor = int(summary.get("recurring_expense_minor") or 0)
    expense_minor = int(summary.get("expense_minor") or 0)
    payroll_minor = int(summary.get("payroll_minor") or 0)
    profit_minor = int(summary.get("profit_minor") or 0)
    assigned_user_count = int(team.get("assigned_user_count") or 0)
    total_shift_count = int(team.get("total_shift_count") or 0)
    assigned_shift_count = int(team.get("assigned_shift_count") or 0)
    assignment_count = int(team.get("assignment_count") or 0)
    tips_total_minor = int(report.get("tips_total_minor") or 0)
    profit_available = bool(summary.get("slot_profit_available", True))

    if not profit_available:
        result_status = "UNAVAILABLE"
    elif profit_minor > 0:
        result_status = "PROFIT"
    elif profit_minor < 0:
        result_status = "LOSS"
    else:
        result_status = "BREAKEVEN"

    top_department = department_share_breakdown[0] if department_share_breakdown else None
    kpi_summary = _build_kpi_summary(kpi_breakdown)

    return {
        "result_status": result_status,
        "revenue_per_assigned_minor": int(revenue_minor / assigned_user_count) if assigned_user_count > 0 else None,
        "tips_per_assigned_minor": int(tips_total_minor / assigned_user_count) if assigned_user_count > 0 else None,
        "profit_per_assigned_minor": int(profit_minor / assigned_user_count)
        if profit_available and assigned_user_count > 0
        else None,
        "revenue_per_shift_minor": int(revenue_minor / total_shift_count) if total_shift_count > 0 else None,
        "profit_per_shift_minor": int(profit_minor / total_shift_count)
        if profit_available and total_shift_count > 0
        else None,
        "assignments_per_shift": round(assignment_count / total_shift_count, 2) if total_shift_count > 0 else None,
        "assigned_shift_coverage_bps": _safe_ratio_bps(
            numerator_minor=assigned_shift_count, denominator_minor=total_shift_count
        ),
        "expense_ratio_bps": _safe_ratio_bps(numerator_minor=expense_minor, denominator_minor=revenue_minor)
        if profit_available
        else None,
        "point_expense_ratio_bps": _safe_ratio_bps(numerator_minor=point_expense_minor, denominator_minor=revenue_minor)
        if profit_available
        else None,
        "recurring_expense_ratio_bps": _safe_ratio_bps(
            numerator_minor=recurring_expense_minor, denominator_minor=revenue_minor
        )
        if profit_available
        else None,
        "payroll_ratio_bps": _safe_ratio_bps(numerator_minor=payroll_minor, denominator_minor=revenue_minor)
        if profit_available
        else None,
        "top_department_title": top_department.get("title") if top_department else None,
        "top_department_share_bps": top_department.get("share_bps") if top_department else None,
        "kpi_metric_count": int(kpi_summary["metric_count"]),
        "nonzero_kpi_metric_count": int(kpi_summary["nonzero_metric_count"]),
        "kpi_total_value_numeric": int(kpi_summary["total_value_numeric"]),
    }


def get_day_economics(*, db: Session, venue_id: int, target_date: date, shift_slot: str = "TOTAL") -> dict:
    slot = _normalize_economics_shift_slot(shift_slot)
    slot_specific = _is_slot_specific(slot)
    summary = get_day_finance_summary(
        db=db, venue_id=venue_id, target_date=target_date, income_mode="PAYMENTS", shift_slot=slot
    )
    report = _get_report_state(db=db, venue_id=venue_id, target_date=target_date, shift_slot=slot)
    team = _get_team_snapshot(db=db, venue_id=venue_id, target_date=target_date, shift_slot=slot)
    payment_revenue_breakdown = _group_revenue_breakdown(
        db, venue_id=venue_id, period_start=target_date, period_end=target_date, income_mode="PAYMENTS", shift_slot=slot
    )
    department_revenue_breakdown = _group_revenue_breakdown(
        db,
        venue_id=venue_id,
        period_start=target_date,
        period_end=target_date,
        income_mode="DEPARTMENTS",
        shift_slot=slot,
    )
    department_share_breakdown = _build_share_breakdown(department_revenue_breakdown)
    kpi_breakdown = _get_kpi_breakdown(db=db, venue_id=venue_id, target_date=target_date, shift_slot=slot)
    metrics = _build_metrics(
        summary=summary,
        report=report,
        team=team,
        department_share_breakdown=department_share_breakdown,
        kpi_breakdown=kpi_breakdown,
    )
    plan = _allocate_common_plan_to_slot(
        plan=get_day_economics_plan(db=db, venue_id=venue_id, target_date=target_date),
        shift_slot=slot,
        active_slots=(_active_finance_shift_slots(db, venue_id=venue_id) if slot_specific else ["DAY"]),
    )
    rules = get_venue_economics_rules(db=db, venue_id=venue_id)
    plan_fact = _build_plan_fact(
        summary=summary,
        metrics=metrics,
        team=team,
        plan=plan,
        comparison_available=True,
    )
    alerts = _build_alerts(
        report=report, summary=summary, metrics=metrics, plan_fact=plan_fact, rules=rules, shift_slot=slot
    )
    rollup = _build_rollup(db=db, venue_id=venue_id, target_date=target_date, shift_slot=slot)
    return {
        "date": target_date,
        "shift_slot": slot,
        "report": report,
        "team": team,
        "metrics": metrics,
        "summary": summary,
        "payment_revenue_breakdown": payment_revenue_breakdown,
        "department_revenue_breakdown": department_revenue_breakdown,
        "department_share_breakdown": department_share_breakdown,
        "kpi_breakdown": kpi_breakdown,
        "kpi_summary": _build_kpi_summary(kpi_breakdown),
        "plan": plan,
        "rules": rules,
        "plan_fact": plan_fact,
        "alerts": alerts,
        "rollup": rollup,
    }


def _list_active_departments(db: Session, *, venue_id: int) -> list[Department]:
    return (
        db.execute(
            select(Department)
            .where(Department.venue_id == int(venue_id), Department.is_active.is_(True))
            .order_by(Department.sort_order.asc(), Department.title.asc(), Department.id.asc())
        )
        .scalars()
        .all()
    )


def _department_actuals_for_month(db: Session, *, venue_id: int, month_date: date) -> dict[int, int]:
    month_start = _month_start(month_date)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    rows = db.execute(
        select(
            DailyReportValue.ref_id,
            func.coalesce(func.sum(DailyReportValue.value_numeric), 0).label("amount"),
        )
        .join(DailyReport, DailyReport.id == DailyReportValue.report_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= month_start,
            DailyReport.date < next_month,
            DailyReportValue.kind == "DEPT",
        )
        .group_by(DailyReportValue.ref_id)
    ).all()
    return {int(row.ref_id): int(row.amount or 0) * 100 for row in rows}


def _department_actuals_for_day(db: Session, *, venue_id: int, target_date: date) -> dict[int, int]:
    rows = db.execute(
        select(
            DailyReportValue.ref_id,
            func.coalesce(func.sum(DailyReportValue.value_numeric), 0).label("amount"),
        )
        .join(DailyReport, DailyReport.id == DailyReportValue.report_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date == target_date,
            DailyReportValue.kind == "DEPT",
        )
        .group_by(DailyReportValue.ref_id)
    ).all()
    return {int(row.ref_id): int(row.amount or 0) * 100 for row in rows}


def list_department_month_plans(*, db: Session, venue_id: int, month_value: str) -> dict:
    month_date = date.fromisoformat(f"{month_value}-01")
    departments = _list_active_departments(db, venue_id=venue_id)
    by_department = {
        int(row.department_id): row
        for row in db.execute(
            select(DepartmentMonthPlan).where(
                DepartmentMonthPlan.venue_id == int(venue_id),
                DepartmentMonthPlan.month_start == month_date,
            )
        )
        .scalars()
        .all()
    }
    actual_current = _department_actuals_for_month(db, venue_id=venue_id, month_date=month_date)
    prev_month = (month_date - timedelta(days=1)).replace(day=1)
    actual_previous = _department_actuals_for_month(db, venue_id=venue_id, month_date=prev_month)
    items = []
    for dep in departments:
        row = by_department.get(int(dep.id))
        items.append(
            {
                "department_id": int(dep.id),
                "department_title": dep.title,
                "department_code": dep.code,
                "month": month_value,
                "revenue_plan_minor": int(row.revenue_plan_minor)
                if row is not None and row.revenue_plan_minor is not None
                else None,
                "notes": row.notes if row is not None else None,
                "actual_current_minor": int(actual_current.get(int(dep.id), 0) or 0),
                "actual_previous_minor": int(actual_previous.get(int(dep.id), 0) or 0),
            }
        )
    return {
        "month": month_value,
        "items": items,
        "department_count": len(items),
    }


def upsert_department_month_plans(*, db: Session, venue_id: int, month_value: str, items: list[dict]) -> dict:
    month_date = date.fromisoformat(f"{month_value}-01")
    allowed_ids = {int(dep.id) for dep in _list_active_departments(db, venue_id=venue_id)}
    existing = {
        int(row.department_id): row
        for row in db.execute(
            select(DepartmentMonthPlan).where(
                DepartmentMonthPlan.venue_id == int(venue_id),
                DepartmentMonthPlan.month_start == month_date,
            )
        )
        .scalars()
        .all()
    }
    touched = 0
    deleted = 0
    for item in items or []:
        dep_id = int(item.get("department_id") or 0)
        if dep_id <= 0 or dep_id not in allowed_ids:
            continue
        revenue_plan_minor = item.get("revenue_plan_minor")
        if revenue_plan_minor is not None:
            revenue_plan_minor = int(revenue_plan_minor)
        notes = (item.get("notes") or "").strip() or None
        row = existing.get(dep_id)
        should_delete = revenue_plan_minor is None and notes is None
        if should_delete:
            if row is not None:
                db.delete(row)
                deleted += 1
            continue
        if row is None:
            row = DepartmentMonthPlan(venue_id=int(venue_id), department_id=dep_id, month_start=month_date)
            db.add(row)
        row.revenue_plan_minor = revenue_plan_minor
        row.notes = notes
        row.updated_at = datetime.utcnow()
        touched += 1
    db.flush()
    result = list_department_month_plans(db=db, venue_id=venue_id, month_value=month_value)
    result["saved_count"] = touched
    result["deleted_count"] = deleted
    return result


def autofill_department_month_plans_from_last_month(
    *, db: Session, venue_id: int, month_value: str, overwrite: bool = True
) -> dict:
    month_date = date.fromisoformat(f"{month_value}-01")
    previous_month = (month_date - timedelta(days=1)).replace(day=1)
    previous_actual = _department_actuals_for_month(db, venue_id=venue_id, month_date=previous_month)
    existing = {
        int(row.department_id): row
        for row in db.execute(
            select(DepartmentMonthPlan).where(
                DepartmentMonthPlan.venue_id == int(venue_id),
                DepartmentMonthPlan.month_start == month_date,
            )
        )
        .scalars()
        .all()
    }
    copied = 0
    skipped = 0
    for dep in _list_active_departments(db, venue_id=venue_id):
        dep_id = int(dep.id)
        actual_minor = int(previous_actual.get(dep_id, 0) or 0)
        row = existing.get(dep_id)
        if row is not None and row.revenue_plan_minor is not None and not overwrite:
            skipped += 1
            continue
        if row is None:
            row = DepartmentMonthPlan(venue_id=int(venue_id), department_id=dep_id, month_start=month_date)
            db.add(row)
        row.revenue_plan_minor = actual_minor if actual_minor > 0 else None
        row.updated_at = datetime.utcnow()
        copied += 1
    db.flush()
    return {
        "copied": copied,
        "skipped": skipped,
        "copied_from_month": previous_month.strftime("%Y-%m"),
        "plan": list_department_month_plans(db=db, venue_id=venue_id, month_value=month_value),
    }


def distribute_department_month_plans_from_venue_plan(
    *, db: Session, venue_id: int, month_value: str, overwrite: bool = True
) -> dict:
    month_date = date.fromisoformat(f"{month_value}-01")
    departments = _list_active_departments(db, venue_id=venue_id)
    venue_plan = db.execute(
        select(DayEconomicsMonthPlan.revenue_plan_minor).where(
            DayEconomicsMonthPlan.venue_id == int(venue_id),
            DayEconomicsMonthPlan.month_start == month_date,
        )
    ).scalar_one_or_none()
    if venue_plan is None or int(venue_plan or 0) <= 0:
        raise ValueError("Нет месячного плана заведения для распределения")
    previous_month = (month_date - timedelta(days=1)).replace(day=1)
    previous_actual = _department_actuals_for_month(db, venue_id=venue_id, month_date=previous_month)
    total_previous = int(sum(int(previous_actual.get(int(dep.id), 0) or 0) for dep in departments))
    existing = {
        int(row.department_id): row
        for row in db.execute(
            select(DepartmentMonthPlan).where(
                DepartmentMonthPlan.venue_id == int(venue_id),
                DepartmentMonthPlan.month_start == month_date,
            )
        )
        .scalars()
        .all()
    }
    copied = 0
    skipped = 0
    department_count = max(len(departments), 1)
    base_plan_minor = int(venue_plan or 0)
    allocations: list[tuple[int, int]] = []
    if total_previous > 0:
        running = 0
        for index, dep in enumerate(departments, start=1):
            if index == len(departments):
                amount_minor = base_plan_minor - running
            else:
                amount_minor = int(
                    round(base_plan_minor * (int(previous_actual.get(int(dep.id), 0) or 0) / total_previous))
                )
                running += amount_minor
            allocations.append((int(dep.id), max(amount_minor, 0)))
    else:
        base = base_plan_minor // department_count
        rem = base_plan_minor - base * department_count
        for idx, dep in enumerate(departments):
            allocations.append((int(dep.id), base + (1 if idx < rem else 0)))
    for dep_id, amount_minor in allocations:
        row = existing.get(dep_id)
        if row is not None and row.revenue_plan_minor is not None and not overwrite:
            skipped += 1
            continue
        if row is None:
            row = DepartmentMonthPlan(venue_id=int(venue_id), department_id=dep_id, month_start=month_date)
            db.add(row)
        row.revenue_plan_minor = int(amount_minor)
        row.updated_at = datetime.utcnow()
        copied += 1
    db.flush()
    return {
        "copied": copied,
        "skipped": skipped,
        "distributed_total_minor": base_plan_minor,
        "copied_from_month": previous_month.strftime("%Y-%m"),
        "plan": list_department_month_plans(db=db, venue_id=venue_id, month_value=month_value),
    }


def list_department_day_plans(*, db: Session, venue_id: int, target_date: date) -> dict:
    departments = _list_active_departments(db, venue_id=venue_id)
    by_department = {
        int(row.department_id): row
        for row in db.execute(
            select(DepartmentDayPlan).where(
                DepartmentDayPlan.venue_id == int(venue_id),
                DepartmentDayPlan.target_date == target_date,
            )
        )
        .scalars()
        .all()
    }
    actual_current = _department_actuals_for_day(db, venue_id=venue_id, target_date=target_date)
    items = []
    for dep in departments:
        row = by_department.get(int(dep.id))
        items.append(
            {
                "department_id": int(dep.id),
                "department_title": dep.title,
                "department_code": dep.code,
                "date": target_date.isoformat(),
                "revenue_plan_minor": int(row.revenue_plan_minor)
                if row is not None and row.revenue_plan_minor is not None
                else None,
                "notes": row.notes if row is not None else None,
                "actual_current_minor": int(actual_current.get(int(dep.id), 0) or 0),
            }
        )
    return {
        "date": target_date.isoformat(),
        "items": items,
        "department_count": len(items),
    }


def upsert_department_day_plans(*, db: Session, venue_id: int, target_date: date, items: list[dict]) -> dict:
    allowed_ids = {int(dep.id) for dep in _list_active_departments(db, venue_id=venue_id)}
    existing = {
        int(row.department_id): row
        for row in db.execute(
            select(DepartmentDayPlan).where(
                DepartmentDayPlan.venue_id == int(venue_id),
                DepartmentDayPlan.target_date == target_date,
            )
        )
        .scalars()
        .all()
    }
    touched = 0
    deleted = 0
    for item in items or []:
        dep_id = int(item.get("department_id") or 0)
        if dep_id <= 0 or dep_id not in allowed_ids:
            continue
        revenue_plan_minor = item.get("revenue_plan_minor")
        if revenue_plan_minor is not None:
            revenue_plan_minor = int(revenue_plan_minor)
        notes = (item.get("notes") or "").strip() or None
        row = existing.get(dep_id)
        should_delete = revenue_plan_minor is None and notes is None
        if should_delete:
            if row is not None:
                db.delete(row)
                deleted += 1
            continue
        if row is None:
            row = DepartmentDayPlan(venue_id=int(venue_id), department_id=dep_id, target_date=target_date)
            db.add(row)
        row.revenue_plan_minor = revenue_plan_minor
        row.notes = notes
        row.updated_at = datetime.utcnow()
        touched += 1
    db.flush()
    result = list_department_day_plans(db=db, venue_id=venue_id, target_date=target_date)
    result["saved_count"] = touched
    result["deleted_count"] = deleted
    return result


def copy_department_day_plans_from_date(
    *, db: Session, venue_id: int, source_date: date, target_date: date, overwrite: bool = True
) -> dict:
    if source_date == target_date:
        raise ValueError("Дата-источник и дата-назначение совпадают")
    allowed_ids = {int(dep.id) for dep in _list_active_departments(db, venue_id=venue_id)}
    source_rows = {
        int(row.department_id): row
        for row in db.execute(
            select(DepartmentDayPlan).where(
                DepartmentDayPlan.venue_id == int(venue_id),
                DepartmentDayPlan.target_date == source_date,
            )
        )
        .scalars()
        .all()
    }
    existing = {
        int(row.department_id): row
        for row in db.execute(
            select(DepartmentDayPlan).where(
                DepartmentDayPlan.venue_id == int(venue_id),
                DepartmentDayPlan.target_date == target_date,
            )
        )
        .scalars()
        .all()
    }
    copied = 0
    skipped = 0
    for dep_id in sorted(allowed_ids):
        source = source_rows.get(dep_id)
        if source is None:
            skipped += 1
            continue
        row = existing.get(dep_id)
        if row is not None and (row.revenue_plan_minor is not None or (row.notes or "").strip()) and not overwrite:
            skipped += 1
            continue
        if row is None:
            row = DepartmentDayPlan(venue_id=int(venue_id), department_id=int(dep_id), target_date=target_date)
            db.add(row)
        row.revenue_plan_minor = int(source.revenue_plan_minor) if source.revenue_plan_minor is not None else None
        row.notes = source.notes
        row.updated_at = datetime.utcnow()
        copied += 1
    db.flush()
    return {
        "copied": copied,
        "skipped": skipped,
        "copied_from_date": source_date.isoformat(),
        "plan": list_department_day_plans(db=db, venue_id=venue_id, target_date=target_date),
    }


def autofill_department_day_plans_from_history(
    *,
    db: Session,
    venue_id: int,
    target_date: date,
    mode: str = "SAME_WEEKDAY_AVG",
    overwrite: bool = True,
    lookback_weeks: int = 4,
) -> dict:
    normalized_mode = str(mode or "SAME_WEEKDAY_AVG").strip().upper()
    if normalized_mode not in {"PREVIOUS_DAY", "PREVIOUS_WEEK", "SAME_WEEKDAY_AVG"}:
        raise ValueError("Неподдерживаемый режим автозаполнения")
    lookback_weeks = max(1, min(int(lookback_weeks or 4), 12))

    if normalized_mode == "PREVIOUS_DAY":
        source_dates = [target_date - timedelta(days=1)]
    elif normalized_mode == "PREVIOUS_WEEK":
        source_dates = [target_date - timedelta(days=7)]
    else:
        source_dates = [target_date - timedelta(days=7 * step) for step in range(1, lookback_weeks + 1)]

    allowed_ids = {int(dep.id) for dep in _list_active_departments(db, venue_id=venue_id)}
    existing = {
        int(row.department_id): row
        for row in db.execute(
            select(DepartmentDayPlan).where(
                DepartmentDayPlan.venue_id == int(venue_id),
                DepartmentDayPlan.target_date == target_date,
            )
        )
        .scalars()
        .all()
    }
    actuals_by_date = {
        src_date: _department_actuals_for_day(db, venue_id=venue_id, target_date=src_date) for src_date in source_dates
    }
    copied = 0
    skipped = 0
    used_points = 0
    for dep_id in sorted(allowed_ids):
        row = existing.get(dep_id)
        if row is not None and (row.revenue_plan_minor is not None or (row.notes or "").strip()) and not overwrite:
            skipped += 1
            continue
        values = [int((actuals_by_date.get(src_date) or {}).get(dep_id, 0) or 0) for src_date in source_dates]
        values = [value for value in values if value > 0]
        if not values:
            skipped += 1
            continue
        if normalized_mode == "SAME_WEEKDAY_AVG":
            revenue_plan_minor = int(round(sum(values) / len(values)))
        else:
            revenue_plan_minor = int(values[0])
        if row is None:
            row = DepartmentDayPlan(venue_id=int(venue_id), department_id=int(dep_id), target_date=target_date)
            db.add(row)
        row.revenue_plan_minor = revenue_plan_minor
        label = (
            "среднее похожих дней"
            if normalized_mode == "SAME_WEEKDAY_AVG"
            else ("вчерашний факт" if normalized_mode == "PREVIOUS_DAY" else "факт прошлой недели")
        )
        row.notes = f"Автозаполнено: {label}"
        row.updated_at = datetime.utcnow()
        copied += 1
        used_points = max(used_points, len(values))
    db.flush()
    return {
        "copied": copied,
        "skipped": skipped,
        "mode": normalized_mode,
        "lookback_weeks": lookback_weeks,
        "used_source_dates": [src.isoformat() for src in source_dates],
        "used_points": used_points,
        "plan": list_department_day_plans(db=db, venue_id=venue_id, target_date=target_date),
    }
