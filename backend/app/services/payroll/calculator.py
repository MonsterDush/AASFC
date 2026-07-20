from __future__ import annotations

from datetime import datetime
import json

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import PayComponent, PayProfile, PayProfileAssignment, PayrollLine, PayrollRun, User
from app.services.finance.ledger import create_finance_entry, delete_finance_entries_for_source

from .component_calculations import (
    _allocate_minor_by_keys,
    _apply_daily_minimum_to_rows,
    _component_boost_department_ids,
    _component_department_ids,
    _component_shift_allocations,
    _department_title_for,
    _department_titles_for_ids,
    _minimum_guarantee_scope,
    _minimum_payout_scope,
    _minimum_payout_scope_title,
    _minimum_payout_shift_top_up,
    _minimum_payout_target_minor,
    _month_dates,
    _normalize_int_ids,
    _ordered_worked_shifts,
    _parse_steps_json,
    _percent_decision_amounts_by_date,
    _round_percent_amount,
    _rub_to_minor,
    _shift_ids,
    _split_date_amounts_to_shifts,
    _sum_department_day_target_minor,
    _sum_department_month_target_minor,
    _sum_department_revenue_by_date_minor,
    _sum_department_revenue_minor,
    _sum_optional_targets,
    calculate_component_amount_minor,
    calculate_kpi_bonus,
    interval_duration_minutes,
    next_month_start,
    parse_month_start,
)
from .metric_loaders import (
    _assignment_overlaps_month,
    _load_closed_report_dates,
    _load_closed_report_slots_by_date,
    _load_kpi_metrics,
    _load_member_metrics,
    _load_profile_components,
    _load_revenue_metrics,
    _load_venue_plan_metrics,
    _pick_latest_assignments,
    _sum_department_revenue_for_worked_dates,
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
    MINIMUM_GUARANTEE_MONTH,
    MINIMUM_GUARANTEE_SHIFT,
    PAY_COMPONENT_TYPES,
    PayrollCalculationResult,
    PayrollKpiBonusDecision,
    PayrollKpiMetrics,
    PayrollMemberMetrics,
    PayrollPercentDecision,
    PayrollRevenueMetrics,
    PayrollVenuePlanMetrics,
    PayrollWorkedShift,
)
from .percent_calculations import (
    _build_percent_component_decision,
    _build_percent_component_snapshot,
    _component_base_scope,
    _component_boost_recalc_mode,
    _component_boost_source_type,
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
        minimum_payout_components: list[PayComponent] = []
        earnings_by_shift_minor: dict[int, int] = {shift_id: 0 for shift_id in _shift_ids(metrics)}

        for component in components:
            component_type = str(component.component_type or "").strip().upper()
            if component_type == "MINIMUM_PAYOUT":
                minimum_payout_components.append(component)
                continue
            worked_dates_sorted = sorted(metrics.worked_dates)
            department_base_minor = 0
            component_department_ids = _component_department_ids(component)
            if component_department_ids:
                base_scope = _component_base_scope(component)
                department_revenue_by_date = _sum_department_revenue_by_date_minor(revenue_metrics, component_department_ids)
                if base_scope == BASE_SCOPE_FULL_PERIOD:
                    department_base_minor = _sum_department_revenue_minor(revenue_metrics, component_department_ids)
                else:
                    department_base_minor = _sum_department_revenue_for_worked_dates(
                        department_revenue_by_date,
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
                breakdown_item["department_ids"] = percent_decision.department_ids
                breakdown_item["department_titles"] = percent_decision.department_titles
                breakdown_item["boost_department_ids"] = percent_decision.boost_department_ids
                breakdown_item["boost_department_titles"] = percent_decision.boost_department_titles
                breakdown_item["boost_kpi_metric_id"] = percent_decision.boost_kpi_metric_id
                if getattr(component, "boost_kpi_metric", None) is not None:
                    breakdown_item["boost_kpi_metric_title"] = component.boost_kpi_metric.title
                breakdown_item["regular_amount_minor"] = int(percent_decision.regular_amount_minor)
                breakdown_item["minimum_guarantee_minor"] = percent_decision.minimum_guarantee_minor
                breakdown_item["minimum_guarantee_scope"] = percent_decision.minimum_guarantee_scope
                breakdown_item["minimum_guarantee_scope_title"] = "за день" if percent_decision.minimum_guarantee_scope == MINIMUM_GUARANTEE_DAY else "за месяц"
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
                breakdown_item["department_ids"] = percent_decision.department_ids
                breakdown_item["department_titles"] = percent_decision.department_titles
                breakdown_item["boost_department_ids"] = percent_decision.boost_department_ids
                breakdown_item["boost_department_titles"] = percent_decision.boost_department_titles
                breakdown_item["boost_kpi_metric_id"] = percent_decision.boost_kpi_metric_id
                if getattr(component, "boost_kpi_metric", None) is not None:
                    breakdown_item["boost_kpi_metric_title"] = component.boost_kpi_metric.title
                breakdown_item["regular_amount_minor"] = int(percent_decision.regular_amount_minor)
                breakdown_item["minimum_guarantee_minor"] = percent_decision.minimum_guarantee_minor
                breakdown_item["minimum_guarantee_scope"] = percent_decision.minimum_guarantee_scope
                breakdown_item["minimum_guarantee_scope_title"] = "за день" if percent_decision.minimum_guarantee_scope == MINIMUM_GUARANTEE_DAY else "за месяц"
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
            shift_allocations = _component_shift_allocations(
                component=component,
                amount_minor=int(amount_minor),
                metrics=metrics,
                month_start=month_start,
                month_end_excl=month_end_excl,
                revenue_metrics=revenue_metrics,
                percent_decision=percent_decision,
            )
            for shift_id, shift_amount_minor in shift_allocations.items():
                earnings_by_shift_minor[int(shift_id)] = int(earnings_by_shift_minor.get(int(shift_id), 0) or 0) + int(shift_amount_minor or 0)
            line_total += int(amount_minor)

        for component in minimum_payout_components:
            source_amount_minor = int(component.amount_minor or 0)
            minimum_scope = _minimum_payout_scope(component)
            minimum_target_minor = _minimum_payout_target_minor(component, metrics)
            amount_before_minimum_minor = int(line_total)
            shift_rows: list[dict] = []
            if minimum_scope == MINIMUM_GUARANTEE_SHIFT:
                top_up_minor, shift_rows = _minimum_payout_shift_top_up(
                    component=component,
                    metrics=metrics,
                    earnings_by_shift_minor=earnings_by_shift_minor,
                )
                for row in shift_rows:
                    shift_id = int(row.get("shift_id") or 0)
                    if shift_id:
                        earnings_by_shift_minor[shift_id] = int(earnings_by_shift_minor.get(shift_id, 0) or 0) + int(row.get("amount_minor") or 0)
            else:
                top_up_minor = max(0, minimum_target_minor - amount_before_minimum_minor)
            breakdown_items.append(
                {
                    "component_id": int(component.id),
                    "component_type": "MINIMUM_PAYOUT",
                    "title": component.title,
                    "amount_minor": int(top_up_minor),
                    "source_amount_minor": int(source_amount_minor),
                    "minimum_target_minor": int(minimum_target_minor),
                    "minimum_payout_scope": minimum_scope,
                    "minimum_payout_scope_title": _minimum_payout_scope_title(minimum_scope),
                    "minimum_guarantee_scope": minimum_scope,
                    "minimum_guarantee_scope_title": _minimum_payout_scope_title(minimum_scope),
                    "amount_before_minimum_minor": int(amount_before_minimum_minor),
                    "aggregate_shift_amount_before_minimum_minor": int(sum(int(row.get("amount_before_minimum_minor") or 0) for row in shift_rows)) if shift_rows else None,
                    "minimum_applied": bool(top_up_minor > 0),
                    "minimum_applied_shifts_count": int(sum(1 for row in shift_rows if row.get("minimum_applied"))) if shift_rows else None,
                    "shift_rows": shift_rows,
                    "minutes_total": int(metrics.minutes_total),
                    "hours_total": round(int(metrics.minutes_total) / 60.0, 2),
                    "shifts_count": int(metrics.shifts_count),
                }
            )
            line_total += int(top_up_minor)

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
