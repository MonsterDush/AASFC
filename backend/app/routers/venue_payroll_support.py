from __future__ import annotations

from datetime import datetime, date, timedelta
import json
import logging
import time
from sqlalchemy import select, inspect
import sqlalchemy as sa
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.metrics import record_payroll_recalculation
from app.services.payroll.calculator import (
    calculate_payroll_for_month,
    parse_month_start,
)
from app.services.payroll.day_breakdown import build_member_day_breakdown
from app.services.payroll.adjustments import load_member_payroll_adjustments
from app.models.user import User
from app.models.shift import Shift
from app.models.shift_assignment import ShiftAssignment
from app.models.daily_report import DailyReport
from app.models.adjustment import Adjustment
from app.models.pay_profile import PayProfile
from app.models.payroll_run import PayrollRun
from app.models.payroll_line import PayrollLine
from app.models.payroll_recalculation_log import PayrollRecalculationLog


from app.routers.venue_pay_profile_support import (
    _parse_json_text,
)


_LOG = logging.getLogger("axelio.payroll.recalculation")


def _payroll_calculation_details(
    calculation,
    *,
    previous_total_amount_minor: int | None,
    duration_seconds: float,
    transaction_result: str,
    extra: dict | None = None,
) -> dict:
    diagnostics = dict(getattr(calculation, "diagnostics", {}) or {})
    total_amount_minor = int(calculation.run.total_amount_minor or 0)
    return {
        **(extra or {}),
        "release": settings.release_version(),
        "transaction_result": str(transaction_result or "unknown"),
        "duration_ms": round(max(0.0, float(duration_seconds)) * 1000, 2),
        "previous_total_amount_minor": (
            int(previous_total_amount_minor) if previous_total_amount_minor is not None else None
        ),
        "total_amount_minor": total_amount_minor,
        "total_delta_minor": (
            total_amount_minor - int(previous_total_amount_minor) if previous_total_amount_minor is not None else None
        ),
        "warning_count": len(calculation.warnings),
        "warnings": calculation.warnings,
        "lines_count": len(calculation.lines),
        **diagnostics,
    }


def _payroll_preview_payload(
    db: Session,
    *,
    venue_id: int,
    month: str,
    calculated_by_user_id: int | None,
) -> dict:
    """Calculate diagnostics inside a savepoint and roll every write back."""

    savepoint = db.begin_nested()
    try:
        calculation = calculate_payroll_for_month(
            db=db,
            venue_id=int(venue_id),
            month=month,
            calculated_by_user_id=(int(calculated_by_user_id) if calculated_by_user_id is not None else None),
        )
        db.flush()
        calculated_payload = _load_payroll_payload(db, venue_id=int(venue_id), month=month)
        lines = list(calculated_payload.get("lines") or [])
        profiles_without_components: dict[int, dict] = {}
        for line in lines:
            breakdown = line.get("breakdown") or {}
            components = list(breakdown.get("components") or [])
            component_profile_ids = {
                int(item["pay_profile_id"]) for item in components if item.get("pay_profile_id") is not None
            }
            for profile in breakdown.get("position_profiles") or []:
                profile_id = profile.get("pay_profile_id")
                if profile_id is None or int(profile_id) in component_profile_ids:
                    continue
                profiles_without_components[int(profile_id)] = {
                    "code": "PAY_PROFILE_WITHOUT_COMPONENTS",
                    "member_user_id": int(line.get("member_user_id") or 0),
                    "pay_profile_id": int(profile_id),
                    "pay_profile_title": profile.get("pay_profile_title"),
                    "position_ids": list(profile.get("position_ids") or []),
                    "profile_active_from": profile.get("profile_active_from"),
                    "profile_active_to": profile.get("profile_active_to"),
                }
        blocking_warnings = [
            *calculation.warnings,
            *profiles_without_components.values(),
        ]
        return {
            "month": month,
            "total_amount_minor": int(calculated_payload.get("total_amount_minor") or 0),
            "lines_count": len(lines),
            "lines": lines,
            "warnings": calculation.warnings,
            "profiles_without_components": list(profiles_without_components.values()),
            "blocking_warnings": blocking_warnings,
            "is_blocked": bool(blocking_warnings),
            "diagnostics": dict(calculation.diagnostics or {}),
        }
    finally:
        savepoint.rollback()
        for instance in list(db.identity_map.values()):
            if isinstance(instance, (PayrollRun, PayrollLine)):
                db.expunge(instance)
        db.expire_all()


