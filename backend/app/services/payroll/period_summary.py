from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import Adjustment, DailyReport, PayrollRecalculationLog, Shift, ShiftAssignment, Venue
from app.services.payroll.day_breakdown import build_member_day_breakdown


def resolve_salary_period(*, month: str | None = None, date_from: date | None = None, date_to: date | None = None) -> tuple[date, date, dict]:
    if month and (date_from is not None or date_to is not None):
        raise ValueError("Use either month or date_from/date_to")
    if month:
        try:
            year_s, month_s = str(month).split("-")
            year = int(year_s)
            month_i = int(month_s)
            period_start = date(year, month_i, 1)
            period_end = date(year + 1, 1, 1) - timedelta(days=1) if month_i == 12 else date(year, month_i + 1, 1) - timedelta(days=1)
        except Exception as exc:  # pragma: no cover - validated in router
            raise ValueError("Bad month format, expected YYYY-MM") from exc
        return period_start, period_end, {"mode": "month", "month": month}
    if date_from is None or date_to is None:
        raise ValueError("Provide month or both date_from/date_to")
    if date_from > date_to:
        raise ValueError("date_from must be <= date_to")
    return date_from, date_to, {"mode": "range", "date_from": date_from.isoformat(), "date_to": date_to.isoformat()}


def _month_starts_between(period_start: date, period_end: date) -> list[date]:
    months: list[date] = []
    current = date(period_start.year, period_start.month, 1)
    last = date(period_end.year, period_end.month, 1)
    while current <= last:
        months.append(current)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return months


def _serialize_recalculation_log(log: PayrollRecalculationLog | None) -> dict | None:
    if log is None:
        return None
    return {
        "id": int(log.id),
        "period_month": log.period_month.strftime("%Y-%m") if getattr(log, "period_month", None) else None,
        "trigger_reason": str(log.trigger_reason or ""),
        "triggered_by_user_id": int(log.triggered_by_user_id) if getattr(log, "triggered_by_user_id", None) is not None else None,
        "created_at": log.created_at.isoformat() if getattr(log, "created_at", None) else None,
    }


def _latest_recalculation_by_venue(
    db: Session,
    *,
    venue_ids: list[int],
    period_start: date,
    period_end: date,
) -> dict[int, dict | None]:
    if not venue_ids:
        return {}
    months = _month_starts_between(period_start, period_end)
    if not months:
        return {}
    rows = db.execute(
        select(PayrollRecalculationLog)
        .where(
            PayrollRecalculationLog.venue_id.in_(venue_ids),
            PayrollRecalculationLog.period_month.in_(months),
        )
        .order_by(PayrollRecalculationLog.venue_id.asc(), PayrollRecalculationLog.created_at.desc(), PayrollRecalculationLog.id.desc())
    ).scalars().all()
    out: dict[int, dict | None] = {int(vid): None for vid in venue_ids}
    for row in rows:
        vid = int(row.venue_id)
        if out.get(vid) is None:
            out[vid] = _serialize_recalculation_log(row)
    return out


def _collect_member_candidate_dates(
    db: Session,
    *,
    member_user_id: int,
    period_start: date,
    period_end: date,
    venue_id: int | None = None,
) -> dict[int, set[date]]:
    candidates: dict[int, set[date]] = defaultdict(set)

    shift_rows = db.execute(
        select(Shift.venue_id, Shift.date)
        .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
        .join(DailyReport, and_(DailyReport.venue_id == Shift.venue_id, DailyReport.date == Shift.date))
        .where(
            ShiftAssignment.member_user_id == int(member_user_id),
            Shift.is_active.is_(True),
            Shift.date >= period_start,
            Shift.date <= period_end,
            DailyReport.status == "CLOSED",
            *([Shift.venue_id == int(venue_id)] if venue_id is not None else []),
        )
        .distinct()
    ).all()
    for row in shift_rows:
        candidates[int(row.venue_id)].add(row.date)

    adjustment_rows = db.execute(
        select(Adjustment.venue_id, Adjustment.date)
        .where(
            Adjustment.member_user_id == int(member_user_id),
            Adjustment.is_active.is_(True),
            Adjustment.date >= period_start,
            Adjustment.date <= period_end,
            *([Adjustment.venue_id == int(venue_id)] if venue_id is not None else []),
        )
        .distinct()
    ).all()
    for row in adjustment_rows:
        candidates[int(row.venue_id)].add(row.date)

    return candidates


