from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import PayrollLine


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
    for item in breakdown_items:
        item["pay_profile_id"] = int(profile.id)
        item["pay_profile_title"] = profile.title
        item["position_ids"] = position_ids
        item["position_titles"] = position_titles

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
