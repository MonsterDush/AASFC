from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import json

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import DailyReport, DailyReportValue, DayEconomicsMonthPlan, DayEconomicsPlan, DayEconomicsPlanTemplate, DepartmentDayPlan, DepartmentMonthPlan, PayComponent, PayProfile, PayProfileAssignment, PayrollLine, PayrollRun, Shift, ShiftAssignment, ShiftInterval, User
from app.services.finance.ledger import create_finance_entry, delete_finance_entries_for_source


PAY_COMPONENT_TYPES = {
    "SALARY_FIXED_MONTH",
    "SALARY_HOURLY",
    "SALARY_PER_SHIFT",
    "PERCENT_TOTAL_REVENUE",
    "PERCENT_DEPARTMENT_REVENUE",
    "KPI_BONUS",
}

BASE_SCOPE_FULL_PERIOD = "FULL_PERIOD"
BASE_SCOPE_WORKED_DATES = "WORKED_DATES"

BOOST_SOURCE_NONE = "NONE"
BOOST_SOURCE_VENUE_MONTH_PLAN = "VENUE_MONTH_PLAN"
BOOST_SOURCE_VENUE_DAY_PLAN = "VENUE_DAY_PLAN"
BOOST_SOURCE_DEPARTMENT_MONTH_PLAN = "DEPARTMENT_MONTH_PLAN"
BOOST_SOURCE_DEPARTMENT_DAY_PLAN = "DEPARTMENT_DAY_PLAN"
BOOST_SOURCE_KPI_METRIC = "KPI_METRIC"

BOOST_RECALC_REPLACE_ALL = "REPLACE_ALL"
BOOST_RECALC_EXCESS_ONLY = "EXCESS_ONLY"

BASE_SCOPE_TITLES = {
    BASE_SCOPE_FULL_PERIOD: "по всему периоду",
    BASE_SCOPE_WORKED_DATES: "по отработанным дням",
}
BOOST_SOURCE_TITLES = {
    BOOST_SOURCE_NONE: "без условия",
    BOOST_SOURCE_VENUE_MONTH_PLAN: "месячный план заведения",
    BOOST_SOURCE_VENUE_DAY_PLAN: "суточный план заведения",
    BOOST_SOURCE_DEPARTMENT_MONTH_PLAN: "месячный план департамента",
    BOOST_SOURCE_DEPARTMENT_DAY_PLAN: "суточный план департамента",
    BOOST_SOURCE_KPI_METRIC: "KPI",
}
BOOST_RECALC_TITLES = {
    BOOST_RECALC_REPLACE_ALL: "весь объём",
    BOOST_RECALC_EXCESS_ONLY: "только превышение",
}


@dataclass
class PayrollMemberMetrics:
    minutes_total: int = 0
    shifts_count: int = 0
    worked_dates: set[date] = field(default_factory=set)


@dataclass
class PayrollRevenueMetrics:
    total_revenue_minor: int = 0
    total_revenue_by_date_minor: dict[date, int] = field(default_factory=dict)
    department_revenue_minor: dict[int, int] = field(default_factory=dict)
    department_revenue_by_date_minor: dict[int, dict[date, int]] = field(default_factory=dict)


@dataclass
class PayrollKpiMetrics:
    totals_by_metric_id: dict[int, int] = field(default_factory=dict)


@dataclass
class PayrollCalculationResult:
    run: PayrollRun
    lines: list[PayrollLine]


@dataclass
class PayrollKpiBonusDecision:
    amount_minor: int
    metric_value: int
    threshold_value: int | None = None
    matched_step: dict | None = None
    steps: list[dict] = field(default_factory=list)


@dataclass
class PayrollVenuePlanMetrics:
    month_revenue_target_minor: int | None = None
    day_revenue_target_by_date_minor: dict[date, int | None] = field(default_factory=dict)
    department_month_revenue_target_minor: dict[int, int | None] = field(default_factory=dict)
    department_day_revenue_target_by_date_minor: dict[int, dict[date, int | None]] = field(default_factory=dict)


