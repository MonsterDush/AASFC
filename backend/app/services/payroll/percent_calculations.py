from __future__ import annotations

from app.models import PayComponent

from .component_calculations import (
    _apply_daily_minimum_to_rows,
    _component_boost_department_ids,
    _component_department_ids,
    _department_titles_for_ids,
    _minimum_guarantee_scope,
    _round_percent_amount,
    _sum_department_day_target_minor,
    _sum_department_month_target_minor,
    _sum_department_revenue_by_date_minor,
    _sum_department_revenue_minor,
)
from .payroll_types import (
    BASE_SCOPE_FULL_PERIOD,
    BASE_SCOPE_TITLES,
    BASE_SCOPE_WORKED_DATES,
    BOOST_RECALC_EXCESS_ONLY,
    BOOST_RECALC_REPLACE_ALL,
    BOOST_RECALC_TITLES,
    BOOST_SOURCE_DEPARTMENT_DAY_PLAN,
    BOOST_SOURCE_DEPARTMENT_MONTH_PLAN,
    BOOST_SOURCE_KPI_METRIC,
    BOOST_SOURCE_NONE,
    BOOST_SOURCE_TITLES,
    BOOST_SOURCE_VENUE_DAY_PLAN,
    BOOST_SOURCE_VENUE_MONTH_PLAN,
    MINIMUM_GUARANTEE_DAY,
    PayrollKpiMetrics,
    PayrollMemberMetrics,
    PayrollPercentDecision,
    PayrollRevenueMetrics,
    PayrollVenuePlanMetrics,
)


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
        "department_ids": [int(item) for item in (decision.department_ids or [])],
        "department_titles": [str(item) for item in (decision.department_titles or [])],
        "boost_department_id": int(getattr(component, "boost_department_id", 0) or 0)
        if getattr(component, "boost_department_id", None) is not None
        else None,
        "boost_department_ids": [int(item) for item in (decision.boost_department_ids or [])],
        "boost_department_title": getattr(getattr(component, "boost_department", None), "title", None),
        "boost_department_titles": [str(item) for item in (decision.boost_department_titles or [])],
        "boost_kpi_metric_id": int(decision.boost_kpi_metric_id) if decision.boost_kpi_metric_id is not None else None,
        "boost_kpi_metric_title": getattr(getattr(component, "boost_kpi_metric", None), "title", None),
        "minimum_guarantee_minor": int(decision.minimum_guarantee_minor)
        if decision.minimum_guarantee_minor is not None
        else None,
        "minimum_guarantee_scope": decision.minimum_guarantee_scope,
        "minimum_guarantee_scope_title": "за день"
        if decision.minimum_guarantee_scope == MINIMUM_GUARANTEE_DAY
        else "за месяц",
        "maximum_cap_minor": int(decision.maximum_cap_minor) if decision.maximum_cap_minor is not None else None,
        "minimum_applied": bool(decision.minimum_applied),
        "maximum_applied": bool(decision.maximum_applied),
        "department_id": int(getattr(component, "department_id", 0) or 0)
        if getattr(component, "department_id", None) is not None
        else None,
        "department_title": getattr(getattr(component, "department", None), "title", None),
        "day_rows": [dict(row) for row in (decision.day_rows or [])],
    }
    return snapshot


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
    boost_percent_bps = (
        int(component.boost_percent_bps or 0) if getattr(component, "boost_percent_bps", None) is not None else None
    )
    boost_source_type = _component_boost_source_type(component)
    boost_source_title = BOOST_SOURCE_TITLES.get(boost_source_type, boost_source_type or BOOST_SOURCE_NONE)
    boost_recalc_mode = _component_boost_recalc_mode(component)
    department_ids = _component_department_ids(component)
    boost_department_ids = _component_boost_department_ids(component, fallback_department_ids=department_ids)
    boost_recalc_mode_effective = boost_recalc_mode
    minimum_guarantee_minor = (
        int(component.minimum_guarantee_minor or 0)
        if getattr(component, "minimum_guarantee_minor", None) is not None
        else None
    )
    minimum_guarantee_scope = _minimum_guarantee_scope(component)
    maximum_cap_minor = (
        int(component.maximum_cap_minor or 0) if getattr(component, "maximum_cap_minor", None) is not None else None
    )

    if component_type == "PERCENT_TOTAL_REVENUE":
        source_by_date = revenue_metrics.total_revenue_by_date_minor
    else:
        source_by_date = _sum_department_revenue_by_date_minor(revenue_metrics, department_ids)

    if base_scope == BASE_SCOPE_WORKED_DATES:
        base_by_date = {
            day: int(source_by_date.get(day) or 0) for day in sorted(metrics.worked_dates) if day in source_by_date
        }
    else:
        base_by_date = {
            day: int(amount or 0) for day, amount in sorted(source_by_date.items(), key=lambda item: item[0])
        }

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
                if (
                    boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY
                    and excess_supported
                    and boost_target_minor is not None
                ):
                    regular_part = _round_percent_amount(
                        min(base_amount_minor, boost_target_minor), regular_percent_bps
                    )
                    boost_part = _round_percent_amount(
                        max(base_amount_minor - boost_target_minor, 0), int(boost_percent_bps or 0)
                    )
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
                    if (
                        boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY
                        and excess_supported
                        and target_day_minor is not None
                    ):
                        regular_part = _round_percent_amount(
                            min(base_day_minor, int(target_day_minor)), regular_percent_bps
                        )
                        boost_part = _round_percent_amount(
                            max(base_day_minor - int(target_day_minor), 0), int(boost_percent_bps or 0)
                        )
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
            boost_target_minor = _sum_department_month_target_minor(venue_plan_metrics, boost_department_ids)
            boost_actual_minor = _sum_department_revenue_minor(revenue_metrics, boost_department_ids)
            boost_applied = boost_target_minor is not None and boost_actual_minor >= boost_target_minor
            if boost_applied:
                excess_supported = component_type == "PERCENT_DEPARTMENT_REVENUE" and set(department_ids) == set(
                    boost_department_ids
                )
                if (
                    boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY
                    and excess_supported
                    and boost_target_minor is not None
                ):
                    regular_part = _round_percent_amount(
                        min(base_amount_minor, boost_target_minor), regular_percent_bps
                    )
                    boost_part = _round_percent_amount(
                        max(base_amount_minor - boost_target_minor, 0), int(boost_percent_bps or 0)
                    )
                    amount_minor = int(regular_part + boost_part)
                else:
                    if boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY and not excess_supported:
                        boost_recalc_mode_effective = BOOST_RECALC_REPLACE_ALL
                    amount_minor = _round_percent_amount(base_amount_minor, int(boost_percent_bps or 0))
                applied_percent_bps = int(boost_percent_bps or 0)

        elif boost_source_type == BOOST_SOURCE_DEPARTMENT_DAY_PLAN:
            day_actuals_by_date = _sum_department_revenue_by_date_minor(revenue_metrics, boost_department_ids)
            excess_supported = component_type == "PERCENT_DEPARTMENT_REVENUE" and set(department_ids) == set(
                boost_department_ids
            )
            amount_minor = 0
            applied_days_count = 0
            for day, base_day_minor in sorted(base_by_date.items(), key=lambda item: item[0]):
                actual_day_minor = int(day_actuals_by_date.get(day) or 0)
                target_day_minor = _sum_department_day_target_minor(venue_plan_metrics, boost_department_ids, day)
                day_boost_applied = target_day_minor is not None and actual_day_minor >= int(target_day_minor or 0)
                day_percent_bps = regular_percent_bps
                if day_boost_applied:
                    applied_days_count += 1
                    day_percent_bps = int(boost_percent_bps or 0)
                    if (
                        boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY
                        and excess_supported
                        and target_day_minor is not None
                    ):
                        regular_part = _round_percent_amount(
                            min(base_day_minor, int(target_day_minor)), regular_percent_bps
                        )
                        boost_part = _round_percent_amount(
                            max(base_day_minor - int(target_day_minor), 0), int(boost_percent_bps or 0)
                        )
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
            boost_kpi_metric_id = (
                int(component.boost_kpi_metric_id or 0)
                if getattr(component, "boost_kpi_metric_id", None) is not None
                else 0
            )
            boost_target_value = (
                int(component.boost_threshold_value or 0)
                if getattr(component, "boost_threshold_value", None) is not None
                else None
            )
            boost_actual_value = (
                int(kpi_metrics.totals_by_metric_id.get(boost_kpi_metric_id, 0)) if boost_kpi_metric_id else 0
            )
            boost_applied = bool(boost_target_value is not None and boost_actual_value >= boost_target_value)
            if boost_recalc_mode == BOOST_RECALC_EXCESS_ONLY:
                boost_recalc_mode_effective = BOOST_RECALC_REPLACE_ALL
            if boost_applied:
                amount_minor = _round_percent_amount(base_amount_minor, int(boost_percent_bps or 0))
                applied_percent_bps = int(boost_percent_bps or 0)

    minimum_applied = False
    maximum_applied = False
    if minimum_guarantee_minor is not None and minimum_guarantee_scope == MINIMUM_GUARANTEE_DAY:
        if not day_rows:
            day_rows = [
                {
                    "date": day.isoformat(),
                    "base_amount_minor": int(base_day_minor),
                    "actual_amount_minor": int(base_day_minor),
                    "target_amount_minor": None,
                    "boost_applied": bool(boost_applied),
                    "percent_bps": int(applied_percent_bps),
                    "amount_minor": _round_percent_amount(int(base_day_minor), int(applied_percent_bps)),
                }
                for day, base_day_minor in sorted(base_by_date.items(), key=lambda item: item[0])
            ]
        day_rows, minimum_applied = _apply_daily_minimum_to_rows(day_rows, minimum_guarantee_minor)
        amount_minor = int(sum(int(row.get("amount_minor") or 0) for row in day_rows))
    elif minimum_guarantee_minor is not None and amount_minor < minimum_guarantee_minor:
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
        boost_recalc_mode_title=BOOST_RECALC_TITLES.get(
            boost_recalc_mode_effective, BOOST_RECALC_TITLES[BOOST_RECALC_REPLACE_ALL]
        ),
        boost_percent_bps=boost_percent_bps,
        boost_target_minor=boost_target_minor,
        boost_actual_minor=boost_actual_minor,
        boost_target_value=boost_target_value,
        boost_actual_value=boost_actual_value,
        boost_kpi_metric_id=int(component.boost_kpi_metric_id)
        if getattr(component, "boost_kpi_metric_id", None) is not None
        else None,
        department_ids=[int(item) for item in department_ids],
        department_titles=_department_titles_for_ids(component, department_ids),
        boost_department_ids=[int(item) for item in boost_department_ids],
        boost_department_titles=_department_titles_for_ids(component, boost_department_ids),
        minimum_guarantee_minor=minimum_guarantee_minor,
        minimum_guarantee_scope=minimum_guarantee_scope,
        maximum_cap_minor=maximum_cap_minor,
        minimum_applied=minimum_applied,
        maximum_applied=maximum_applied,
        day_rows=day_rows,
    )
