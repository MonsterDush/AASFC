from __future__ import annotations

import json

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import PayrollLine


def clear_payroll_lines_for_run(db: Session, *, payroll_run_id: int) -> None:
    identity_map = getattr(db, "identity_map", {})
    attached_lines = [
        instance
        for instance in identity_map.values()
        if isinstance(instance, PayrollLine) and int(instance.payroll_run_id) == int(payroll_run_id)
    ]
    db.execute(delete(PayrollLine).where(PayrollLine.payroll_run_id == int(payroll_run_id)))
    db.flush()
    for line in attached_lines:
        if line in db:
            db.expunge(line)


def _component_rounding_rule(component_type: str | None) -> str:
    normalized = str(component_type or "").strip().upper()
    if normalized == "SALARY_FIXED_MONTH":
        return "CALENDAR_DAY_ALLOCATION_REMAINDER_EARLIEST"
    if normalized == "SALARY_HOURLY":
        return "HALF_UP_TO_MINOR_UNIT"
    if normalized in {"PERCENT_TOTAL_REVENUE", "PERCENT_DEPARTMENT_REVENUE"}:
        return "HALF_UP_TO_MINOR_UNIT"
    return "EXACT_MINOR_UNITS"


def add_position_context_to_aggregate(
    aggregates: dict[int, dict],
    *,
    context,
    line_total: int,
    breakdown_items: list[dict],
    shift_allocations: list[dict],
) -> None:
    profile = context.profile
    member_user = context.member_user
    metrics = context.metrics
    position_ids = sorted(int(value) for value in context.position_ids)
    position_titles = sorted((value for value in context.position_titles if value), key=str.casefold)
    profile_active_dates = sorted(getattr(context, "profile_active_dates", set()) or set())
    profile_period_ids = sorted(int(value) for value in getattr(context, "profile_period_ids", set()) or set())
    assignment_ids = sorted(int(value) for value in getattr(context, "assignment_ids", set()) or set())
    profile_sources = sorted(getattr(context, "profile_sources", set()) or set())
    discarded_profile_candidates = [
        {"profile_source": source, "pay_profile_id": profile_id}
        for source, profile_id in sorted(getattr(context, "discarded_profile_candidates", set()) or set())
    ]
    profile_source = profile_sources[0] if len(profile_sources) == 1 else "MIXED"
    used_shift_ids = sorted(int(shift.shift_id) for shift in metrics.worked_shifts)
    used_shift_dates = sorted({shift.shift_date.isoformat() for shift in metrics.worked_shifts})
    for item in breakdown_items:
        item["pay_profile_id"] = int(profile.id)
        item["pay_profile_title"] = profile.title
        item["position_ids"] = position_ids
        item["position_titles"] = position_titles
        item["profile_source"] = profile_source
        item["profile_period_ids"] = profile_period_ids
        item["assignment_ids"] = assignment_ids
        item["position_id"] = position_ids[0] if len(position_ids) == 1 else None
        item["position_title"] = position_titles[0] if len(position_titles) == 1 else None
        item["profile_period_id"] = profile_period_ids[0] if len(profile_period_ids) == 1 else None
        item["assignment_id"] = assignment_ids[0] if len(assignment_ids) == 1 else None
        item["profile_active_from"] = profile_active_dates[0].isoformat() if profile_active_dates else None
        item["profile_active_to"] = profile_active_dates[-1].isoformat() if profile_active_dates else None
        item["profile_active_dates_count"] = len(profile_active_dates)
        item["used_shift_ids"] = used_shift_ids
        item["used_shift_dates"] = used_shift_dates
        item["rounding_rule"] = _component_rounding_rule(item.get("component_type"))
        item["discarded_profile_candidates"] = discarded_profile_candidates
        item["warnings"] = list(item.get("warnings") or [])

    member_id = int(member_user.id)
    aggregate = aggregates.setdefault(
        member_id,
        {
            "member": member_user,
            "amount_minor": 0,
            "profile_ids": set(),
            "profile_titles": {},
            "minutes_total": 0,
            "shifts_count": 0,
            "worked_dates": set(),
            "components": [],
            "shift_allocations": {},
            "position_profiles": [],
        },
    )
    aggregate["amount_minor"] += int(line_total)
    aggregate["profile_ids"].add(int(profile.id))
    aggregate["profile_titles"][int(profile.id)] = profile.title
    aggregate["minutes_total"] += int(metrics.minutes_total)
    aggregate["shifts_count"] += int(metrics.shifts_count)
    aggregate["worked_dates"].update(metrics.worked_dates)
    aggregate["components"].extend(breakdown_items)
    aggregate["position_profiles"].append(
        {
            "pay_profile_id": int(profile.id),
            "pay_profile_title": profile.title,
            "position_ids": position_ids,
            "position_titles": position_titles,
            "profile_period_ids": profile_period_ids,
            "assignment_ids": assignment_ids,
            "profile_source": profile_source,
            "discarded_profile_candidates": discarded_profile_candidates,
            "profile_active_from": profile_active_dates[0].isoformat() if profile_active_dates else None,
            "profile_active_to": profile_active_dates[-1].isoformat() if profile_active_dates else None,
            "profile_active_dates_count": len(profile_active_dates),
            "amount_minor": int(line_total),
            "metrics": {
                "minutes_total": int(metrics.minutes_total),
                "hours_total": round(int(metrics.minutes_total) / 60.0, 2),
                "shifts_count": int(metrics.shifts_count),
                "worked_dates_count": len(metrics.worked_dates),
                "worked_dates": [day.isoformat() for day in sorted(metrics.worked_dates)],
            },
        }
    )
    for allocation in shift_allocations:
        shift_id = int(allocation["shift_id"])
        existing = aggregate["shift_allocations"].get(shift_id)
        if existing is None:
            aggregate["shift_allocations"][shift_id] = dict(allocation)
        else:
            existing["amount_minor"] = int(existing.get("amount_minor") or 0) + int(allocation.get("amount_minor") or 0)


