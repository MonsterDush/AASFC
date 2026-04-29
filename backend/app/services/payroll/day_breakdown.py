from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select, inspect
from sqlalchemy.orm import Session

from app.models import (
    Adjustment,
    DailyReport,
    DailyReportTipAllocation,
    DailyReportValue,
    PayrollLine,
    PayrollRecalculationLog,
    PayrollRun,
    Shift,
    ShiftAssignment,
    ShiftInterval,
    User,
    Venue,
    VenueMember,
)
from app.services.payroll.calculator import interval_duration_minutes
from app.services.shifts.slots import normalize_shift_slot


def _payroll_recalculation_logs_table_exists(db: Session) -> bool:
    try:
        return bool(inspect(db.get_bind()).has_table(PayrollRecalculationLog.__tablename__))
    except Exception:
        return True


_COMPONENT_TITLES = {
    "SALARY_FIXED_MONTH": "Оклад",
    "SALARY_HOURLY": "Почасовая ставка",
    "SALARY_PER_SHIFT": "Фикс за смену",
    "PERCENT_TOTAL_REVENUE": "% от общей выручки",
    "PERCENT_DEPARTMENT_REVENUE": "% от департамента",
    "KPI_BONUS": "KPI",
}


def _normalize_breakdown_shift_slot(value: str | None) -> str:
    raw = str(value or "TOTAL").strip().upper()
    if raw in {"DAY", "NIGHT"}:
        return normalize_shift_slot(raw)
    return "TOTAL"


def _is_slot_specific(value: str | None) -> bool:
    return _normalize_breakdown_shift_slot(value) in {"DAY", "NIGHT"}


@dataclass
class DayAllocationContext:
    shift_slot: str
    worked_dates: list[date]
    minutes_by_date: dict[date, int]
    shifts_by_date: dict[date, int]
    revenue_by_date_minor: dict[date, int]
    department_revenue_by_date_minor: dict[int, dict[date, int]]
    kpi_by_date: dict[int, dict[date, int]]


def _fmt_money_minor(value_minor: int | None) -> str:
    minor = int(value_minor or 0)
    sign = "-" if minor < 0 else ""
    abs_minor = abs(minor)
    if abs_minor % 100 == 0:
        rub = abs_minor // 100
        return f"{sign}{rub:,} ₽".replace(",", " ")
    rub = abs_minor / 100.0
    return f"{sign}{rub:,.2f} ₽".replace(",", " ")


def _fmt_hours(minutes: int | None) -> str:
    mins = int(minutes or 0)
    hours = mins / 60.0
    rendered = f"{hours:.2f}".rstrip("0").rstrip(".")
    return f"{rendered} ч"


def _safe_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


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
            value = [part.strip() for part in raw.split(",") if part.strip()]
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


def _component_department_ids(component: dict) -> list[int]:
    ids = _normalize_int_ids(component.get("department_ids"))
    legacy_id = int(component.get("department_id") or 0)
    if legacy_id > 0 and legacy_id not in ids:
        ids.insert(0, legacy_id)
    return ids


def _component_department_titles(component: dict, ids: list[int], *, prefix: str = "department") -> list[str]:
    raw_titles = component.get(f"{prefix}_titles")
    titles = [str(title) for title in raw_titles] if isinstance(raw_titles, list) else []
    out: list[str] = []
    for index, dep_id in enumerate(ids):
        if index < len(titles) and titles[index]:
            out.append(titles[index])
        else:
            single_title = component.get(f"{prefix}_title")
            if len(ids) == 1 and single_title:
                out.append(str(single_title))
            else:
                out.append(f"#{dep_id}")
    return out


def _sum_department_weights_by_date(
    department_revenue_by_date_minor: dict[int, dict[date, int]],
    department_ids: list[int],
    ordered_dates: list[date],
) -> dict[date, int]:
    weights: dict[date, int] = {}
    for day in ordered_dates:
        weights[day] = sum(
            int(department_revenue_by_date_minor.get(int(dep_id), {}).get(day, 0) or 0)
            for dep_id in department_ids
        )
    return weights


