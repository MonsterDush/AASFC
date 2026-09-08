"""Exact threshold comparison and marginal brackets, independent per report date."""

from decimal import Decimal, ROUND_HALF_UP

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
from .payroll_types import BOOST_RECALC_TITLES, BOOST_SOURCE_TITLES, PayrollPercentDecision
from .percent_tier_rules import excess_compatible, tier_dict


def calculate_brackets(base, actual, target, tiers, base_rate, *, kpi=False, excess=False):
    achievement = Decimal(actual) if kpi else Decimal(actual) * 100 / Decimal(target) if target and target > 0 else None
    matched = None
    for tier in tiers:
        # Compare unrounded quantities: 109.999% must not reach a 110% tier.
        if achievement is not None and achievement >= Decimal(str(tier["threshold_value"])):
            matched = tier
    rate = int(matched["percent_bps"]) if matched else base_rate
    amount, segments = _round_percent_amount(base, rate), []
    if excess and target and target > 0:
        cursor, current_rate, total = Decimal(0), base_rate, Decimal(0)
        for tier in tiers + [None]:
            boundary = Decimal(base) if tier is None else Decimal(target) * Decimal(str(tier["threshold_value"])) / 100
            end = min(Decimal(base), boundary)
            if end > cursor:
                portion = (end - cursor) * current_rate / 10000
                total += portion
                segments.append(
                    {
                        "base_amount_minor": float(end - cursor),
                        "percent_bps": current_rate,
                        "amount_minor": int(portion.quantize(Decimal(1), rounding=ROUND_HALF_UP)),
                    }
                )
                cursor = end
            if tier is None or boundary >= base:
                break
            current_rate = int(tier["percent_bps"])
        amount = int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP))
        if segments:
            segments[-1]["amount_minor"] += amount - sum(row["amount_minor"] for row in segments)
    return {
        "amount_minor": amount,
        "percent_bps": rate,
        "matched_tier": dict(matched) if matched else None,
        "achievement_percent": float(achievement) if achievement is not None and not kpi else None,
        "segments": segments,
        "boost_applied": matched is not None,
    }


