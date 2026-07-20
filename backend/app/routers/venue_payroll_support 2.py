from __future__ import annotations

from datetime import datetime, timezone, date, time, timedelta
import json
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status, UploadFile, File
from sqlalchemy import select, delete, update, func, inspect
import sqlalchemy as sa
from sqlalchemy.orm import Session
from app.core.permission_codes import parse_permission_codes, normalize_known_permission_codes
from app.services.payroll.calculator import (
    PAY_COMPONENT_TYPES,
    BASE_SCOPE_FULL_PERIOD,
    BASE_SCOPE_WORKED_DATES,
    BOOST_RECALC_EXCESS_ONLY,
    BOOST_RECALC_REPLACE_ALL,
    BOOST_SOURCE_DEPARTMENT_DAY_PLAN,
    BOOST_SOURCE_DEPARTMENT_MONTH_PLAN,
    BOOST_SOURCE_KPI_METRIC,
    BOOST_SOURCE_NONE,
    BOOST_SOURCE_VENUE_DAY_PLAN,
    BOOST_SOURCE_VENUE_MONTH_PLAN,
    MINIMUM_GUARANTEE_DAY,
    MINIMUM_GUARANTEE_MONTH,
    MINIMUM_GUARANTEE_SHIFT,
    calculate_payroll_for_month,
    parse_month_start,
)
from app.services.payroll.day_breakdown import build_member_day_breakdown
from app.routers.venue_access import (
    _has_revenue_view_access,
    _is_active_member_or_admin,
    _is_owner_or_super_admin,
    _is_report_viewer,
    _require_active_member_or_admin,
    _require_owner_or_super_admin,
    _require_report_viewer,
    _require_revenue_viewer,
)
from app.models.user import User
from app.models.venue_setup_state import VenueSetupState
from app.models.shift import Shift
from app.models.shift_assignment import ShiftAssignment
from app.models.daily_report import DailyReport
from app.models.adjustment import Adjustment
from app.models.department import Department
from app.models.pay_profile import PayProfile
from app.models.pay_profile_assignment import PayProfileAssignment
from app.models.pay_component import PayComponent
from app.models.payroll_run import PayrollRun
from app.models.payroll_line import PayrollLine
from app.models.payroll_recalculation_log import PayrollRecalculationLog
from app.auth.venue_permissions import require_venue_permission, has_venue_permission

from app.routers.venue_common import (
    BASE_SCOPE_TITLES,
    BOOST_RECALC_TITLES,
    BOOST_SOURCE_TITLES,
    MINIMUM_GUARANTEE_SCOPE_TITLES,
)

from app.routers.venue_pay_profile_support import (
    _parse_json_text,
    _require_payroll_calculate,
    _require_payroll_view,
)


def _payroll_recalculation_logs_table_exists(db: Session) -> bool:
    try:
        return bool(inspect(db.get_bind()).has_table(PayrollRecalculationLog.__tablename__))
    except Exception:
        return True


def _serialize_payroll_recalculation_log(row: PayrollRecalculationLog | None) -> dict | None:
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
        "triggered_by_user_id": int(row.triggered_by_user_id) if getattr(row, "triggered_by_user_id", None) is not None else None,
        "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
        "target_dates": target_dates,
    }