def _serialize_recalculation_log(row: PayrollRecalculationLog | None) -> dict | None:
    if row is None:
        return None
    target_dates: list[str] = []
    try:
        raw_dates = json.loads(row.target_dates_json) if row.target_dates_json else []
        if isinstance(raw_dates, list):
            target_dates = [str(item) for item in raw_dates if item]
    except Exception:
        target_dates = []
    return {
        "id": int(row.id),
        "period_month": row.period_month.strftime("%Y-%m") if getattr(row, "period_month", None) else None,
        "trigger_reason": str(row.trigger_reason or ""),
        "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
        "target_dates": target_dates,
    }


def _month_start_for_day(target_date: date) -> date:
    return date(target_date.year, target_date.month, 1)


def _next_month_start(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def _allocate_minor_by_keys(total_minor: int, ordered_keys: list[date], weights_by_key: dict[date, int] | None = None) -> dict[date, int]:
    keys = list(ordered_keys or [])
    if not keys:
        return {}

    sign = -1 if int(total_minor or 0) < 0 else 1
    abs_total = abs(int(total_minor or 0))

    prepared_weights: dict[date, int] = {}
    for key in keys:
        weight = int((weights_by_key or {}).get(key, 0) or 0)
        prepared_weights[key] = max(weight, 0)

    weight_total = sum(prepared_weights.values())
    if weight_total <= 0:
        prepared_weights = {key: 1 for key in keys}
        weight_total = len(keys)

    allocated: dict[date, int] = {}
    used = 0
    for key in keys:
        part = (abs_total * prepared_weights[key]) // weight_total
        allocated[key] = part
        used += part

    remainder = abs_total - used
    for key in keys:
        if remainder <= 0:
            break
        allocated[key] += 1
        remainder -= 1

    return {key: sign * int(value) for key, value in allocated.items()}


def _load_day_allocation_context(
    db: Session,
    *,
    venue_id: int,
    member_user_id: int,
    month_start: date,
    month_end_excl: date,
    worked_dates: list[date],
    shift_slot: str | None = None,
) -> DayAllocationContext:
    slot = _normalize_breakdown_shift_slot(shift_slot)
    worked_dates = sorted({day for day in worked_dates if isinstance(day, date)})
    if not worked_dates:
        return DayAllocationContext(
            shift_slot=slot,
            worked_dates=[],
            minutes_by_date={},
            shifts_by_date={},
            revenue_by_date_minor={},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )

    shift_filters = [Shift.shift_slot == slot] if slot in {"DAY", "NIGHT"} else []
    report_filters = [DailyReport.shift_slot == slot] if slot in {"DAY", "NIGHT"} else []

    shift_rows = db.execute(
        select(
            Shift.date.label("shift_date"),
            Shift.id.label("shift_id"),
            ShiftInterval.start_time,
            ShiftInterval.end_time,
        )
        .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
        .join(ShiftInterval, ShiftInterval.id == Shift.interval_id)
        .where(
            Shift.venue_id == int(venue_id),
            Shift.is_active.is_(True),
            Shift.date >= month_start,
            Shift.date < month_end_excl,
            Shift.date.in_(worked_dates),
            ShiftAssignment.member_user_id == int(member_user_id),
            *shift_filters,
        )
    ).all()

    minutes_by_date: dict[date, int] = defaultdict(int)
    shift_ids_by_date: dict[date, set[int]] = defaultdict(set)
    for row in shift_rows:
        shift_date = row.shift_date
        minutes_by_date[shift_date] += interval_duration_minutes(row.start_time, row.end_time)
        shift_ids_by_date[shift_date].add(int(row.shift_id))

    report_rows = db.execute(
        select(DailyReport.date, func.coalesce(func.sum(DailyReport.revenue_total), 0).label("revenue_total"))
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= month_start,
            DailyReport.date < month_end_excl,
            DailyReport.date.in_(worked_dates),
            *report_filters,
        )
        .group_by(DailyReport.date)
    ).all()
    revenue_by_date_minor = {row.date: int(row.revenue_total or 0) * 100 for row in report_rows}

    value_rows = db.execute(
        select(DailyReport.date, DailyReportValue.kind, DailyReportValue.ref_id, func.coalesce(func.sum(DailyReportValue.value_numeric), 0))
        .join(DailyReport, DailyReport.id == DailyReportValue.report_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date >= month_start,
            DailyReport.date < month_end_excl,
            DailyReport.date.in_(worked_dates),
            *report_filters,
        )
        .group_by(DailyReport.date, DailyReportValue.kind, DailyReportValue.ref_id)
    ).all()

    department_revenue_by_date_minor: dict[int, dict[date, int]] = defaultdict(dict)
    kpi_by_date: dict[int, dict[date, int]] = defaultdict(dict)
    for report_date, kind, ref_id, value_total in value_rows:
        if kind == "DEPT":
            department_revenue_by_date_minor[int(ref_id)][report_date] = int(value_total or 0) * 100
        elif kind == "KPI":
            kpi_by_date[int(ref_id)][report_date] = int(value_total or 0)

    return DayAllocationContext(
        shift_slot=slot,
        worked_dates=worked_dates,
        minutes_by_date={day: int(minutes_by_date.get(day, 0)) for day in worked_dates},
        shifts_by_date={day: len(shift_ids_by_date.get(day, set())) for day in worked_dates},
        revenue_by_date_minor={day: int(revenue_by_date_minor.get(day, 0)) for day in worked_dates},
        department_revenue_by_date_minor={
            int(dep_id): {day: int(amounts.get(day, 0)) for day in worked_dates}
            for dep_id, amounts in department_revenue_by_date_minor.items()
        },
        kpi_by_date={
            int(metric_id): {day: int(amounts.get(day, 0)) for day in worked_dates}
            for metric_id, amounts in kpi_by_date.items()
        },
    )