def build_member_period_summary(
    db: Session,
    *,
    member_user_id: int,
    period_start: date,
    period_end: date,
    venue_id: int | None = None,
) -> dict:
    candidates = _collect_member_candidate_dates(
        db,
        member_user_id=int(member_user_id),
        period_start=period_start,
        period_end=period_end,
        venue_id=int(venue_id) if venue_id is not None else None,
    )

    venue_ids = sorted(candidates.keys())
    venue_names: dict[int, str] = {}
    if venue_ids:
        venue_rows = db.execute(select(Venue.id, Venue.name).where(Venue.id.in_(venue_ids))).all()
        venue_names = {int(row.id): str(row.name or "") for row in venue_rows}

    latest_recalc = _latest_recalculation_by_venue(
        db,
        venue_ids=venue_ids,
        period_start=period_start,
        period_end=period_end,
    )

    items: list[dict] = []
    totals_minor = {"earned_minor": 0, "tips_minor": 0, "bonuses_minor": 0, "penalties_minor": 0, "net_minor": 0}

    for vid in venue_ids:
        dates = sorted(day for day in candidates.get(vid, set()) if period_start <= day <= period_end)
        earned_minor = 0
        tips_minor = 0
        bonuses_minor = 0
        penalties_minor = 0
        net_minor = 0
        payroll_present = False
        partial_present = False
        states_seen: set[str] = set()
        for day in dates:
            breakdown = build_member_day_breakdown(
                db,
                member_user_id=int(member_user_id),
                venue_id=int(vid),
                target_date=day,
            )
            summary = breakdown.get("summary") or {}
            context = breakdown.get("context") or {}
            earned_minor += int(summary.get("earnings_minor") or 0)
            tips_minor += int(summary.get("tips_minor") or 0)
            bonuses_minor += int(summary.get("bonuses_minor") or 0)
            penalties_minor += int(summary.get("penalties_minor") or 0)
            net_minor += int(summary.get("total_minor") or 0)
            payroll_present = payroll_present or bool(context.get("has_payroll_line"))
            state = str(breakdown.get("state") or "").lower()
            if state:
                states_seen.add(state)
            if state in {"partial", "no_payroll"}:
                partial_present = True

        if not dates and not any([earned_minor, tips_minor, bonuses_minor, penalties_minor, net_minor]):
            continue

        if partial_present:
            period_state = "partial"
        elif payroll_present or any([earned_minor, tips_minor, bonuses_minor, penalties_minor, net_minor]):
            period_state = "ready"
        else:
            period_state = "empty"

        source = "payroll" if payroll_present else ("partial" if any([tips_minor, bonuses_minor, penalties_minor]) else "not_calculated")
        item = {
            "venue": {"id": int(vid), "name": venue_names.get(int(vid), "")},
            "earned_minor": int(earned_minor),
            "tips_minor": int(tips_minor),
            "bonuses_minor": int(bonuses_minor),
            "penalties_minor": int(penalties_minor),
            "net_minor": int(net_minor),
            "earned": int(round(earned_minor / 100.0)),
            "tips": int(round(tips_minor / 100.0)),
            "bonuses": int(round(bonuses_minor / 100.0)),
            "penalties": int(round(penalties_minor / 100.0)),
            "net": int(round(net_minor / 100.0)),
            "source": source,
            "calculated": bool(payroll_present),
            "period_state": period_state,
            "days_count": len(dates),
            "latest_recalculation": latest_recalc.get(int(vid)),
        }
        items.append(item)
        totals_minor["earned_minor"] += int(earned_minor)
        totals_minor["tips_minor"] += int(tips_minor)
        totals_minor["bonuses_minor"] += int(bonuses_minor)
        totals_minor["penalties_minor"] += int(penalties_minor)
        totals_minor["net_minor"] += int(net_minor)

    totals = {
        "earned_minor": int(totals_minor["earned_minor"]),
        "tips_minor": int(totals_minor["tips_minor"]),
        "bonuses_minor": int(totals_minor["bonuses_minor"]),
        "penalties_minor": int(totals_minor["penalties_minor"]),
        "net_minor": int(totals_minor["net_minor"]),
        "earned": int(round(totals_minor["earned_minor"] / 100.0)),
        "tips": int(round(totals_minor["tips_minor"] / 100.0)),
        "bonuses": int(round(totals_minor["bonuses_minor"] / 100.0)),
        "penalties": int(round(totals_minor["penalties_minor"] / 100.0)),
        "net": int(round(totals_minor["net_minor"] / 100.0)),
    }

    items.sort(key=lambda item: (0 if item.get("calculated") else 1, str(item.get("venue", {}).get("name") or "")))

    return {
        "items": items,
        "totals": totals,
        "period": {
            "date_from": period_start.isoformat(),
            "date_to": period_end.isoformat(),
            "mode": "month" if period_start.day == 1 and (period_end.day in {28, 29, 30, 31}) else "range",
        },
    }