def _create_payroll_recalculation_log(
    db: Session,
    *,
    venue_id: int,
    period_month: date,
    trigger_reason: str,
    triggered_by_user_id: int | None = None,
    target_dates: list[date] | tuple[date, ...] | None = None,
    details: dict | None = None,
) -> PayrollRecalculationLog | None:
    if not _payroll_recalculation_logs_table_exists(db):
        return None
    obj = PayrollRecalculationLog(
        venue_id=int(venue_id),
        period_month=period_month,
        triggered_by_user_id=int(triggered_by_user_id) if triggered_by_user_id is not None else None,
        trigger_reason=str(trigger_reason or "system"),
        target_dates_json=json.dumps(sorted({day.isoformat() for day in (target_dates or []) if isinstance(day, date)}), ensure_ascii=False),
        details_json=json.dumps(details or {}, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    db.flush()
    return obj


def _latest_payroll_recalculation_log(db: Session, *, venue_id: int, period_month: date) -> PayrollRecalculationLog | None:
    if not _payroll_recalculation_logs_table_exists(db):
        return None
    return db.execute(
        select(PayrollRecalculationLog)
        .where(
            PayrollRecalculationLog.venue_id == int(venue_id),
            PayrollRecalculationLog.period_month == period_month,
        )
        .order_by(PayrollRecalculationLog.created_at.desc(), PayrollRecalculationLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _has_closed_report_for_date(db: Session, *, venue_id: int, target_date: date) -> bool:
    report_id = db.execute(
        select(DailyReport.id).where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.date == target_date,
            DailyReport.status == "CLOSED",
        )
    ).scalar_one_or_none()
    return report_id is not None


def _recalculate_payroll_for_dates(
    db: Session,
    *,
    venue_id: int,
    target_dates: list[date] | tuple[date, ...],
    calculated_by_user_id: int | None = None,
    force: bool = False,
    trigger_reason: str = "system",
    details: dict | None = None,
) -> list[str]:
    months_done: list[str] = []
    seen: set[str] = set()
    target_dates = [day for day in target_dates if isinstance(day, date)]
    for target_date in target_dates:
        month = target_date.strftime("%Y-%m")
        if month in seen:
            continue
        if not force and not _has_closed_report_for_date(db, venue_id=venue_id, target_date=target_date):
            continue
        calculate_payroll_for_month(
            db=db,
            venue_id=int(venue_id),
            month=month,
            calculated_by_user_id=int(calculated_by_user_id) if calculated_by_user_id is not None else None,
        )
        month_start = parse_month_start(month)
        month_target_dates = sorted(day for day in target_dates if day.strftime("%Y-%m") == month)
        _create_payroll_recalculation_log(
            db,
            venue_id=int(venue_id),
            period_month=month_start,
            trigger_reason=str(trigger_reason or "system"),
            triggered_by_user_id=int(calculated_by_user_id) if calculated_by_user_id is not None else None,
            target_dates=month_target_dates,
            details=details or {},
        )
        seen.add(month)
        months_done.append(month)
    return months_done


def _load_payroll_payload(db: Session, *, venue_id: int, month: str) -> dict:
    month_start = parse_month_start(month)
    latest_recalculation = _latest_payroll_recalculation_log(db, venue_id=int(venue_id), period_month=month_start)
    run = db.execute(
        select(PayrollRun).where(
            PayrollRun.venue_id == venue_id,
            PayrollRun.period_month == month_start,
        )
    ).scalar_one_or_none()
    if run is None:
        return {
            "month": month,
            "run": None,
            "lines": [],
            "total_amount_minor": 0,
            "lines_count": 0,
            "latest_recalculation": _serialize_payroll_recalculation_log(latest_recalculation),
        }

    rows = db.execute(
        select(PayrollLine, User, PayProfile)
        .join(User, User.id == PayrollLine.member_user_id)
        .outerjoin(PayProfile, PayProfile.id == PayrollLine.pay_profile_id)
        .where(PayrollLine.payroll_run_id == int(run.id))
        .order_by(User.short_name.asc(), User.full_name.asc(), PayrollLine.id.asc())
    ).all()

    lines = []
    for line, member, profile in rows:
        lines.append(
            {
                "id": int(line.id),
                "member_user_id": int(line.member_user_id),
                "amount_minor": int(line.amount_minor or 0),
                "pay_profile_id": int(line.pay_profile_id) if line.pay_profile_id is not None else None,
                "pay_profile_title": profile.title if profile is not None else None,
                "member": {
                    "user_id": int(member.id),
                    "tg_user_id": member.tg_user_id,
                    "tg_username": member.tg_username,
                    "full_name": member.full_name,
                    "short_name": member.short_name,
                },
                "breakdown": _parse_json_text(line.breakdown_json),
            }
        )

    return {
        "month": month,
        "run": {
            "id": int(run.id),
            "venue_id": int(run.venue_id),
            "period_month": run.period_month.isoformat() if run.period_month else None,
            "calculated_by_user_id": run.calculated_by_user_id,
            "calculated_at": run.calculated_at.isoformat() if run.calculated_at else None,
            "total_amount_minor": int(run.total_amount_minor or 0),
            "lines_count": int(run.lines_count or 0),
        },
        "lines": lines,
        "total_amount_minor": int(run.total_amount_minor or 0),
        "lines_count": int(run.lines_count or 0),
        "latest_recalculation": _serialize_payroll_recalculation_log(latest_recalculation),
    }


def _month_starts_between(period_start: date, period_end: date) -> list[date]:
    current = date(period_start.year, period_start.month, 1)
    last = date(period_end.year, period_end.month, 1)
    months: list[date] = []
    while current <= last:
        months.append(current)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return months


def _latest_payroll_recalculation_for_period(db: Session, *, venue_id: int, period_start: date, period_end: date) -> dict | None:
    months = _month_starts_between(period_start, period_end)
    if not months or not _payroll_recalculation_logs_table_exists(db):
        return None
    row = db.execute(
        select(PayrollRecalculationLog)
        .where(
            PayrollRecalculationLog.venue_id == int(venue_id),
            PayrollRecalculationLog.period_month.in_(months),
        )
        .order_by(PayrollRecalculationLog.created_at.desc(), PayrollRecalculationLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return _serialize_payroll_recalculation_log(row)


def _collect_venue_payroll_candidate_dates(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
) -> dict[int, set[date]]:
    candidates: dict[int, set[date]] = {}

    shift_rows = db.execute(
        select(ShiftAssignment.member_user_id, Shift.date)
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .join(DailyReport, sa.and_(DailyReport.venue_id == Shift.venue_id, DailyReport.date == Shift.date))
        .where(
            Shift.venue_id == int(venue_id),
            Shift.is_active.is_(True),
            Shift.date >= period_start,
            Shift.date <= period_end,
            DailyReport.status == "CLOSED",
        )
        .distinct()
    ).all()
    for member_user_id, shift_date in shift_rows:
        if member_user_id is None or shift_date is None:
            continue
        candidates.setdefault(int(member_user_id), set()).add(shift_date)

    adjustment_rows = db.execute(
        select(Adjustment.member_user_id, Adjustment.date)
        .where(
            Adjustment.venue_id == int(venue_id),
            Adjustment.is_active.is_(True),
            Adjustment.date >= period_start,
            Adjustment.date <= period_end,
            Adjustment.member_user_id.is_not(None),
        )
        .distinct()
    ).all()
    for member_user_id, adjustment_date in adjustment_rows:
        if member_user_id is None or adjustment_date is None:
            continue
        candidates.setdefault(int(member_user_id), set()).add(adjustment_date)

    return candidates


def _build_venue_payroll_period_payload(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
    period_meta: dict,
) -> dict:
    member_dates = _collect_venue_payroll_candidate_dates(
        db,
        venue_id=int(venue_id),
        period_start=period_start,
        period_end=period_end,
    )

    member_ids = sorted(member_dates.keys())
    members = db.execute(
        select(User).where(User.id.in_(member_ids))
    ).scalars().all() if member_ids else []
    members_by_id = {int(member.id): member for member in members}

    lines: list[dict] = []
    total_amount_minor = 0
    latest_recalculation = _latest_payroll_recalculation_for_period(
        db,
        venue_id=int(venue_id),
        period_start=period_start,
        period_end=period_end,
    )

    for member_id in member_ids:
        dates = sorted(member_dates.get(member_id, set()))
        if not dates:
            continue

        earnings_minor = 0
        tips_minor = 0
        bonuses_minor = 0
        penalties_minor = 0
        total_minor = 0
        minutes_total = 0
        shifts_count = 0
        worked_dates: set[str] = set()
        pay_profile_titles: list[str] = []
        has_payroll_line = False
        components_map: dict[tuple[str, str, str, str], dict] = {}

        for target_date in dates:
            day_breakdown = build_member_day_breakdown(
                db,
                member_user_id=int(member_id),
                venue_id=int(venue_id),
                target_date=target_date,
            )
            summary = day_breakdown.get("summary") or {}
            context = day_breakdown.get("context") or {}
            earnings_minor += int(summary.get("earnings_minor") or 0)
            tips_minor += int(summary.get("tips_minor") or 0)
            bonuses_minor += int(summary.get("bonuses_minor") or 0)
            penalties_minor += int(summary.get("penalties_minor") or 0)
            total_minor += int(summary.get("total_minor") or 0)
            minutes_total += int(context.get("minutes_total") or 0)
            shifts_count += int(context.get("shifts_count") or 0)
            if context.get("has_payroll_line"):
                has_payroll_line = True
            pay_profile_title = str(context.get("pay_profile_title") or "").strip()
            if pay_profile_title:
                pay_profile_titles.append(pay_profile_title)
            for item in (day_breakdown.get("items") or []):
                if not isinstance(item, dict):
                    continue
                key = (
                    str(item.get("category") or ""),
                    str(item.get("component_type") or ""),
                    str(item.get("title") or ""),
                    str(item.get("formula_text") or ""),
                )
                existing = components_map.get(key)
                if existing is None:
                    existing = {
                        "category": str(item.get("category") or ""),
                        "component_type": str(item.get("component_type") or ""),
                        "title": str(item.get("title") or ""),
                        "base_text": str(item.get("base_text") or ""),
                        "formula_text": str(item.get("formula_text") or ""),
                        "amount_minor": 0,
                    }
                    components_map[key] = existing
                existing["amount_minor"] += int(item.get("amount_minor") or 0)
            if int(context.get("minutes_total") or 0) > 0 or int(context.get("shifts_count") or 0) > 0:
                worked_dates.add(target_date.isoformat())

        if not any([earnings_minor, tips_minor, bonuses_minor, penalties_minor, total_minor]):
            continue

        member = members_by_id.get(int(member_id))
        unique_titles = sorted({title for title in pay_profile_titles if title})
        if len(unique_titles) == 1:
            pay_profile_title = unique_titles[0]
        elif len(unique_titles) > 1:
            pay_profile_title = "Несколько профилей"
        else:
            pay_profile_title = None

        components = sorted(
            components_map.values(),
            key=lambda item: (0 if int(item.get("amount_minor") or 0) >= 0 else 1, str(item.get("title") or "")),
        )

        line_payload = {
            "id": None,
            "member_user_id": int(member_id),
            "amount_minor": int(total_minor),
            "pay_profile_id": None,
            "pay_profile_title": pay_profile_title,
            "member": {
                "user_id": int(member.id) if member is not None else int(member_id),
                "tg_user_id": getattr(member, "tg_user_id", None),
                "tg_username": getattr(member, "tg_username", None),
                "full_name": getattr(member, "full_name", None),
                "short_name": getattr(member, "short_name", None),
            },
            "breakdown": {
                "metrics": {
                    "hours_total": round(minutes_total / 60.0, 2),
                    "shifts_count": int(shifts_count),
                    "worked_dates_count": len(worked_dates),
                    "worked_dates": sorted(worked_dates),
                },
                "components": components,
                "summary": {
                    "earnings_minor": int(earnings_minor),
                    "tips_minor": int(tips_minor),
                    "bonuses_minor": int(bonuses_minor),
                    "penalties_minor": int(penalties_minor),
                    "total_minor": int(total_minor),
                },
                "period_mode": "range",
                "period": {
                    "date_from": period_start.isoformat(),
                    "date_to": period_end.isoformat(),
                },
            },
            "period_state": "ready" if has_payroll_line else ("partial" if total_minor else "empty"),
        }
        lines.append(line_payload)
        total_amount_minor += int(total_minor)

    lines.sort(key=lambda item: ((str(item.get("member", {}).get("short_name") or item.get("member", {}).get("full_name") or "").lower()), int(item.get("member_user_id") or 0)))

    return {
        **period_meta,
        "run": None,
        "lines": lines,
        "total_amount_minor": int(total_amount_minor),
        "lines_count": len(lines),
        "latest_recalculation": latest_recalculation,
    }