def _component_allocation_for_day(
    *,
    component: dict,
    target_date: date,
    context: DayAllocationContext,
) -> dict | None:
    component_type = str(component.get("component_type") or "").strip().upper()
    worked_dates = list(context.worked_dates or [])
    if not worked_dates or target_date not in worked_dates:
        return None

    ordered_dates = sorted(worked_dates)
    month_component_amount_minor = int(component.get("amount_minor") or 0)

    if component_type == "SALARY_HOURLY":
        weights = {day: int(context.minutes_by_date.get(day, 0)) for day in ordered_dates}
        base_text = f"{_fmt_hours(context.minutes_by_date.get(target_date, 0))} из {_fmt_hours(sum(weights.values()))}"
        rate_minor = component.get("source_rate_minor")
        formula_text = (
            f"{_fmt_money_minor(int(rate_minor or 0))}/ч × {_fmt_hours(context.minutes_by_date.get(target_date, 0))}"
            if rate_minor not in (None, "")
            else "Распределено по минутам дня внутри месячного hourly-компонента"
        )
    elif component_type == "SALARY_PER_SHIFT":
        weights = {day: int(context.shifts_by_date.get(day, 0)) for day in ordered_dates}
        base_text = f"{int(context.shifts_by_date.get(target_date, 0))} смен из {sum(weights.values())}"
        source_amount_minor = component.get("source_amount_minor")
        formula_text = (
            f"{_fmt_money_minor(int(source_amount_minor or 0))} × {int(context.shifts_by_date.get(target_date, 0))} смен"
            if source_amount_minor not in (None, "")
            else "Распределено по количеству смен"
        )
    elif component_type == "SALARY_FIXED_MONTH":
        weights = {day: 1 for day in ordered_dates}
        base_text = f"1 день из {len(ordered_dates)}"
        source_amount_minor = component.get("source_amount_minor", month_component_amount_minor)
        formula_text = f"{_fmt_money_minor(int(source_amount_minor or 0))} / {len(ordered_dates)} рабочих дней"
    elif component_type == "PERCENT_TOTAL_REVENUE":
        day_rows = [row for row in (component.get("day_rows") or []) if isinstance(row, dict)]
        day_snapshot = next((row for row in day_rows if str(row.get("date") or "") == target_date.isoformat()), None)
        if day_snapshot is not None:
            amount_minor = int(day_snapshot.get("amount_minor") or 0)
            if amount_minor == 0:
                return None
            percent_bps = int(day_snapshot.get("percent_bps") or component.get("percent_bps") or component.get("source_percent_bps") or 0)
            actual_minor = day_snapshot.get("actual_amount_minor")
            target_minor = day_snapshot.get("target_amount_minor")
            base_text = f"база {_fmt_money_minor(day_snapshot.get('base_amount_minor'))}"
            if actual_minor is not None:
                base_text += f" · факт {_fmt_money_minor(actual_minor)}"
            if target_minor is not None:
                base_text += f" · цель {_fmt_money_minor(target_minor)}"
            formula_text = f"{(percent_bps / 100):.2f}% от базы дня"
            if day_snapshot.get("boost_applied"):
                formula_text += " · план выполнен"
            if day_snapshot.get("minimum_applied"):
                formula_text += f" · дневная минималка {_fmt_money_minor(day_snapshot.get('amount_minor'))}"
        else:
            weights = {day: int(context.revenue_by_date_minor.get(day, 0)) for day in ordered_dates}
            base_text = f"{_fmt_money_minor(context.revenue_by_date_minor.get(target_date, 0))} из {_fmt_money_minor(sum(weights.values()))}"
            percent_bps = component.get("percent_bps") or component.get("source_percent_bps")
            if percent_bps not in (None, ""):
                formula_text = f"{(int(percent_bps) / 100):.2f}% от общей выручки месяца, доля дня по выручке"
            else:
                formula_text = "Распределено по выручке дня"
            allocation = _allocate_minor_by_keys(month_component_amount_minor, ordered_dates, weights)
            amount_minor = int(allocation.get(target_date, 0))
            if amount_minor == 0:
                return None
            title = str(component.get("title") or _COMPONENT_TITLES.get(component_type) or "Компонент").strip()
            return {
                "category": "earning",
                "source": "payroll_component",
                "component_type": component_type,
                "title": title,
                "base_text": base_text,
                "formula_text": formula_text,
                "amount_minor": amount_minor,
                "month_component_amount_minor": month_component_amount_minor,
                "month_share_ratio": None,
                "is_estimated": False,
            }
        title = str(component.get("title") or _COMPONENT_TITLES.get(component_type) or "Компонент").strip()
        return {
            "category": "earning",
            "source": "payroll_component",
            "component_type": component_type,
            "title": title,
            "base_text": base_text,
            "formula_text": formula_text,
            "amount_minor": amount_minor,
            "month_component_amount_minor": month_component_amount_minor,
            "month_share_ratio": None,
            "is_estimated": False,
        }
    elif component_type == "PERCENT_DEPARTMENT_REVENUE":
        department_ids = _component_department_ids(component)
        dep_titles = _component_department_titles(component, department_ids, prefix="department")
        dep_title = " + ".join(dep_titles) if dep_titles else "департаментов"
        day_rows = [row for row in (component.get("day_rows") or []) if isinstance(row, dict)]
        day_snapshot = next((row for row in day_rows if str(row.get("date") or "") == target_date.isoformat()), None)
        if day_snapshot is not None:
            amount_minor = int(day_snapshot.get("amount_minor") or 0)
            if amount_minor == 0:
                return None
            percent_bps = int(day_snapshot.get("percent_bps") or component.get("percent_bps") or component.get("source_percent_bps") or 0)
            actual_minor = day_snapshot.get("actual_amount_minor")
            target_minor = day_snapshot.get("target_amount_minor")
            base_text = f"база {_fmt_money_minor(day_snapshot.get('base_amount_minor'))}"
            if actual_minor is not None:
                base_text += f" · факт {_fmt_money_minor(actual_minor)}"
            if target_minor is not None:
                base_text += f" · цель {_fmt_money_minor(target_minor)}"
            formula_text = f"{(percent_bps / 100):.2f}% от {dep_title}"
            if day_snapshot.get("boost_applied"):
                formula_text += " · план выполнен"
            if day_snapshot.get("minimum_applied"):
                formula_text += f" · дневная минималка {_fmt_money_minor(day_snapshot.get('amount_minor'))}"
        else:
            weights = _sum_department_weights_by_date(context.department_revenue_by_date_minor, department_ids, ordered_dates)
            base_text = f"{_fmt_money_minor(weights.get(target_date, 0))} из {_fmt_money_minor(sum(weights.values()))}"
            percent_bps = component.get("percent_bps") or component.get("source_percent_bps")
            if percent_bps not in (None, ""):
                formula_text = f"{(int(percent_bps) / 100):.2f}% от {dep_title}, доля дня по выручке"
            else:
                formula_text = f"Распределено по выручке {dep_title}"
            allocation = _allocate_minor_by_keys(month_component_amount_minor, ordered_dates, weights)
            amount_minor = int(allocation.get(target_date, 0))
            if amount_minor == 0:
                return None
            title = str(component.get("title") or _COMPONENT_TITLES.get(component_type) or "Компонент").strip()
            return {
                "category": "earning",
                "source": "payroll_component",
                "component_type": component_type,
                "title": title,
                "base_text": base_text,
                "formula_text": formula_text,
                "amount_minor": amount_minor,
                "month_component_amount_minor": month_component_amount_minor,
                "month_share_ratio": None,
                "is_estimated": False,
            }
        title = str(component.get("title") or _COMPONENT_TITLES.get(component_type) or "Компонент").strip()
        return {
            "category": "earning",
            "source": "payroll_component",
            "component_type": component_type,
            "title": title,
            "base_text": base_text,
            "formula_text": formula_text,
            "amount_minor": amount_minor,
            "month_component_amount_minor": month_component_amount_minor,
            "month_share_ratio": None,
            "is_estimated": False,
        }
    elif component_type == "KPI_BONUS":
        metric_id = int(component.get("kpi_metric_id") or 0)
        metric_weights = context.kpi_by_date.get(metric_id, {})
        weights = {day: int(metric_weights.get(day, 0)) for day in ordered_dates}
        metric_title = str(component.get("kpi_metric_title") or "KPI").strip()
        base_text = f"{int(metric_weights.get(target_date, 0) or 0)} из {sum(weights.values())}"
        matched_step = component.get("matched_step") or {}
        if matched_step:
            formula_text = f"{metric_title}: сработала ступень ≥ {int(matched_step.get('threshold_value') or 0)}"
        else:
            threshold_value = component.get("threshold_value")
            if threshold_value is not None:
                formula_text = f"{metric_title}: бонус с порогом {int(threshold_value)}"
            else:
                formula_text = f"{metric_title}: бонус распределён по KPI дня"
    else:
        weights = {day: 1 for day in ordered_dates}
        base_text = f"1 день из {len(ordered_dates)}"
        formula_text = "Распределено равномерно по рабочим дням"

    allocation = _allocate_minor_by_keys(month_component_amount_minor, ordered_dates, weights)
    amount_minor = int(allocation.get(target_date, 0))
    if amount_minor == 0:
        return None

    title = str(component.get("title") or _COMPONENT_TITLES.get(component_type) or "Компонент").strip()
    return {
        "category": "earning",
        "source": "payroll_component",
        "component_type": component_type,
        "title": title,
        "base_text": base_text,
        "formula_text": formula_text,
        "amount_minor": amount_minor,
        "month_component_amount_minor": month_component_amount_minor,
        "month_share_ratio": None,
        "is_estimated": False,
    }