def calculate_tier_decision(component, metrics, revenue, kpis, plans):
    from .percent_calculations import _component_base_scope, _component_boost_source_type, _component_boost_recalc_mode

    scope = _component_base_scope(component)
    source = _component_boost_source_type(component)
    mode = _component_boost_recalc_mode(component)
    base_rate = int(component.percent_bps or 0)
    departments = _component_department_ids(component)
    boost_departments = _component_boost_department_ids(component, fallback_department_ids=departments)
    tiers = [tier_dict(tier) for tier in sorted(component.percent_tiers, key=lambda tier: tier.threshold_value)]
    effective_mode = mode
    if mode == "EXCESS_ONLY" and not excess_compatible(
        component.component_type, scope, source, departments, boost_departments
    ):
        effective_mode = "REPLACE_ALL"
    total_type = component.component_type == "PERCENT_TOTAL_REVENUE"
    source_by_date = (
        revenue.total_revenue_by_date_minor
        if total_type
        else _sum_department_revenue_by_date_minor(revenue, departments)
    )
    bases = {
        day: int(value)
        for day, value in sorted(source_by_date.items())
        if scope != "WORKED_DATES" or day in metrics.worked_dates
    }
    base = sum(bases.values())
    daily = source in {"VENUE_DAY_PLAN", "DEPARTMENT_DAY_PLAN"}
    is_kpi = source == "KPI_METRIC"
    target, actual, rows = None, None, []
    kpi_id = getattr(component, "boost_kpi_metric_id", None)
    if source == "VENUE_MONTH_PLAN":
        target, actual = plans.month_revenue_target_minor, revenue.total_revenue_minor
    elif source == "DEPARTMENT_MONTH_PLAN":
        target = _sum_department_month_target_minor(plans, boost_departments)
        actual = _sum_department_revenue_minor(revenue, boost_departments)
    elif is_kpi:
        actual = kpis.totals_by_metric_id.get(kpi_id, 0)
    if target is not None and target <= 0:
        target = None
    result = calculate_brackets(
        base, actual or 0, target, tiers, base_rate, kpi=is_kpi, excess=effective_mode == "EXCESS_ONLY"
    )
    if daily:
        actuals = (
            revenue.total_revenue_by_date_minor
            if source == "VENUE_DAY_PLAN"
            else _sum_department_revenue_by_date_minor(revenue, boost_departments)
        )
        for day, day_base in bases.items():
            day_target = (
                plans.day_revenue_target_by_date_minor.get(day)
                if source == "VENUE_DAY_PLAN"
                else _sum_department_day_target_minor(plans, boost_departments, day)
            )
            day_target = day_target if day_target and day_target > 0 else None
            day_actual = int(actuals.get(day, 0))
            detail = calculate_brackets(
                day_base, day_actual, day_target, tiers, base_rate, excess=effective_mode == "EXCESS_ONLY"
            )
            rows.append(
                {
                    "date": day.isoformat(),
                    "base_amount_minor": day_base,
                    "target_amount_minor": day_target,
                    "actual_amount_minor": day_actual,
                    **detail,
                }
            )
        result["amount_minor"] = sum(row["amount_minor"] for row in rows)
        result["boost_applied"] = any(row["boost_applied"] for row in rows)
        result["percent_bps"] = max((row["percent_bps"] for row in rows), default=base_rate)
        result["matched_tier"] = None
    minimum = getattr(component, "minimum_guarantee_minor", None)
    minimum_scope = _minimum_guarantee_scope(component)
    maximum = getattr(component, "maximum_cap_minor", None)
    amount, minimum_applied = result["amount_minor"], False
    if minimum is not None and minimum_scope == "DAY":
        if not rows:
            # Allocate the already calculated monthly amount; do not recalculate marginal rates per day.
            allocated = 0
            for index, (day, day_base) in enumerate(bases.items()):
                part = (
                    amount - allocated
                    if index == len(bases) - 1
                    else int(Decimal(amount) * day_base / base)
                    if base
                    else 0
                )
                allocated += part
                rows.append(
                    {
                        "date": day.isoformat(),
                        "base_amount_minor": day_base,
                        "amount_minor": part,
                        "percent_bps": result["percent_bps"],
                        "boost_applied": result["boost_applied"],
                        "monthly_allocation": True,
                    }
                )
        rows, minimum_applied = _apply_daily_minimum_to_rows(rows, minimum)
        amount = sum(row["amount_minor"] for row in rows)
    elif minimum is not None and amount < minimum:
        amount, minimum_applied = minimum, True
    maximum_applied = maximum is not None and amount > maximum
    if maximum_applied:
        amount = maximum
    decision = PayrollPercentDecision(
        amount_minor=int(amount),
        base_amount_minor=base,
        base_scope=scope,
        regular_percent_bps=base_rate,
        applied_percent_bps=result["percent_bps"],
        regular_amount_minor=_round_percent_amount(base, base_rate),
        boost_enabled=True,
        boost_applied=result["boost_applied"],
        boost_source_type=source,
        boost_source_title=BOOST_SOURCE_TITLES.get(source, source),
        boost_recalc_mode=mode,
        boost_recalc_mode_effective=effective_mode,
        boost_recalc_mode_title=BOOST_RECALC_TITLES[effective_mode],
        boost_percent_bps=tiers[-1]["percent_bps"],
        boost_target_minor=target,
        boost_actual_minor=actual if not is_kpi else None,
        boost_actual_value=actual if is_kpi else None,
        boost_target_value=int(tiers[0]["threshold_value"]) if is_kpi else None,
        boost_kpi_metric_id=kpi_id,
        department_ids=departments,
        department_titles=_department_titles_for_ids(component, departments),
        boost_department_ids=boost_departments,
        boost_department_titles=_department_titles_for_ids(component, boost_departments),
        minimum_guarantee_minor=minimum,
        minimum_guarantee_scope=minimum_scope,
        maximum_cap_minor=maximum,
        minimum_applied=minimum_applied,
        maximum_applied=maximum_applied,
        day_rows=rows,
    )
    decision.tier_details = {
        "calculation_version": 2,
        "percent_tiers": tiers,
        "matched_tier": result["matched_tier"],
        "achievement_percent": result["achievement_percent"],
        "applied_percent_varies_by_day": daily,
        "segments": result["segments"],
        "threshold_unit": "VALUE" if is_kpi else "PLAN_PERCENT",
        "recalc_fallback_reason": "INCOMPATIBLE_BASE" if mode != effective_mode else None,
    }
    return decision