@dataclass
class PayrollPercentDecision:
    amount_minor: int
    base_amount_minor: int
    base_scope: str
    regular_percent_bps: int
    applied_percent_bps: int
    regular_amount_minor: int
    boost_enabled: bool
    boost_applied: bool
    boost_source_type: str
    boost_source_title: str
    boost_recalc_mode: str
    boost_recalc_mode_effective: str
    boost_recalc_mode_title: str
    boost_percent_bps: int | None = None
    boost_target_minor: int | None = None
    boost_actual_minor: int | None = None
    boost_target_value: int | None = None
    boost_actual_value: int | None = None
    boost_kpi_metric_id: int | None = None
    minimum_guarantee_minor: int | None = None
    maximum_cap_minor: int | None = None
    minimum_applied: bool = False
    maximum_applied: bool = False
    day_rows: list[dict] = field(default_factory=list)


def _build_percent_component_snapshot(component: PayComponent, decision: PayrollPercentDecision) -> dict:
    snapshot = {
        "kind": "percent_component",
        "component_type": str(getattr(component, "component_type", "") or ""),
        "base_scope": decision.base_scope,
        "base_scope_title": BASE_SCOPE_TITLES.get(decision.base_scope, decision.base_scope),
        "base_amount_minor": int(decision.base_amount_minor),
        "regular_percent_bps": int(decision.regular_percent_bps),
        "applied_percent_bps": int(decision.applied_percent_bps),
        "regular_amount_minor": int(decision.regular_amount_minor),
        "final_amount_minor": int(decision.amount_minor),
        "boost_enabled": bool(decision.boost_enabled),
        "boost_applied": bool(decision.boost_applied),
        "boost_source_type": decision.boost_source_type,
        "boost_source_title": decision.boost_source_title,
        "boost_recalc_mode": decision.boost_recalc_mode,
        "boost_recalc_mode_effective": decision.boost_recalc_mode_effective,
        "boost_recalc_mode_title": decision.boost_recalc_mode_title,
        "boost_percent_bps": int(decision.boost_percent_bps) if decision.boost_percent_bps is not None else None,
        "boost_target_minor": int(decision.boost_target_minor) if decision.boost_target_minor is not None else None,
        "boost_actual_minor": int(decision.boost_actual_minor) if decision.boost_actual_minor is not None else None,
        "boost_target_value": int(decision.boost_target_value) if decision.boost_target_value is not None else None,
        "boost_actual_value": int(decision.boost_actual_value) if decision.boost_actual_value is not None else None,
        "boost_department_id": int(getattr(component, "boost_department_id", 0) or 0) if getattr(component, "boost_department_id", None) is not None else None,
        "boost_department_title": getattr(getattr(component, "boost_department", None), "title", None),
        "boost_kpi_metric_id": int(decision.boost_kpi_metric_id) if decision.boost_kpi_metric_id is not None else None,
        "boost_kpi_metric_title": getattr(getattr(component, "boost_kpi_metric", None), "title", None),
        "minimum_guarantee_minor": int(decision.minimum_guarantee_minor) if decision.minimum_guarantee_minor is not None else None,
        "maximum_cap_minor": int(decision.maximum_cap_minor) if decision.maximum_cap_minor is not None else None,
        "minimum_applied": bool(decision.minimum_applied),
        "maximum_applied": bool(decision.maximum_applied),
        "department_id": int(getattr(component, "department_id", 0) or 0) if getattr(component, "department_id", None) is not None else None,
        "department_title": getattr(getattr(component, "department", None), "title", None),
        "day_rows": [dict(row) for row in (decision.day_rows or [])],
    }
    return snapshot


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


def _rub_to_minor(value: object) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        normalized = value.strip().replace(",", ".")
        if not normalized:
            return None
        try:
            num = float(normalized)
        except Exception:
            return None
    else:
        try:
            num = float(value)
        except Exception:
            return None
    if num < 0:
        return None
    return int(round(num * 100))


def _parse_steps_json(raw: object) -> list[dict]:
    if raw is None:
        return []
    value = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except Exception:
            return []

    if isinstance(value, dict):
        candidate = value.get("steps")
        if isinstance(candidate, list):
            value = candidate
        else:
            return []

    if not isinstance(value, list):
        return []

    out: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        threshold_value = item.get("threshold_value")
        amount_minor = item.get("amount_minor")
        if amount_minor in (None, ""):
            amount_minor = _rub_to_minor(item.get("amount_rub"))
        try:
            threshold_value = int(threshold_value)
            amount_minor = int(amount_minor)
        except Exception:
            continue
        if threshold_value < 0 or amount_minor < 0:
            continue
        normalized = {
            "threshold_value": threshold_value,
            "amount_minor": amount_minor,
        }
        if item.get("title") not in (None, ""):
            normalized["title"] = str(item.get("title"))
        out.append(normalized)

    out.sort(key=lambda row: (int(row.get("threshold_value") or 0), int(row.get("amount_minor") or 0)))
    return out


