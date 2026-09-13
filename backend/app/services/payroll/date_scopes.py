from __future__ import annotations

from datetime import date, timedelta

from .payroll_types import PayrollKpiMetrics, PayrollRevenueMetrics


def context_month_dates(context: object, *, month_start: date, month_end_excl: date) -> tuple[list[date], set[date]]:
    month_dates: list[date] = []
    cursor = month_start
    while cursor < month_end_excl:
        month_dates.append(cursor)
        cursor += timedelta(days=1)
    raw_active_dates = getattr(context, "profile_active_dates", None)
    active_dates = (
        {day for day in raw_active_dates if month_start <= day < month_end_excl}
        if raw_active_dates is not None
        else set(month_dates)
    )
    metrics = getattr(context, "metrics", None)
    if metrics is not None:
        setattr(metrics, "_salary_active_dates", active_dates)
    return month_dates, active_dates


def prorate_fixed_month_amount(
    full_amount_minor: int,
    *,
    month_dates: list[date],
    active_dates: set[date],
) -> int:
    if not month_dates or not active_dates:
        return 0
    quotient, remainder = divmod(int(full_amount_minor), len(month_dates))
    amounts = {day: quotient + (1 if index < remainder else 0) for index, day in enumerate(month_dates)}
    return sum(amounts.get(day, 0) for day in active_dates)


def enrich_fixed_salary_breakdown(
    item: dict,
    *,
    component: object,
    month_dates: list[date],
    active_dates: set[date],
) -> None:
    item.update(
        {
            "profile_active_dates": [day.isoformat() for day in sorted(active_dates)],
            "profile_active_dates_count": len(active_dates),
            "month_dates_count": len(month_dates),
            "prorated": len(active_dates) != len(month_dates),
            "salary_accrual_day": (
                int(component.salary_accrual_day)
                if getattr(component, "salary_accrual_day", None) is not None
                else None
            ),
        }
    )


def revenue_metrics_for_dates(
    metrics: PayrollRevenueMetrics,
    allowed_dates: set[date],
) -> PayrollRevenueMetrics:
    total_by_date = {
        day: int(amount or 0) for day, amount in metrics.total_revenue_by_date_minor.items() if day in allowed_dates
    }
    department_by_date = {
        int(department_id): {day: int(amount or 0) for day, amount in amounts.items() if day in allowed_dates}
        for department_id, amounts in metrics.department_revenue_by_date_minor.items()
    }
    return PayrollRevenueMetrics(
        total_revenue_minor=sum(total_by_date.values()),
        total_revenue_by_date_minor=total_by_date,
        department_revenue_minor={
            department_id: sum(amounts.values()) for department_id, amounts in department_by_date.items()
        },
        department_revenue_by_date_minor=department_by_date,
    )


def kpi_metrics_for_dates(metrics: PayrollKpiMetrics, allowed_dates: set[date]) -> PayrollKpiMetrics:
    values = {
        int(metric_id): {
            (day, slot): int(amount or 0) for (day, slot), amount in by_date_slot.items() if day in allowed_dates
        }
        for metric_id, by_date_slot in metrics.values_by_metric_date_slot.items()
    }
    return PayrollKpiMetrics(
        totals_by_metric_id={metric_id: sum(by_date_slot.values()) for metric_id, by_date_slot in values.items()},
        values_by_metric_date_slot=values,
    )