def build_member_day_breakdown(
    db: Session,
    *,
    member_user_id: int,
    venue_id: int,
    target_date: date,
    shift_slot: str | None = None,
) -> dict:
    slot = _normalize_breakdown_shift_slot(shift_slot)
    month_start = _month_start_for_day(target_date)
    month_end_excl = _next_month_start(month_start)

    venue = db.execute(select(Venue).where(Venue.id == int(venue_id))).scalar_one_or_none()
    member = db.execute(select(User).where(User.id == int(member_user_id))).scalar_one_or_none()
    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.user_id == int(member_user_id),
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()

    line_row = db.execute(
        select(PayrollLine, PayrollRun)
        .join(PayrollRun, PayrollRun.id == PayrollLine.payroll_run_id)
        .where(
            PayrollLine.venue_id == int(venue_id),
            PayrollLine.member_user_id == int(member_user_id),
            PayrollRun.period_month == month_start,
        )
        .order_by(PayrollLine.id.desc())
    ).first()

    payroll_line = line_row[0] if line_row else None
    payroll_run = line_row[1] if line_row else None
    breakdown = _safe_json(getattr(payroll_line, "breakdown_json", None))
    latest_recalculation = None
    if _payroll_recalculation_logs_table_exists(db):
        latest_recalculation = db.execute(
            select(PayrollRecalculationLog)
            .where(
                PayrollRecalculationLog.venue_id == int(venue_id),
                PayrollRecalculationLog.period_month == month_start,
            )
            .order_by(PayrollRecalculationLog.created_at.desc(), PayrollRecalculationLog.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    metrics = breakdown.get("metrics") if isinstance(breakdown.get("metrics"), dict) else {}
    worked_dates = []
    for raw_day in (metrics.get("worked_dates") or []):
        try:
            worked_dates.append(date.fromisoformat(str(raw_day)))
        except Exception:
            continue

    context = _load_day_allocation_context(
        db,
        venue_id=int(venue_id),
        member_user_id=int(member_user_id),
        month_start=month_start,
        month_end_excl=month_end_excl,
        worked_dates=worked_dates,
        shift_slot=slot,
    )

    items: list[dict] = []
    # Payroll lines are stored at month/date level, not per DAY/NIGHT slot.
    # Keep TOTAL fully detailed; for a single slot expose slot-specific context/tips
    # without duplicating a full monthly component into both DAY and NIGHT.
    if slot == "TOTAL":
        for component in (breakdown.get("components") or []):
            if not isinstance(component, dict):
                continue
            item = _component_allocation_for_day(component=component, target_date=target_date, context=context)
            if item is not None:
                items.append(item)

    tip_rows = db.execute(
        select(DailyReportTipAllocation.amount)
        .join(DailyReport, DailyReport.id == DailyReportTipAllocation.report_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date == target_date,
            DailyReportTipAllocation.user_id == int(member_user_id),
            *([DailyReport.shift_slot == slot] if slot in {"DAY", "NIGHT"} else []),
        )
    ).all()
    allocated_tips_minor = sum(int(row.amount or 0) * 100 for row in tip_rows)
    if allocated_tips_minor:
        items.append(
            {
                "category": "tip",
                "source": "report_tip_allocation",
                "component_type": "TIP",
                "title": "Чаевые из отчёта",
                "base_text": _format_date_context(target_date),
                "formula_text": "Распределено из закрытого отчёта смены",
                "amount_minor": allocated_tips_minor,
                "is_estimated": False,
            }
        )

    adjustment_rows = []
    if slot == "TOTAL":
        adjustment_rows = db.execute(
            select(Adjustment.type, Adjustment.amount, Adjustment.reason)
            .where(
                Adjustment.venue_id == int(venue_id),
                Adjustment.member_user_id == int(member_user_id),
                Adjustment.date == target_date,
                Adjustment.is_active.is_(True),
            )
            .order_by(Adjustment.id.asc())
        ).all()
    for adj_type, amount, reason in adjustment_rows:
        adj_type_str = str(adj_type or "").lower()
        amount_minor = int(amount or 0) * 100
        if amount_minor <= 0:
            continue
        if adj_type_str == "bonus":
            category = "bonus"
            signed_minor = amount_minor
            title = "Премия"
        elif adj_type_str == "tip":
            category = "tip"
            signed_minor = amount_minor
            title = "Ручные чаевые"
        elif adj_type_str == "writeoff":
            category = "writeoff"
            signed_minor = -amount_minor
            title = "Списание"
        else:
            category = "penalty"
            signed_minor = -amount_minor
            title = "Штраф"
        formula_text = "Добавлено вручную"
        if reason:
            formula_text = f"{formula_text}: {str(reason).strip()[:200]}"
        items.append(
            {
                "category": category,
                "source": "adjustment",
                "component_type": adj_type_str.upper() or "ADJUSTMENT",
                "title": title,
                "base_text": _format_date_context(target_date),
                "formula_text": formula_text,
                "amount_minor": signed_minor,
                "is_estimated": False,
            }
        )

    items.sort(key=lambda item: (0 if int(item.get("amount_minor") or 0) >= 0 else 1, str(item.get("title") or "")))

    earnings_minor = sum(int(item.get("amount_minor") or 0) for item in items if item.get("category") == "earning")
    tips_minor = sum(int(item.get("amount_minor") or 0) for item in items if item.get("category") == "tip")
    bonuses_minor = sum(int(item.get("amount_minor") or 0) for item in items if item.get("category") == "bonus")
    penalties_minor = -sum(int(item.get("amount_minor") or 0) for item in items if item.get("category") in {"penalty", "writeoff"})
    total_minor = earnings_minor + bonuses_minor - penalties_minor

    day_minutes = int(context.minutes_by_date.get(target_date, 0))
    day_shifts = int(context.shifts_by_date.get(target_date, 0))
    day_revenue_minor = int(context.revenue_by_date_minor.get(target_date, 0))
    state = "ready" if items else "empty"
    if slot in {"DAY", "NIGHT"}:
        state = "slot_limited" if items else "slot_empty"
    elif payroll_line is None and (tips_minor or bonuses_minor or penalties_minor):
        state = "partial"
    elif payroll_line is None and not items:
        state = "no_payroll"

    return {
        "state": state,
        "shift_slot": slot,
        "venue": {
            "id": int(venue.id) if venue is not None else int(venue_id),
            "name": getattr(venue, "name", None) or "",
        },
        "member": {
            "user_id": int(member.id) if member is not None else int(member_user_id),
            "name": getattr(member, "short_name", None) or getattr(member, "full_name", None) or getattr(member, "tg_username", None) or f"user #{member_user_id}",
            "venue_role": getattr(vm, "venue_role", None) if vm is not None else None,
        },
        "date": target_date.isoformat(),
        "month": month_start.strftime("%Y-%m"),
        "summary": {
            "earnings_minor": earnings_minor,
            "tips_minor": tips_minor,
            "bonuses_minor": bonuses_minor,
            "penalties_minor": penalties_minor,
            "total_minor": total_minor,
        },
        "context": {
            "minutes_total": day_minutes,
            "hours_total": round(day_minutes / 60.0, 2),
            "shifts_count": day_shifts,
            "revenue_minor": day_revenue_minor,
            "slot_payroll_detail_available": slot == "TOTAL",
            "slot_adjustments_available": slot == "TOTAL",
            "slot_note": ("Детализация оклада/процентов и ручные корректировки доступны в Итого" if slot in {"DAY", "NIGHT"} else None),
            "has_payroll_line": payroll_line is not None,
            "payroll_line_id": int(payroll_line.id) if payroll_line is not None else None,
            "pay_profile_title": breakdown.get("pay_profile_title") if breakdown else None,
            "calculated_at": payroll_run.calculated_at.isoformat() if payroll_run is not None and getattr(payroll_run, "calculated_at", None) else None,
            "latest_recalculation": _serialize_recalculation_log(latest_recalculation),
        },
        "items": items,
    }


def _format_date_context(target_date: date) -> str:
    return target_date.isoformat()