def calculate_kpi_bonus(
    component: PayComponent,
    *,
    kpi_metric_value: int = 0,
) -> PayrollKpiBonusDecision:
    metric_value = int(kpi_metric_value or 0)
    steps = _parse_steps_json(getattr(component, "steps_json", None))
    threshold_value = getattr(component, "threshold_value", None)
    threshold_value = int(threshold_value) if threshold_value is not None else None

    if steps:
        matched_step = None
        for step in steps:
            if metric_value >= int(step.get("threshold_value") or 0):
                matched_step = step
            else:
                break
        return PayrollKpiBonusDecision(
            amount_minor=int(matched_step.get("amount_minor") or 0) if matched_step is not None else 0,
            metric_value=metric_value,
            threshold_value=threshold_value,
            matched_step=matched_step,
            steps=steps,
        )

    amount_minor = int(getattr(component, "amount_minor", 0) or 0)
    if threshold_value is None or metric_value >= threshold_value:
        return PayrollKpiBonusDecision(
            amount_minor=amount_minor,
            metric_value=metric_value,
            threshold_value=threshold_value,
            matched_step=None,
            steps=[],
        )
    return PayrollKpiBonusDecision(
        amount_minor=0,
        metric_value=metric_value,
        threshold_value=threshold_value,
        matched_step=None,
        steps=[],
    )