def _payroll_table_exists(db: Session, table_name: str) -> bool:
    try:
        # Reuse the transaction connection. Inspecting the Engine can check out
        # and roll back the same DBAPI connection under SQLite/StaticPool,
        # discarding pending position/profile changes before recalculation.
        return bool(inspect(db.connection()).has_table(table_name))
    except Exception:
        return True


def _payroll_recalculation_logs_table_exists(db: Session) -> bool:
    return _payroll_table_exists(db, PayrollRecalculationLog.__tablename__)


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
    details: dict = {}
    try:
        raw_details = json.loads(row.details_json) if row.details_json else {}
        if isinstance(raw_details, dict):
            details = raw_details
    except Exception:
        details = {}
    return {
        "id": int(row.id),
        "period_month": row.period_month.strftime("%Y-%m") if getattr(row, "period_month", None) else None,
        "trigger_reason": str(row.trigger_reason or ""),
        "triggered_by_user_id": int(row.triggered_by_user_id)
        if getattr(row, "triggered_by_user_id", None) is not None
        else None,
        "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
        "target_dates": target_dates,
        "details": details,
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
        target_dates_json=json.dumps(
            sorted({day.isoformat() for day in (target_dates or []) if isinstance(day, date)}), ensure_ascii=False
        ),
        details_json=json.dumps(details or {}, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    db.flush()
    return obj


def _latest_payroll_recalculation_log(
    db: Session, *, venue_id: int, period_month: date
) -> PayrollRecalculationLog | None:
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
        select(DailyReport.id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.date == target_date,
            DailyReport.status == "CLOSED",
        )
        .limit(1)
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
        previous_total_amount_minor = db.execute(
            select(PayrollRun.total_amount_minor).where(
                PayrollRun.venue_id == int(venue_id),
                PayrollRun.period_month == parse_month_start(month),
            )
        ).scalar_one_or_none()
        started_at = time.perf_counter()
        try:
            calculation = calculate_payroll_for_month(
                db=db,
                venue_id=int(venue_id),
                month=month,
                calculated_by_user_id=int(calculated_by_user_id) if calculated_by_user_id is not None else None,
            )
        except Exception:
            duration_seconds = time.perf_counter() - started_at
            record_payroll_recalculation(
                trigger_reason=str(trigger_reason or "system"),
                duration_seconds=duration_seconds,
                result="failed",
            )
            _LOG.exception(
                "payroll_recalculation_failed",
                extra={
                    "venue_id": int(venue_id),
                    "period_month": month,
                    "trigger_reason": str(trigger_reason or "system"),
                    "duration_ms": round(duration_seconds * 1000, 2),
                },
            )
            raise
        duration_seconds = time.perf_counter() - started_at
        month_start = parse_month_start(month)
        month_target_dates = sorted(day for day in target_dates if day.strftime("%Y-%m") == month)
        calculation_details = _payroll_calculation_details(
            calculation,
            previous_total_amount_minor=(
                int(previous_total_amount_minor) if previous_total_amount_minor is not None else None
            ),
            duration_seconds=duration_seconds,
            transaction_result="committed",
            extra=details,
        )
        _create_payroll_recalculation_log(
            db,
            venue_id=int(venue_id),
            period_month=month_start,
            trigger_reason=str(trigger_reason or "system"),
            triggered_by_user_id=int(calculated_by_user_id) if calculated_by_user_id is not None else None,
            target_dates=month_target_dates,
            details=calculation_details,
        )
        record_payroll_recalculation(
            trigger_reason=str(trigger_reason or "system"),
            duration_seconds=duration_seconds,
            warnings=calculation.warnings,
        )
        _LOG.info(
            "payroll_recalculated",
            extra={
                "venue_id": int(venue_id),
                "period_month": month,
                "trigger_reason": str(trigger_reason or "system"),
                **calculation_details,
            },
        )
        seen.add(month)
        months_done.append(month)
    return months_done


def _recalculate_affected_payroll_runs(
    db: Session,
    *,
    venue_id: int,
    calculated_by_user_id: int | None,
    trigger_reason: str,
    details: dict | None = None,
    affected_from: date | None = None,
    affected_to: date | None = None,
) -> list[str]:
    """Recalculate persisted months inside an explicitly affected date range."""

    # Some maintenance/legacy schemas can be upgraded in stages. Position and
    # profile writes must remain available until the payroll tables arrive.
    if not _payroll_table_exists(db, PayrollRun.__tablename__):
        return []

    if affected_from is not None and affected_to is not None and affected_to < affected_from:
        affected_from, affected_to = affected_to, affected_from

    month_filters = [PayrollRun.venue_id == int(venue_id)]
    if affected_from is not None:
        month_filters.append(PayrollRun.period_month >= date(affected_from.year, affected_from.month, 1))
    if affected_to is not None:
        month_filters.append(PayrollRun.period_month <= date(affected_to.year, affected_to.month, 1))
    months = list(
        db.execute(
            select(PayrollRun.period_month).where(*month_filters).order_by(PayrollRun.period_month.asc())
        ).scalars()
    )
    return _recalculate_payroll_for_dates(
        db,
        venue_id=int(venue_id),
        target_dates=months,
        calculated_by_user_id=calculated_by_user_id,
        force=True,
        trigger_reason=trigger_reason,
        details=details,
    )


def _load_payroll_payload(db: Session, *, venue_id: int, month: str) -> dict:
    month_start = parse_month_start(month)
    month_end = (
        date(month_start.year + 1, 1, 1)
        if month_start.month == 12
        else date(month_start.year, month_start.month + 1, 1)
    ) - timedelta(days=1)
    latest_recalculation = _latest_payroll_recalculation_log(db, venue_id=int(venue_id), period_month=month_start)
    run = db.execute(
        select(PayrollRun).where(
            PayrollRun.venue_id == venue_id,
            PayrollRun.period_month == month_start,
        )
    ).scalar_one_or_none()
    if run is None:
        partial = _build_venue_payroll_period_payload(
            db,
            venue_id=int(venue_id),
            period_start=month_start,
            period_end=month_end,
            period_meta={"mode": "month", "month": month},
        )
        partial["run"] = None
        partial["latest_recalculation"] = _serialize_payroll_recalculation_log(latest_recalculation)
        return partial

    rows = db.execute(
        select(PayrollLine, User, PayProfile)
        .join(User, User.id == PayrollLine.member_user_id)
        .outerjoin(PayProfile, PayProfile.id == PayrollLine.pay_profile_id)
        .where(PayrollLine.payroll_run_id == int(run.id))
        .order_by(User.short_name.asc(), User.full_name.asc(), PayrollLine.id.asc())
    ).all()

    adjustments_by_member = load_member_payroll_adjustments(
        db,
        venue_id=int(venue_id),
        period_start=month_start,
        period_end=month_end,
    )
    members_by_id = {int(member.id): member for _line, member, _profile in rows}
    missing_member_ids = sorted(set(adjustments_by_member) - set(members_by_id))
    if missing_member_ids:
        extra_members = db.execute(select(User).where(User.id.in_(missing_member_ids))).scalars().all()
        members_by_id.update({int(member.id): member for member in extra_members})

    lines = []
    seen_member_ids: set[int] = set()
    for line, member, profile in rows:
        member_id = int(line.member_user_id)
        seen_member_ids.add(member_id)
        adjustment_items = adjustments_by_member.get(member_id, [])
        adjustment_total_minor = sum(int(item.get("amount_minor") or 0) for item in adjustment_items)
        breakdown = _parse_json_text(line.breakdown_json) or {}
        breakdown["components"] = [*(breakdown.get("components") or []), *adjustment_items]
        breakdown["adjustments_minor"] = int(adjustment_total_minor)
        lines.append(
            {
                "id": int(line.id),
                "member_user_id": member_id,
                "amount_minor": int(line.amount_minor or 0) + int(adjustment_total_minor),
                "pay_profile_id": int(line.pay_profile_id) if line.pay_profile_id is not None else None,
                "pay_profile_title": profile.title if profile is not None else None,
                "member": {
                    "user_id": int(member.id),
                    "tg_user_id": member.tg_user_id,
                    "tg_username": member.tg_username,
                    "full_name": member.full_name,
                    "short_name": member.short_name,
                },
                "breakdown": breakdown,
            }
        )

    for member_id in sorted(set(adjustments_by_member) - seen_member_ids):
        member = members_by_id.get(member_id)
        if member is None:
            continue
        adjustment_items = adjustments_by_member[member_id]
        adjustment_total_minor = sum(int(item.get("amount_minor") or 0) for item in adjustment_items)
        lines.append(
            {
                "id": None,
                "member_user_id": int(member_id),
                "amount_minor": int(adjustment_total_minor),
                "pay_profile_id": None,
                "pay_profile_title": None,
                "member": {
                    "user_id": int(member.id),
                    "tg_user_id": member.tg_user_id,
                    "tg_username": member.tg_username,
                    "full_name": member.full_name,
                    "short_name": member.short_name,
                },
                "breakdown": {
                    "metrics": {"hours_total": 0, "shifts_count": 0, "worked_dates_count": 0, "worked_dates": []},
                    "components": list(adjustment_items),
                    "adjustments_minor": int(adjustment_total_minor),
                },
            }
        )

    lines.sort(
        key=lambda item: (
            str(
                (item.get("member") or {}).get("short_name") or (item.get("member") or {}).get("full_name") or ""
            ).lower(),
            int(item.get("member_user_id") or 0),
        )
    )
    total_amount_minor = sum(int(item.get("amount_minor") or 0) for item in lines)

    return {
        "month": month,
        "run": {
            "id": int(run.id),
            "venue_id": int(run.venue_id),
            "period_month": run.period_month.isoformat() if run.period_month else None,
            "calculated_by_user_id": run.calculated_by_user_id,
            "calculated_at": run.calculated_at.isoformat() if run.calculated_at else None,
            "total_amount_minor": int(total_amount_minor),
            "base_total_amount_minor": int(run.total_amount_minor or 0),
            "lines_count": len(lines),
        },
        "lines": lines,
        "total_amount_minor": int(total_amount_minor),
        "lines_count": len(lines),
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


def _latest_payroll_recalculation_for_period(
    db: Session, *, venue_id: int, period_start: date, period_end: date
) -> dict | None:
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
        .join(
            DailyReport,
            sa.and_(
                DailyReport.venue_id == Shift.venue_id,
                DailyReport.date == Shift.date,
                DailyReport.shift_slot == Shift.shift_slot,
            ),
        )
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
    members = db.execute(select(User).where(User.id.in_(member_ids))).scalars().all() if member_ids else []
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
            for item in day_breakdown.get("items") or []:
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

    lines.sort(
        key=lambda item: (
            (str(item.get("member", {}).get("short_name") or item.get("member", {}).get("full_name") or "").lower()),
            int(item.get("member_user_id") or 0),
        )
    )

    return {
        **period_meta,
        "run": None,
        "lines": lines,
        "total_amount_minor": int(total_amount_minor),
        "lines_count": len(lines),
        "latest_recalculation": latest_recalculation,
    }