def build_payroll_lines_from_position_aggregates(
    db: Session,
    *,
    payroll_run_id: int,
    venue_id: int,
    aggregates: dict[int, dict],
    revenue_metrics,
    kpi_metrics,
) -> tuple[list[PayrollLine], int]:
    lines: list[PayrollLine] = []
    total_amount_minor = 0
    for member_id in sorted(aggregates):
        aggregate = aggregates[member_id]
        member_user = aggregate["member"]
        profile_ids = sorted(int(value) for value in aggregate["profile_ids"])
        single_profile_id = profile_ids[0] if len(profile_ids) == 1 else None
        worked_dates = sorted(aggregate["worked_dates"])
        breakdown = {
            "member_user_id": member_id,
            "member_name": member_user.short_name
            or member_user.full_name
            or member_user.tg_username
            or f"user #{member_id}",
            "pay_profile_id": single_profile_id,
            "pay_profile_title": aggregate["profile_titles"].get(single_profile_id)
            if single_profile_id is not None
            else None,
            "pay_profile_ids": profile_ids,
            "pay_profile_titles": [aggregate["profile_titles"][value] for value in profile_ids],
            "position_profiles": aggregate["position_profiles"],
            "metrics": {
                "minutes_total": int(aggregate["minutes_total"]),
                "hours_total": round(int(aggregate["minutes_total"]) / 60.0, 2),
                "shifts_count": int(aggregate["shifts_count"]),
                "worked_dates_count": len(worked_dates),
                "worked_dates": [day.isoformat() for day in worked_dates],
            },
            "revenue_metrics": {"total_revenue_minor": int(revenue_metrics.total_revenue_minor)},
            "kpi_metrics": {
                str(metric_id): int(value) for metric_id, value in sorted(kpi_metrics.totals_by_metric_id.items())
            },
            "components": aggregate["components"],
            "shift_allocations": [
                aggregate["shift_allocations"][shift_id] for shift_id in sorted(aggregate["shift_allocations"])
            ],
        }
        line = PayrollLine(
            payroll_run_id=int(payroll_run_id),
            venue_id=int(venue_id),
            member_user_id=member_id,
            pay_profile_id=single_profile_id,
            amount_minor=int(aggregate["amount_minor"]),
            breakdown_json=json.dumps(breakdown, ensure_ascii=False),
        )
        db.add(line)
        lines.append(line)
        total_amount_minor += int(aggregate["amount_minor"])
    return lines, total_amount_minor