def calculate_component_amount_minor(
    component: PayComponent,
    *,
    minutes_total: int,
    shifts_count: int,
    total_revenue_minor: int = 0,
    department_revenue_minor: int = 0,
    kpi_metric_value: int = 0,
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

    if component_type == "KPI_BONUS":
        return int(calculate_kpi_bonus(component, kpi_metric_value=kpi_metric_value).amount_minor)

    return 0




def _round_percent_amount(base_amount_minor: int, percent_bps: int) -> int:
    return int((int(base_amount_minor) * int(percent_bps) + 5000) // 10000)


def _component_base_scope(component: PayComponent) -> str:
    raw = str(getattr(component, "base_scope", "") or "").strip().upper()
    if raw in {BASE_SCOPE_FULL_PERIOD, BASE_SCOPE_WORKED_DATES}:
        return raw
    component_type = str(getattr(component, "component_type", "") or "").strip().upper()
    if component_type == "PERCENT_DEPARTMENT_REVENUE":
        return BASE_SCOPE_WORKED_DATES
    return BASE_SCOPE_FULL_PERIOD


def _component_boost_source_type(component: PayComponent) -> str:
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


def _component_boost_recalc_mode(component: PayComponent) -> str:
    raw = str(getattr(component, "boost_recalc_mode", "") or "").strip().upper()
    if raw == BOOST_RECALC_EXCESS_ONLY:
        return BOOST_RECALC_EXCESS_ONLY
    return BOOST_RECALC_REPLACE_ALL


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


def _build_percent_component_decision(
    component: PayComponent,
    *,
    metrics: PayrollMemberMetrics,
    revenue_metrics: PayrollRevenueMetrics,
    kpi_metrics: PayrollKpiMetrics,
    venue_plan_metrics: PayrollVenuePlanMetrics,
) -> PayrollPercentDecision:
    component_type = str(component.component_type or "").strip().upper()
    if component_type not in {"PERCENT_TOTAL_REVENUE", "PERCENT_DEPARTMENT_REVENUE"}:
        raise ValueError(f"Unsupported percent component type: {component.component_type}")

    base_scope = _component_base_scope(component)
    regular_percent_bps = int(component.percent_bps or 0)
    boost_percent_bps = int(component.boost_percent_bps or 0) if getattr(component, "boost_percent_bps", None) is not None else None
    boost_source_type = _component_boost_source_type(component)
    boost_source_title = BOOST_SOURCE_TITLES.get(boost_source_type, boost_source_type or BOOST_SOURCE_NONE)
    boost_recalc_mode = _component_boost_recalc_mode(component)
    boost_department_id = int(component.boost_department_id or component.department_id or 0) if getattr(component, "boost_department_id", None) is not None or getattr(component, "department_id", None) is not None else 0
    boost_recalc_mode_effective = boost_recalc_mode
    minimum_guarantee_minor = int(component.minimum_guarantee_minor or 0) if getattr(component, "minimum_guarantee_minor", None) is not None else None
    maximum_cap_minor = int(component.maximum_cap_minor or 0) if getattr(component, "maximum_cap_minor", None) is not None else None

    if component_type == "PERCENT_TOTAL_REVENUE":
        source_by_date = revenue_metrics.total_revenue_by_date_minor
    else:
        source_by_date = revenue_metrics.department_revenue_by_date_minor.get(int(component.department_id or 0), {})

    if base_scope == BASE_SCOPE_WORKED_DATES:
        base_by_date = {
            day: int(source_by_date.get(day) or 0)
            for day in sorted(metrics.worked_dates)
            if day in source_by_date
        }
    else:
        base_by_date = {day: int(amount or 0) for day, amount in sorted(source_by_date.items(), key=lambda item: item[0])}

    base_amount_minor = int(sum(int(amount or 0) for amount in base_by_date.values()))
    regular_amount_minor = _round_percent_amount(base_amount_minor, regular_percent_bps)

    boost_enabled = bool(
        getattr(component, "boost_enabled", False)
        and boost_percent_bps is not None
        and boost_percent_bps > 0
        and boost_source_type != BOOST_SOURCE_NONE
    )

    amount_minor = int(regular_amount_minor)
    applied_percent_bps = int(regular_percent_bps)
    boost_applied = False
    boost_target_minor: int | None = None
    boost_actual_minor: int | None = None
    boost_target_value: int | None = None
    boost_actual_value: int | None = None
    day_rows: list[dict] = []

    if boost_enabled and base_amount_minor > 0:
        if boost_source_type == BOOST_SOURCE_VENUE_MONTH_PLAN:
            boost_target_minor = venue_plan_metrics.month_revenue_target_minor
            boost_actual_minor = int(revenue_metrics.total_revenue_minor)
            boost_applied = boost_target_minor is not None and boost_actual_minor >= boost_target_minor
            if boost_applied:
                excess_supported = component_type == "PERCENT_TOTAL_REVENUE" and base_scope == BASE_SCOPE_FULL_PERIOD
                if boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY and excess_supported and boost_target_minor is not None:
                    regular_part = _round_percent_amount(min(base_amount_minor, boost_target_minor), regular_percent_bps)
                    boost_part = _round_percent_amount(max(base_amount_minor - boost_target_minor, 0), int(boost_percent_bps or 0))
                    amount_minor = int(regular_part + boost_part)
                else:
                    if boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY and not excess_supported:
                        boost_recalc_mode_effective = BOOST_RECALC_REPLACE_ALL
                    amount_minor = _round_percent_amount(base_amount_minor, int(boost_percent_bps or 0))
                applied_percent_bps = int(boost_percent_bps or 0)

        elif boost_source_type == BOOST_SOURCE_VENUE_DAY_PLAN:
            excess_supported = component_type == "PERCENT_TOTAL_REVENUE"
            amount_minor = 0
            applied_days_count = 0
            for day, base_day_minor in sorted(base_by_date.items(), key=lambda item: item[0]):
                actual_day_minor = int(revenue_metrics.total_revenue_by_date_minor.get(day) or 0)
                target_day_minor = venue_plan_metrics.day_revenue_target_by_date_minor.get(day)
                day_boost_applied = target_day_minor is not None and actual_day_minor >= int(target_day_minor or 0)
                day_percent_bps = regular_percent_bps
                if day_boost_applied:
                    applied_days_count += 1
                    day_percent_bps = int(boost_percent_bps or 0)
                    if boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY and excess_supported and target_day_minor is not None:
                        regular_part = _round_percent_amount(min(base_day_minor, int(target_day_minor)), regular_percent_bps)
                        boost_part = _round_percent_amount(max(base_day_minor - int(target_day_minor), 0), int(boost_percent_bps or 0))
                        day_amount_minor = int(regular_part + boost_part)
                    else:
                        if boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY and not excess_supported:
                            boost_recalc_mode_effective = BOOST_RECALC_REPLACE_ALL
                        day_amount_minor = _round_percent_amount(base_day_minor, int(boost_percent_bps or 0))
                else:
                    day_amount_minor = _round_percent_amount(base_day_minor, regular_percent_bps)
                amount_minor += int(day_amount_minor)
                day_rows.append(
                    {
                        "date": day.isoformat(),
                        "base_amount_minor": int(base_day_minor),
                        "actual_amount_minor": int(actual_day_minor),
                        "target_amount_minor": int(target_day_minor) if target_day_minor is not None else None,
                        "boost_applied": bool(day_boost_applied),
                        "percent_bps": int(day_percent_bps),
                        "amount_minor": int(day_amount_minor),
                    }
                )
            boost_applied = applied_days_count > 0
            boost_actual_value = int(applied_days_count)

        elif boost_source_type == BOOST_SOURCE_DEPARTMENT_MONTH_PLAN:
            boost_target_minor = venue_plan_metrics.department_month_revenue_target_minor.get(int(boost_department_id or 0))
            boost_actual_minor = int(revenue_metrics.department_revenue_minor.get(int(boost_department_id or 0), 0) or 0)
            boost_applied = boost_target_minor is not None and boost_actual_minor >= boost_target_minor
            if boost_applied:
                excess_supported = component_type == "PERCENT_DEPARTMENT_REVENUE" and int(component.department_id or 0) == int(boost_department_id or 0)
                if boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY and excess_supported and boost_target_minor is not None:
                    regular_part = _round_percent_amount(min(base_amount_minor, boost_target_minor), regular_percent_bps)
                    boost_part = _round_percent_amount(max(base_amount_minor - boost_target_minor, 0), int(boost_percent_bps or 0))
                    amount_minor = int(regular_part + boost_part)
                else:
                    if boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY and not excess_supported:
                        boost_recalc_mode_effective = BOOST_RECALC_REPLACE_ALL
                    amount_minor = _round_percent_amount(base_amount_minor, int(boost_percent_bps or 0))
                applied_percent_bps = int(boost_percent_bps or 0)

        elif boost_source_type == BOOST_SOURCE_DEPARTMENT_DAY_PLAN:
            day_targets_by_date = venue_plan_metrics.department_day_revenue_target_by_date_minor.get(int(boost_department_id or 0), {})
            day_actuals_by_date = revenue_metrics.department_revenue_by_date_minor.get(int(boost_department_id or 0), {})
            excess_supported = component_type == "PERCENT_DEPARTMENT_REVENUE" and int(component.department_id or 0) == int(boost_department_id or 0)
            amount_minor = 0
            applied_days_count = 0
            for day, base_day_minor in sorted(base_by_date.items(), key=lambda item: item[0]):
                actual_day_minor = int(day_actuals_by_date.get(day) or 0)
                target_day_minor = day_targets_by_date.get(day)
                day_boost_applied = target_day_minor is not None and actual_day_minor >= int(target_day_minor or 0)
                day_percent_bps = regular_percent_bps
                if day_boost_applied:
                    applied_days_count += 1
                    day_percent_bps = int(boost_percent_bps or 0)
                    if boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY and excess_supported and target_day_minor is not None:
                        regular_part = _round_percent_amount(min(base_day_minor, int(target_day_minor)), regular_percent_bps)
                        boost_part = _round_percent_amount(max(base_day_minor - int(target_day_minor), 0), int(boost_percent_bps or 0))
                        day_amount_minor = int(regular_part + boost_part)
                    else:
                        if boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY and not excess_supported:
                            boost_recalc_mode_effective = BOOST_RECALC_REPLACE_ALL
                        day_amount_minor = _round_percent_amount(base_day_minor, int(boost_percent_bps or 0))
                else:
                    day_amount_minor = _round_percent_amount(base_day_minor, regular_percent_bps)
                amount_minor += int(day_amount_minor)
                day_rows.append(
                    {
                        "date": day.isoformat(),
                        "base_amount_minor": int(base_day_minor),
                        "actual_amount_minor": int(actual_day_minor),
                        "target_amount_minor": int(target_day_minor) if target_day_minor is not None else None,
                        "boost_applied": bool(day_boost_applied),
                        "percent_bps": int(day_percent_bps),
                        "amount_minor": int(day_amount_minor),
                    }
                )
            boost_applied = applied_days_count > 0
            boost_actual_value = int(applied_days_count)

        elif boost_source_type == BOOST_SOURCE_KPI_METRIC:
            boost_kpi_metric_id = int(component.boost_kpi_metric_id or 0) if getattr(component, "boost_kpi_metric_id", None) is not None else 0
            boost_target_value = int(component.boost_threshold_value or 0) if getattr(component, "boost_threshold_value", None) is not None else None
            boost_actual_value = int(kpi_metrics.totals_by_metric_id.get(boost_kpi_metric_id, 0)) if boost_kpi_metric_id else 0
            boost_applied = bool(boost_target_value is not None and boost_actual_value >= boost_target_value)
            if boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY:
                boost_recalc_mode_effective = BOOST_RECALC_REPLACE_ALL
            if boost_applied:
                amount_minor = _round_percent_amount(base_amount_minor, int(boost_percent_bps or 0))
                applied_percent_bps = int(boost_percent_bps or 0)

    minimum_applied = False
    maximum_applied = False
    if minimum_guarantee_minor is not None and amount_minor < minimum_guarantee_minor:
        amount_minor = int(minimum_guarantee_minor)
        minimum_applied = True
    if maximum_cap_minor is not None and amount_minor > maximum_cap_minor:
        amount_minor = int(maximum_cap_minor)
        maximum_applied = True

    return PayrollPercentDecision(
        amount_minor=int(amount_minor),
        base_amount_minor=int(base_amount_minor),
        base_scope=base_scope,
        regular_percent_bps=int(regular_percent_bps),
        applied_percent_bps=int(applied_percent_bps),
        regular_amount_minor=int(regular_amount_minor),
        boost_enabled=bool(boost_enabled),
        boost_applied=bool(boost_applied),
        boost_source_type=boost_source_type,
        boost_source_title=boost_source_title,
        boost_recalc_mode=boost_recalc_mode,
        boost_recalc_mode_effective=boost_recalc_mode_effective,
        boost_recalc_mode_title=BOOST_RECALC_TITLES.get(boost_recalc_mode_effective, BOOST_RECALC_TITLES[BOOST_RECALC_REPLACE_ALL]),
        boost_percent_bps=boost_percent_bps,
        boost_target_minor=boost_target_minor,
        boost_actual_minor=boost_actual_minor,
        boost_target_value=boost_target_value,
        boost_actual_value=boost_actual_value,
        boost_kpi_metric_id=int(component.boost_kpi_metric_id) if getattr(component, "boost_kpi_metric_id", None) is not None else None,
        minimum_guarantee_minor=minimum_guarantee_minor,
        maximum_cap_minor=maximum_cap_minor,
        minimum_applied=minimum_applied,
        maximum_applied=maximum_applied,
        day_rows=day_rows,
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
    out: dict[int, list[PayComponent]] = {}
    for component in rows:
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



def _load_member_metrics(db: Session, *, venue_id: int, month_start: date, month_end_excl: date, member_user_ids: list[int]) -> dict[int, PayrollMemberMetrics]:
    if not member_user_ids:
        return {}

    out: dict[int, PayrollMemberMetrics] = {int(uid): PayrollMemberMetrics() for uid in member_user_ids}
    closed_dates = _load_closed_report_dates(db, venue_id=venue_id, month_start=month_start, month_end_excl=month_end_excl)
    if not closed_dates:
        return out

    rows = db.execute(
        select(
            ShiftAssignment.member_user_id,
            Shift.id.label("shift_id"),
            Shift.date.label("shift_date"),
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
            Shift.date.in_(closed_dates),
            ShiftAssignment.member_user_id.in_(member_user_ids),
        )
    ).all()

    shift_sets: dict[int, set[int]] = {int(uid): set() for uid in member_user_ids}

    for row in rows:
        member_user_id = int(row.member_user_id)
        metrics = out.setdefault(member_user_id, PayrollMemberMetrics())
        metrics.minutes_total += interval_duration_minutes(row.start_time, row.end_time)
        metrics.worked_dates.add(row.shift_date)
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
    return PayrollKpiMetrics(totals_by_metric_id=totals_by_metric_id)


def _sum_department_revenue_for_worked_dates(
    department_revenue_by_date_minor: dict[date, int] | None,
    worked_dates: set[date] | None,
) -> int:
    if not department_revenue_by_date_minor or not worked_dates:
        return 0
    return int(sum(int(department_revenue_by_date_minor.get(day) or 0) for day in worked_dates))


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
    kpi_metrics = _load_kpi_metrics(
        db,
        venue_id=int(venue_id),
        month_start=month_start,
        month_end_excl=month_end_excl,
    )
    venue_plan_metrics = _load_venue_plan_metrics(
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
            worked_dates_sorted = sorted(metrics.worked_dates)
            department_base_minor = 0
            if component.department_id is not None:
                base_scope = _component_base_scope(component)
                if base_scope == BASE_SCOPE_FULL_PERIOD:
                    department_base_minor = int(revenue_metrics.department_revenue_minor.get(int(component.department_id), 0))
                else:
                    department_base_minor = _sum_department_revenue_for_worked_dates(
                        revenue_metrics.department_revenue_by_date_minor.get(int(component.department_id), {}),
                        metrics.worked_dates,
                    )
            kpi_metric_value = 0
            if component.kpi_metric_id is not None:
                kpi_metric_value = int(kpi_metrics.totals_by_metric_id.get(int(component.kpi_metric_id), 0))

            percent_decision: PayrollPercentDecision | None = None
            if component_type in {"PERCENT_TOTAL_REVENUE", "PERCENT_DEPARTMENT_REVENUE"}:
                percent_decision = _build_percent_component_decision(
                    component,
                    metrics=metrics,
                    revenue_metrics=revenue_metrics,
                    kpi_metrics=kpi_metrics,
                    venue_plan_metrics=venue_plan_metrics,
                )
                amount_minor = int(percent_decision.amount_minor)
            else:
                amount_minor = calculate_component_amount_minor(
                    component,
                    minutes_total=int(metrics.minutes_total),
                    shifts_count=int(metrics.shifts_count),
                    total_revenue_minor=int(revenue_metrics.total_revenue_minor),
                    department_revenue_minor=int(department_base_minor),
                    kpi_metric_value=int(kpi_metric_value),
                )
            breakdown_item = {
                "component_id": int(component.id),
                "component_type": component.component_type,
                "title": component.title,
                "amount_minor": int(amount_minor),
                "minutes_total": int(metrics.minutes_total),
                "hours_total": round(int(metrics.minutes_total) / 60.0, 2),
                "shifts_count": int(metrics.shifts_count),
                "source_amount_minor": int(component.amount_minor or 0) if component.amount_minor is not None else None,
                "source_rate_minor": int(component.rate_minor or 0) if component.rate_minor is not None else None,
                "source_percent_bps": int(component.percent_bps or 0) if component.percent_bps is not None else None,
            }
            if component_type == "PERCENT_TOTAL_REVENUE" and percent_decision is not None:
                breakdown_item["percent_bps"] = int(percent_decision.applied_percent_bps)
                breakdown_item["regular_percent_bps"] = int(percent_decision.regular_percent_bps)
                breakdown_item["boost_percent_bps"] = percent_decision.boost_percent_bps
                breakdown_item["base_amount_minor"] = int(percent_decision.base_amount_minor)
                breakdown_item["base_scope"] = percent_decision.base_scope
                breakdown_item["base_scope_title"] = BASE_SCOPE_TITLES.get(percent_decision.base_scope, percent_decision.base_scope)
                breakdown_item["boost_enabled"] = bool(percent_decision.boost_enabled)
                breakdown_item["boost_applied"] = bool(percent_decision.boost_applied)
                breakdown_item["boost_source_type"] = percent_decision.boost_source_type
                breakdown_item["boost_source_title"] = percent_decision.boost_source_title
                breakdown_item["boost_recalc_mode"] = percent_decision.boost_recalc_mode
                breakdown_item["boost_recalc_mode_effective"] = percent_decision.boost_recalc_mode_effective
                breakdown_item["boost_recalc_mode_title"] = percent_decision.boost_recalc_mode_title
                breakdown_item["boost_target_minor"] = percent_decision.boost_target_minor
                breakdown_item["boost_actual_minor"] = percent_decision.boost_actual_minor
                breakdown_item["boost_target_value"] = percent_decision.boost_target_value
                breakdown_item["boost_actual_value"] = percent_decision.boost_actual_value
                breakdown_item["boost_department_id"] = int(component.boost_department_id) if getattr(component, "boost_department_id", None) is not None else None
                breakdown_item["boost_department_title"] = component.boost_department.title if getattr(component, "boost_department", None) is not None else None
                breakdown_item["boost_kpi_metric_id"] = percent_decision.boost_kpi_metric_id
                if getattr(component, "boost_kpi_metric", None) is not None:
                    breakdown_item["boost_kpi_metric_title"] = component.boost_kpi_metric.title
                breakdown_item["regular_amount_minor"] = int(percent_decision.regular_amount_minor)
                breakdown_item["minimum_guarantee_minor"] = percent_decision.minimum_guarantee_minor
                breakdown_item["maximum_cap_minor"] = percent_decision.maximum_cap_minor
                breakdown_item["minimum_applied"] = bool(percent_decision.minimum_applied)
                breakdown_item["maximum_applied"] = bool(percent_decision.maximum_applied)
                breakdown_item["day_rows"] = percent_decision.day_rows
                breakdown_item["calculation_snapshot"] = _build_percent_component_snapshot(component, percent_decision)
            elif component_type == "PERCENT_DEPARTMENT_REVENUE" and percent_decision is not None:
                breakdown_item["percent_bps"] = int(percent_decision.applied_percent_bps)
                breakdown_item["regular_percent_bps"] = int(percent_decision.regular_percent_bps)
                breakdown_item["boost_percent_bps"] = percent_decision.boost_percent_bps
                breakdown_item["department_id"] = int(component.department_id) if component.department_id is not None else None
                breakdown_item["department_title"] = component.department.title if getattr(component, "department", None) is not None else None
                breakdown_item["base_amount_minor"] = int(percent_decision.base_amount_minor)
                breakdown_item["base_scope"] = percent_decision.base_scope
                breakdown_item["base_scope_title"] = BASE_SCOPE_TITLES.get(percent_decision.base_scope, percent_decision.base_scope)
                breakdown_item["worked_dates_count"] = len(worked_dates_sorted)
                breakdown_item["worked_dates"] = [day.isoformat() for day in worked_dates_sorted]
                breakdown_item["boost_enabled"] = bool(percent_decision.boost_enabled)
                breakdown_item["boost_applied"] = bool(percent_decision.boost_applied)
                breakdown_item["boost_source_type"] = percent_decision.boost_source_type
                breakdown_item["boost_source_title"] = percent_decision.boost_source_title
                breakdown_item["boost_recalc_mode"] = percent_decision.boost_recalc_mode
                breakdown_item["boost_recalc_mode_effective"] = percent_decision.boost_recalc_mode_effective
                breakdown_item["boost_recalc_mode_title"] = percent_decision.boost_recalc_mode_title
                breakdown_item["boost_target_minor"] = percent_decision.boost_target_minor
                breakdown_item["boost_actual_minor"] = percent_decision.boost_actual_minor
                breakdown_item["boost_target_value"] = percent_decision.boost_target_value
                breakdown_item["boost_actual_value"] = percent_decision.boost_actual_value
                breakdown_item["boost_department_id"] = int(component.boost_department_id) if getattr(component, "boost_department_id", None) is not None else None
                breakdown_item["boost_department_title"] = component.boost_department.title if getattr(component, "boost_department", None) is not None else None
                breakdown_item["boost_kpi_metric_id"] = percent_decision.boost_kpi_metric_id
                if getattr(component, "boost_kpi_metric", None) is not None:
                    breakdown_item["boost_kpi_metric_title"] = component.boost_kpi_metric.title
                breakdown_item["regular_amount_minor"] = int(percent_decision.regular_amount_minor)
                breakdown_item["minimum_guarantee_minor"] = percent_decision.minimum_guarantee_minor
                breakdown_item["maximum_cap_minor"] = percent_decision.maximum_cap_minor
                breakdown_item["minimum_applied"] = bool(percent_decision.minimum_applied)
                breakdown_item["maximum_applied"] = bool(percent_decision.maximum_applied)
                breakdown_item["day_rows"] = percent_decision.day_rows
                breakdown_item["calculation_snapshot"] = _build_percent_component_snapshot(component, percent_decision)
            elif component_type == "KPI_BONUS":
                kpi_decision = calculate_kpi_bonus(component, kpi_metric_value=int(kpi_metric_value))
                breakdown_item["kpi_metric_id"] = int(component.kpi_metric_id) if component.kpi_metric_id is not None else None
                breakdown_item["kpi_metric_title"] = component.kpi_metric.title if getattr(component, "kpi_metric", None) is not None else None
                breakdown_item["metric_value"] = int(kpi_decision.metric_value)
                breakdown_item["threshold_value"] = kpi_decision.threshold_value
                breakdown_item["matched_step"] = kpi_decision.matched_step
                breakdown_item["steps"] = kpi_decision.steps
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
                "worked_dates_count": len(sorted(metrics.worked_dates)),
                "worked_dates": [day.isoformat() for day in sorted(metrics.worked_dates)],
            },
            "revenue_metrics": {
                "total_revenue_minor": int(revenue_metrics.total_revenue_minor),
            },
            "kpi_metrics": {
                str(metric_id): int(value)
                for metric_id, value in sorted(kpi_metrics.totals_by_metric_id.items())
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
