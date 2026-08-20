from __future__ import annotations

from datetime import datetime, timezone, date, timedelta
import json
import hashlib
from sqlalchemy import select
import sqlalchemy as sa
from sqlalchemy.orm import Session
from app.core.db import SessionLocal
from app.core.i18n import localized, user_locale
from app.services import tg_notify
from app.services.notification_logs import (
    log_notification_attempt,
    lock_notification_idempotency_key,
    notification_delivery_exists,
)
from app.services.payroll.day_breakdown import build_member_day_breakdown
from app.services.finance.day_economics import get_day_economics
from app.routers.venue_access import (
    _has_revenue_view_access,
    _is_report_viewer,
)
from app.models.user import User
from app.models.venue_member import VenueMember
from app.models.shift import Shift
from app.models.shift_assignment import ShiftAssignment
from app.models.daily_report import DailyReport
from app.models.daily_report_tip_allocation import DailyReportTipAllocation
from app.models.notification_job import NotificationJob
from app.models.adjustment import Adjustment

from app.routers.venue_common import (
    _NOTIFICATION_JOB_MAX_ATTEMPTS,
    _NOTIFICATION_JOB_RETRY_MINUTES,
    _NOTIFICATION_JOB_STALE_MINUTES,
    _NOTIFICATION_JOB_STATUS_FAILED,
    _NOTIFICATION_JOB_STATUS_PENDING,
    _NOTIFICATION_JOB_STATUS_PROCESSING,
    _NOTIFICATION_JOB_STATUS_SENT,
    _NOTIFICATION_JOB_TYPE_ADJUSTMENT_ASSIGNED,
    _NOTIFICATION_JOB_TYPE_ADJUSTMENT_DISPUTE_EVENT,
    _NOTIFICATION_JOB_TYPE_DAY_ECONOMICS_SUMMARY,
    _NOTIFICATION_JOB_TYPE_SALARY_DAY_BREAKDOWN,
    _NOTIFICATION_JOB_TYPE_SOFT_ALERTS,
    _NOTIFICATION_JOB_TYPE_SHIFT_COMMENT,
    _NOTIFICATION_JOB_TYPE_SHIFT_SWAP,
    log,
)

from app.routers.venue_adjustment_notifications import (
    _send_adjustment_assigned_notification,
    _send_adjustment_dispute_event_notifications,
)
from app.routers.venue_shift_notifications import _send_shift_comment_notifications
from app.routers.venue_shift_swap_notifications import _send_shift_swap_notifications
from app.routers.venue_notification_common import (
    NotificationDeliveryError,
    _build_owner_day_economics_link,
    _build_staff_salary_day_link,
    _should_notify_user,
    _venue_name,
)


def _can_receive_day_economics_summary(db: Session, *, venue_id: int, user: User) -> bool:
    if user is None:
        return False
    if not _should_notify_user(user, "day_economics"):
        return False
    if not getattr(user, "tg_user_id", None):
        return False
    return _has_revenue_view_access(db, venue_id=venue_id, user=user) and _is_report_viewer(
        db, venue_id=venue_id, user=user
    )


def _can_receive_soft_alerts(db: Session, *, venue_id: int, user: User) -> bool:
    if user is None:
        return False
    if not _should_notify_user(user, "soft_alerts"):
        return False
    if not getattr(user, "tg_user_id", None):
        return False
    return _has_revenue_view_access(db, venue_id=venue_id, user=user) and _is_report_viewer(
        db, venue_id=venue_id, user=user
    )


def _notification_detail_level(detail_level: str | None) -> str:
    level = str(detail_level or "standard").strip().lower()
    if level not in {"short", "standard", "detailed"}:
        return "standard"
    return level


def _normalize_notification_shift_slot(value: str | None) -> str:
    slot = str(value or "TOTAL").strip().upper()
    return slot if slot in {"DAY", "NIGHT"} else "TOTAL"


def _notification_shift_slot_label(value: str | None, *, locale: str = "ru") -> str:
    slot = _normalize_notification_shift_slot(value)
    if slot == "DAY":
        return localized(locale, ru="День", en="Day")
    if slot == "NIGHT":
        return localized(locale, ru="Ночь", en="Night")
    return localized(locale, ru="Итого за дату", en="Full day")


_EN_ALERT_COPY = {
    "REPORT_NOT_CLOSED": ("Day is not closed", "The day figures may be incomplete until the report is closed."),
    "DRAFT_EXPENSES": ("Draft expenses found", "Draft expenses are not included in the final figures yet."),
    "SLOT_COSTS_NOT_ALLOCATED": (
        "Expenses and payroll are shown under Full day",
        "Current expenses, adjustments, and payroll are not allocated between day and night shifts.",
    ),
    "LOSS_DAY": ("The day is operating at a loss", "Actual profit for the day is negative."),
    "EXPENSE_RATIO_HIGH": (
        "Expenses are above the limit",
        "The expense-to-revenue ratio exceeds the configured limit.",
    ),
    "PAYROLL_RATIO_HIGH": ("Payroll is above the limit", "The payroll-to-revenue ratio exceeds the configured limit."),
    "REVENUE_PER_ASSIGNED_LOW": ("Low revenue per employee", "Revenue per employee is below the configured target."),
    "SHIFT_COVERAGE_LOW": ("Low shift coverage", "Shift coverage is below the configured target."),
    "PROFIT_BELOW_TARGET": (
        "Profit is below the threshold",
        "Actual profit is below the configured minimum threshold.",
    ),
    "REVENUE_PLAN_MISSED": ("Revenue plan missed", "Actual revenue is below the daily plan."),
    "PROFIT_PLAN_MISSED": ("Profit plan missed", "Actual profit is below the daily plan."),
}


def _localized_alert_copy(alert: dict, *, locale: str) -> tuple[str, str]:
    title = str((alert or {}).get("title") or localized(locale, ru="Алерт", en="Alert")).strip()
    detail = str((alert or {}).get("detail") or "").strip()
    if locale != "en":
        return title, detail
    return _EN_ALERT_COPY.get(str((alert or {}).get("code") or "").strip().upper(), (title, detail))


def _notification_event_token(value: str | None) -> str:
    raw = str(value or "legacy").strip() or "legacy"
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def _soft_alert_signature(alerts: list[dict]) -> str:
    normalized: list[str] = []
    for item in alerts or []:
        code = str((item or {}).get("code") or "").strip().upper()
        severity = str((item or {}).get("severity") or "").strip().upper()
        if code:
            normalized.append(f"{severity}:{code}")
    normalized.sort()
    return (
        hashlib.sha1("|".join(normalized).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
        if normalized
        else "none"
    )


def _select_soft_alerts_for_notification(economics: dict) -> list[dict]:
    alerts = economics.get("alerts") or []
    selected: list[dict] = []
    seen_codes: set[str] = set()
    for item in alerts:
        severity = str((item or {}).get("severity") or "").strip().upper()
        code = str((item or {}).get("code") or "").strip().upper()
        if severity not in {"WARN", "CRITICAL"}:
            continue
        if not code or code in seen_codes:
            continue
        selected.append(item)
        seen_codes.add(code)
    selected.sort(
        key=lambda item: (
            0 if str((item or {}).get("severity") or "").strip().upper() == "CRITICAL" else 1,
            str((item or {}).get("code") or ""),
        )
    )
    return selected


def _build_soft_alerts_notification_text(
    *,
    venue_name: str,
    target_date: date,
    economics: dict,
    alerts: list[dict],
    detail_level: str,
    shift_slot: str = "TOTAL",
    locale: str = "ru",
) -> str:
    level = _notification_detail_level(detail_level)
    summary = economics.get("summary") or {}
    metrics = economics.get("metrics") or {}
    rules = economics.get("rules") or {}
    profit_available = bool(summary.get("slot_profit_available", True))

    lines: list[str] = [
        f"⚠️ {localized(locale, ru='Мягкие алерты', en='Alerts')} · {_format_notification_date(target_date, locale=locale)}",
        f"{localized(locale, ru='Заведение', en='Venue')}: {venue_name}",
        f"{localized(locale, ru='Слот', en='Shift')}: {_notification_shift_slot_label(shift_slot, locale=locale)}",
    ]
    if level in {"standard", "detailed"}:
        lines.append(
            f"{localized(locale, ru='Выручка', en='Revenue')}: {_fmt_money_minor(summary.get('revenue_minor'))}"
        )
        if profit_available:
            lines.extend(
                [
                    f"{localized(locale, ru='Расходы', en='Expenses')}: {_fmt_money_minor(summary.get('expense_minor'))} ({_fmt_percent_bps(metrics.get('expense_ratio_bps'))})",
                    f"{localized(locale, ru='ФОТ', en='Payroll')}: {_fmt_money_minor(summary.get('payroll_minor'))} ({_fmt_percent_bps(metrics.get('payroll_ratio_bps'))})",
                    f"{localized(locale, ru='Прибыль', en='Profit')}: {_fmt_money_minor(summary.get('profit_minor'))}",
                ]
            )
        else:
            lines.append(
                localized(
                    locale,
                    ru="Расходы, ФОТ и прибыль: доступны только в «Итого»",
                    en="Expenses, payroll, and profit are available only under Full day",
                )
            )

    lines.append(localized(locale, ru="Что требует внимания:", en="Needs attention:"))
    visible = alerts if level == "detailed" else alerts[:4]
    for alert in visible:
        severity = str((alert or {}).get("severity") or "").strip().upper()
        title, detail = _localized_alert_copy(alert, locale=locale)
        icon = "🔴" if severity == "CRITICAL" else "🟠"
        lines.append(f"{icon} {title}")
        if level in {"standard", "detailed"} and detail:
            lines.append(f"  {detail}")
    extra = max(len(alerts) - len(visible), 0)
    if extra:
        lines.append(localized(locale, ru=f"• ещё {extra}", en=f"• {extra} more"))

    if level == "detailed":
        max_payroll_ratio_bps = rules.get("max_payroll_ratio_bps")
        max_expense_ratio_bps = rules.get("max_expense_ratio_bps")
        min_coverage_bps = rules.get("min_assigned_shift_coverage_bps")
        policy_parts: list[str] = []
        if profit_available and max_payroll_ratio_bps is not None:
            policy_parts.append(
                f"{localized(locale, ru='ФОТ', en='payroll')} ≤ {_fmt_percent_bps(max_payroll_ratio_bps)}"
            )
        if profit_available and max_expense_ratio_bps is not None:
            policy_parts.append(
                f"{localized(locale, ru='расходы', en='expenses')} ≤ {_fmt_percent_bps(max_expense_ratio_bps)}"
            )
        if min_coverage_bps is not None:
            policy_parts.append(
                f"{localized(locale, ru='покрытие смен', en='shift coverage')} ≥ {_fmt_percent_bps(min_coverage_bps)}"
            )
        if bool(rules.get("warn_on_draft_expenses", True)):
            policy_parts.append(localized(locale, ru="черновые расходы учитываются", en="draft expenses are included"))
        if policy_parts:
            lines.append(localized(locale, ru="Пороговые правила: ", en="Threshold rules: ") + " · ".join(policy_parts))

    return "\n".join(lines)


def _fmt_money_minor(value_minor: int | None) -> str:
    minor = int(value_minor or 0)
    sign = "-" if minor < 0 else ""
    abs_minor = abs(minor)
    if abs_minor % 100 == 0:
        rub = abs_minor // 100
        return f"{sign}{rub:,} ₽".replace(",", " ")
    rub = abs_minor / 100.0
    return f"{sign}{rub:,.2f} ₽".replace(",", " ")


def _fmt_percent_bps(value_bps: int | None) -> str:
    if value_bps is None:
        return "—"
    value = int(value_bps) / 100.0
    rendered = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{rendered}%"


def _format_notification_date(value: date, *, locale: str = "ru") -> str:
    if locale == "en":
        return value.strftime("%B %-d, %Y")
    months = {
        1: "января",
        2: "февраля",
        3: "марта",
        4: "апреля",
        5: "мая",
        6: "июня",
        7: "июля",
        8: "августа",
        9: "сентября",
        10: "октября",
        11: "ноября",
        12: "декабря",
    }
    return f"{value.day} {months.get(value.month, value.strftime('%m'))} {value.year}"


def _truncate_breakdown_items(items: list[dict], *, limit: int) -> list[dict]:
    return list(items[: max(int(limit), 0)])


def _render_breakdown(title: str, items: list[dict], *, limit: int, locale: str = "ru") -> list[str]:
    if not items:
        return [f"{title}: —"]
    visible = _truncate_breakdown_items(items, limit=limit)
    lines = [f"{title}:"]
    for item in visible:
        lines.append(
            f"• {item.get('title') or localized(locale, ru='Без названия', en='Untitled')} — {_fmt_money_minor(int(item.get('amount_minor') or 0))}"
        )
    extra = max(len(items) - len(visible), 0)
    if extra:
        lines.append(localized(locale, ru=f"• ещё {extra}", en=f"• {extra} more"))
    return lines


def _build_day_economics_notification_text(
    *,
    venue_name: str,
    target_date: date,
    economics: dict,
    detail_level: str,
    shift_slot: str = "TOTAL",
    locale: str = "ru",
) -> str:
    level = _notification_detail_level(detail_level)

    summary = economics.get("summary") or {}
    payment_breakdown = economics.get("payment_revenue_breakdown") or []
    department_breakdown = economics.get("department_revenue_breakdown") or []
    profit_available = bool(summary.get("slot_profit_available", True))

    lines: list[str] = [
        f"📊 {localized(locale, ru='Экономика дня', en='Daily economics')} · {_format_notification_date(target_date, locale=locale)}",
        f"{localized(locale, ru='Заведение', en='Venue')}: {venue_name}",
        f"{localized(locale, ru='Слот', en='Shift')}: {_notification_shift_slot_label(shift_slot, locale=locale)}",
        f"{localized(locale, ru='Выручка', en='Revenue')}: {_fmt_money_minor(summary.get('revenue_minor'))}",
    ]
    if profit_available:
        lines.extend(
            [
                f"{localized(locale, ru='ФОТ', en='Payroll')}: {_fmt_money_minor(summary.get('payroll_minor'))} ({_fmt_percent_bps(summary.get('payroll_ratio_bps'))})",
                f"{localized(locale, ru='Прибыль', en='Profit')}: {_fmt_money_minor(summary.get('profit_minor'))}",
            ]
        )
    else:
        lines.append(
            localized(
                locale,
                ru="Расходы, ФОТ и прибыль: доступны только в «Итого»",
                en="Expenses, payroll, and profit are available only under Full day",
            )
        )

    draft_total_minor = int(summary.get("draft_expense_total_minor") or 0)
    draft_count = int(summary.get("draft_expense_count") or 0)

    if level in {"standard", "detailed"}:
        lines.extend(
            _render_breakdown(
                localized(locale, ru="По оплатам", en="By payment method"),
                payment_breakdown,
                limit=4 if level == "standard" else 8,
                locale=locale,
            )
        )
        lines.extend(
            _render_breakdown(
                localized(locale, ru="По департаментам", en="By department"),
                department_breakdown,
                limit=4 if level == "standard" else 8,
                locale=locale,
            )
        )
        if profit_available:
            lines.append(
                f"{localized(locale, ru='Разовые расходы', en='One-time expenses')}: {_fmt_money_minor(summary.get('point_expense_minor'))}"
            )
            lines.append(
                f"{localized(locale, ru='Регулярные расходы', en='Recurring expenses')}: {_fmt_money_minor(summary.get('recurring_expense_minor'))}"
            )
            if draft_count > 0 or draft_total_minor > 0:
                lines.append(
                    f"{localized(locale, ru='Черновые расходы', en='Draft expenses')}: {_fmt_money_minor(draft_total_minor)} ({draft_count} {localized(locale, ru='шт.', en='items')})"
                )
            else:
                lines.append(localized(locale, ru="Черновые расходы: —", en="Draft expenses: —"))

    if level == "detailed":
        point_expenses = summary.get("point_expenses") or []
        recurring_expenses = summary.get("recurring_expenses") or []
        if point_expenses:
            lines.extend(
                _render_breakdown(
                    localized(locale, ru="Детализация разовых расходов", en="One-time expense details"),
                    point_expenses,
                    limit=6,
                    locale=locale,
                )
            )
        if recurring_expenses:
            lines.extend(
                _render_breakdown(
                    localized(locale, ru="Детализация регулярных расходов", en="Recurring expense details"),
                    recurring_expenses,
                    limit=6,
                    locale=locale,
                )
            )

    return "\n".join(lines)


def _build_salary_day_breakdown_text(
    *,
    venue_name: str,
    target_date: date,
    breakdown: dict,
    detail_level: str,
    shift_slot: str = "TOTAL",
    locale: str = "ru",
) -> str:
    level = _notification_detail_level(detail_level)

    summary = breakdown.get("summary") or {}
    context = breakdown.get("context") or {}
    items = breakdown.get("items") or []
    state = str(breakdown.get("state") or "ready")

    lines: list[str] = [
        f"💸 {localized(locale, ru='Начисление за день', en='Daily earnings')} · {_format_notification_date(target_date, locale=locale)}",
        f"{localized(locale, ru='Заведение', en='Venue')}: {venue_name}",
        f"{localized(locale, ru='Слот', en='Shift')}: {_notification_shift_slot_label(shift_slot, locale=locale)}",
        f"{localized(locale, ru='Итого начисление', en='Total earnings')}: {_fmt_money_minor(summary.get('total_minor'))}",
    ]

    if state == "partial":
        lines.append(
            localized(
                locale,
                ru="Данные частичные: часть начислений ещё в пересчёте",
                en="Partial data: some earnings are still being recalculated",
            )
        )
    elif state == "no_payroll":
        lines.append(
            localized(
                locale,
                ru="Начисление ещё не рассчитано payroll, ниже только доступные данные",
                en="Payroll has not been calculated yet; only currently available data is shown",
            )
        )
    elif state == "empty":
        lines.append(
            localized(locale, ru="За этот день начислений не найдено", en="No earnings were found for this day")
        )

    if level in {"standard", "detailed"}:
        lines.append(
            f"{localized(locale, ru='Основное начисление', en='Base earnings')}: {_fmt_money_minor(summary.get('earnings_minor'))}"
        )
        if int(summary.get("tips_minor") or 0):
            lines.append(f"{localized(locale, ru='Чаевые', en='Tips')}: {_fmt_money_minor(summary.get('tips_minor'))}")
        if int(summary.get("bonuses_minor") or 0):
            lines.append(
                f"{localized(locale, ru='Премии', en='Bonuses')}: {_fmt_money_minor(summary.get('bonuses_minor'))}"
            )
        if int(summary.get("penalties_minor") or 0):
            lines.append(
                f"{localized(locale, ru='Штрафы/списания', en='Penalties/write-offs')}: {_fmt_money_minor(-int(summary.get('penalties_minor') or 0))}"
            )
        hours_total = context.get("hours_total")
        shifts_count = context.get("shifts_count")
        if hours_total not in (None, "") or shifts_count not in (None, ""):
            lines.append(
                f"{localized(locale, ru='Смен', en='Shifts')}: {int(shifts_count or 0)} · {localized(locale, ru='Часы', en='Hours')}: {hours_total or 0}"
            )

    if items and level in {"standard", "detailed"}:
        visible = items[:4] if level == "standard" else items[:8]
        lines.append(localized(locale, ru="Из чего сложилось:", en="Breakdown:"))
        for item in visible:
            lines.append(
                f"• {item.get('title') or localized(locale, ru='Компонент', en='Component')} — {_fmt_money_minor(int(item.get('amount_minor') or 0))}"
            )
            if level == "detailed":
                base_text = str(item.get("base_text") or "").strip()
                formula_text = str(item.get("formula_text") or "").strip()
                if base_text:
                    lines.append(f"  {localized(locale, ru='База', en='Base')}: {base_text}")
                if formula_text:
                    lines.append(f"  {localized(locale, ru='Формула', en='Formula')}: {formula_text}")
        extra = max(len(items) - len(visible), 0)
        if extra:
            lines.append(localized(locale, ru=f"• ещё {extra}", en=f"• {extra} more"))

    return "\n".join(lines)


def _collect_salary_day_notification_user_ids(
    db: Session,
    *,
    venue_id: int,
    target_date: date,
    shift_slot: str = "TOTAL",
) -> list[int]:
    slot = _normalize_notification_shift_slot(shift_slot)
    user_ids: set[int] = set()

    assignment_stmt = (
        select(ShiftAssignment.member_user_id)
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .where(
            Shift.venue_id == int(venue_id),
            Shift.date == target_date,
            Shift.is_active.is_(True),
            ShiftAssignment.member_user_id.is_not(None),
        )
    )
    if slot in {"DAY", "NIGHT"}:
        assignment_stmt = assignment_stmt.where(Shift.shift_slot == slot)
    assignment_rows = db.execute(assignment_stmt).all()
    for (member_user_id,) in assignment_rows:
        if member_user_id is not None:
            user_ids.add(int(member_user_id))

    if slot == "TOTAL":
        adjustment_rows = db.execute(
            select(Adjustment.member_user_id).where(
                Adjustment.venue_id == int(venue_id),
                Adjustment.date == target_date,
                Adjustment.is_active.is_(True),
                Adjustment.member_user_id.is_not(None),
            )
        ).all()
        for (member_user_id,) in adjustment_rows:
            if member_user_id is not None:
                user_ids.add(int(member_user_id))

    tip_stmt = (
        select(DailyReportTipAllocation.user_id)
        .join(DailyReport, DailyReport.id == DailyReportTipAllocation.report_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == "CLOSED",
            DailyReport.date == target_date,
            DailyReportTipAllocation.user_id.is_not(None),
        )
    )
    if slot in {"DAY", "NIGHT"}:
        tip_stmt = tip_stmt.where(DailyReport.shift_slot == slot)
    tip_rows = db.execute(tip_stmt).all()
    for (user_id,) in tip_rows:
        if user_id is not None:
            user_ids.add(int(user_id))

    return sorted(user_ids)


def _enqueue_salary_day_breakdown_job(
    db: Session,
    *,
    venue_id: int,
    target_date: date,
    shift_slot: str = "TOTAL",
    event_key: str | None = None,
) -> NotificationJob:
    slot = _normalize_notification_shift_slot(shift_slot)
    event_token = _notification_event_token(event_key)
    idempotency_key = f"job:salary_day_breakdown:{int(venue_id)}:{target_date.isoformat()}:{slot}:{event_token}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_SALARY_DAY_BREAKDOWN,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_(
                [_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING, _NOTIFICATION_JOB_STATUS_SENT]
            ),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_SALARY_DAY_BREAKDOWN,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps(
            {
                "venue_id": int(venue_id),
                "target_date": target_date.isoformat(),
                "shift_slot": slot,
                "event_key": str(event_key or "legacy"),
            },
            ensure_ascii=False,
        ),
        attempts=0,
        max_attempts=max(int(_NOTIFICATION_JOB_MAX_ATTEMPTS), 1),
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _send_salary_day_breakdown_notifications(
    db: Session,
    *,
    venue_id: int,
    target_date: date,
    shift_slot: str = "TOTAL",
    event_key: str | None = None,
) -> None:
    slot = _normalize_notification_shift_slot(shift_slot)
    event_token = _notification_event_token(event_key)
    legacy_payload = event_key is None and slot == "TOTAL"
    user_ids = _collect_salary_day_notification_user_ids(
        db,
        venue_id=venue_id,
        target_date=target_date,
        shift_slot=slot,
    )
    if not user_ids:
        return

    users = db.execute(select(User).where(User.id.in_(user_ids)).order_by(User.id.asc())).scalars().all()
    if not users:
        return

    venue_name = _venue_name(db, venue_id)
    link = _build_staff_salary_day_link(
        venue_id=venue_id,
        target_date=target_date,
        shift_slot=slot,
    )
    seen_tg_user_ids: set[int] = set()
    had_delivery_failure = False
    had_retryable_error = False

    for recipient in users:
        if not _should_notify_user(recipient, "salary"):
            continue
        if not getattr(recipient, "tg_user_id", None):
            continue
        active_member = db.execute(
            select(VenueMember.id).where(
                VenueMember.venue_id == int(venue_id),
                VenueMember.user_id == int(recipient.id),
                VenueMember.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if active_member is None and recipient.system_role not in {"SUPER_ADMIN", "MODERATOR"}:
            continue
        chat_id = int(recipient.tg_user_id)
        if chat_id in seen_tg_user_ids:
            continue
        seen_tg_user_ids.add(chat_id)

        dedupe_scope = f"tg:{chat_id}"
        if legacy_payload:
            idempotency_key = f"salary_day_breakdown:{int(venue_id)}:{target_date.isoformat()}:{dedupe_scope}"
        else:
            idempotency_key = (
                f"salary_day_breakdown:{int(venue_id)}:{target_date.isoformat()}:{slot}:{event_token}:{dedupe_scope}"
            )
        lock_notification_idempotency_key(db, idempotency_key)
        if notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("pending", "sent")):
            continue

        breakdown = build_member_day_breakdown(
            db,
            member_user_id=int(recipient.id),
            venue_id=int(venue_id),
            target_date=target_date,
            shift_slot=slot,
        )
        items = breakdown.get("items") or []
        total_minor = int((breakdown.get("summary") or {}).get("total_minor") or 0)
        if not items and total_minor == 0:
            continue

        detail_level = getattr(recipient, "notification_detail_level", "standard")
        locale = user_locale(recipient)
        text = _build_salary_day_breakdown_text(
            venue_name=venue_name,
            target_date=target_date,
            breakdown=breakdown,
            detail_level=detail_level,
            shift_slot=slot,
            locale=locale,
        )

        sent_at = datetime.utcnow().replace(tzinfo=timezone.utc)
        pending_log = log_notification_attempt(
            db,
            notification_type="salary_day_breakdown",
            status="pending",
            user_id=int(recipient.id),
            venue_id=int(venue_id),
            planned_at=sent_at,
            idempotency_key=idempotency_key,
            payload_preview=text[:2000],
        )
        db.flush()
        db.commit()

        result = tg_notify.notify_result(
            chat_id=chat_id,
            text=text,
            url=link,
            button_text=localized(locale, ru="Открыть начисления", en="Open earnings"),
        )
        ok = bool(result.get("ok"))
        retryable = bool(result.get("retryable"))
        error_text = str(result.get("error") or "notify() returned False")[:2000] if not ok else None
        try:
            pending_log.status = "sent" if ok else "failed"
            pending_log.sent_at = sent_at if ok else None
            pending_log.error_text = error_text
            db.add(pending_log)
            db.commit()
        except Exception:
            db.rollback()
            raise

        had_delivery_failure = had_delivery_failure or not ok
        had_retryable_error = had_retryable_error or (retryable and not ok)

    db.commit()
    if had_delivery_failure:
        raise NotificationDeliveryError(
            "salary day breakdown delivery failed",
            retryable=had_retryable_error,
        )


def _enqueue_soft_alerts_job(
    db: Session,
    *,
    venue_id: int,
    target_date: date,
    shift_slot: str = "TOTAL",
    event_key: str | None = None,
) -> NotificationJob:
    slot = _normalize_notification_shift_slot(shift_slot)
    event_token = _notification_event_token(event_key)
    idempotency_key = f"job:soft_alerts:{int(venue_id)}:{target_date.isoformat()}:{slot}:{event_token}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_SOFT_ALERTS,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_(
                [_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING, _NOTIFICATION_JOB_STATUS_SENT]
            ),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_SOFT_ALERTS,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps(
            {
                "venue_id": int(venue_id),
                "target_date": target_date.isoformat(),
                "shift_slot": slot,
                "event_key": str(event_key or "legacy"),
            },
            ensure_ascii=False,
        ),
        attempts=0,
        max_attempts=max(int(_NOTIFICATION_JOB_MAX_ATTEMPTS), 1),
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _send_soft_alert_notifications(
    db: Session,
    *,
    venue_id: int,
    target_date: date,
    shift_slot: str = "TOTAL",
    event_key: str | None = None,
) -> None:
    slot = _normalize_notification_shift_slot(shift_slot)
    event_token = _notification_event_token(event_key)
    legacy_payload = event_key is None and slot == "TOTAL"
    members = (
        db.execute(
            select(User)
            .join(VenueMember, VenueMember.user_id == User.id)
            .where(
                VenueMember.venue_id == int(venue_id),
                VenueMember.is_active.is_(True),
            )
            .order_by(User.id.asc())
        )
        .scalars()
        .all()
    )
    if not members:
        return

    economics = get_day_economics(
        db=db,
        venue_id=venue_id,
        target_date=target_date,
        shift_slot=slot,
    )
    alerts = _select_soft_alerts_for_notification(economics)
    if not alerts:
        return

    recipients: list[User] = []
    seen_recipient_ids: set[int] = set()
    seen_tg_user_ids: set[int] = set()
    for user in members:
        if not _can_receive_soft_alerts(db, venue_id=venue_id, user=user):
            continue
        user_id = int(user.id)
        tg_user_id = int(user.tg_user_id) if getattr(user, "tg_user_id", None) is not None else None
        if user_id in seen_recipient_ids:
            continue
        if tg_user_id is not None and tg_user_id in seen_tg_user_ids:
            continue
        recipients.append(user)
        seen_recipient_ids.add(user_id)
        if tg_user_id is not None:
            seen_tg_user_ids.add(tg_user_id)
    if not recipients:
        return

    venue_name = _venue_name(db, venue_id)
    link = _build_owner_day_economics_link(
        venue_id=venue_id,
        target_date=target_date,
        shift_slot=slot,
    )
    sent_at = datetime.utcnow().replace(tzinfo=timezone.utc)
    alert_signature = _soft_alert_signature(alerts)
    had_delivery_failure = False
    had_retryable_error = False

    for recipient in recipients:
        chat_id = int(recipient.tg_user_id)
        dedupe_scope = (
            f"tg:{chat_id}" if getattr(recipient, "tg_user_id", None) is not None else f"user:{int(recipient.id)}"
        )
        if legacy_payload:
            idempotency_key = f"soft_alerts:{int(venue_id)}:{target_date.isoformat()}:{dedupe_scope}:{alert_signature}"
        else:
            idempotency_key = (
                f"soft_alerts:{int(venue_id)}:{target_date.isoformat()}:{slot}:"
                f"{event_token}:{dedupe_scope}:{alert_signature}"
            )
        lock_notification_idempotency_key(db, idempotency_key)
        if notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("pending", "sent")):
            continue

        detail_level = getattr(recipient, "notification_detail_level", "standard")
        locale = user_locale(recipient)
        text = _build_soft_alerts_notification_text(
            venue_name=venue_name,
            target_date=target_date,
            economics=economics,
            alerts=alerts,
            detail_level=detail_level,
            shift_slot=slot,
            locale=locale,
        )

        pending_log = log_notification_attempt(
            db,
            notification_type="soft_alerts",
            status="pending",
            user_id=int(recipient.id),
            venue_id=int(venue_id),
            planned_at=sent_at,
            idempotency_key=idempotency_key,
            payload_preview=text[:2000],
        )
        db.flush()
        db.commit()

        result = tg_notify.notify_result(
            chat_id=chat_id,
            text=text,
            url=link,
            button_text=localized(locale, ru="Открыть экономику дня", en="Open daily economics"),
        )
        ok = bool(result.get("ok"))
        retryable = bool(result.get("retryable"))
        error_text = str(result.get("error") or "notify() returned False")[:2000] if not ok else None
        try:
            pending_log.status = "sent" if ok else "failed"
            pending_log.sent_at = sent_at if ok else None
            pending_log.error_text = error_text
            db.add(pending_log)
            db.commit()
        except Exception:
            db.rollback()
            raise

        had_delivery_failure = had_delivery_failure or not ok
        had_retryable_error = had_retryable_error or (retryable and not ok)

    db.commit()
    if had_delivery_failure:
        raise NotificationDeliveryError(
            "soft alerts delivery failed",
            retryable=had_retryable_error,
        )


def _enqueue_day_economics_summary_job(
    db: Session,
    *,
    venue_id: int,
    target_date: date,
    shift_slot: str = "TOTAL",
    event_key: str | None = None,
) -> NotificationJob:
    slot = _normalize_notification_shift_slot(shift_slot)
    event_token = _notification_event_token(event_key)
    idempotency_key = f"job:day_economics_summary:{int(venue_id)}:{target_date.isoformat()}:{slot}:{event_token}"
    existing = db.execute(
        select(NotificationJob)
        .where(
            NotificationJob.job_type == _NOTIFICATION_JOB_TYPE_DAY_ECONOMICS_SUMMARY,
            NotificationJob.idempotency_key == idempotency_key,
            NotificationJob.status.in_(
                [_NOTIFICATION_JOB_STATUS_PENDING, _NOTIFICATION_JOB_STATUS_PROCESSING, _NOTIFICATION_JOB_STATUS_SENT]
            ),
        )
        .order_by(NotificationJob.id.desc())
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = NotificationJob(
        job_type=_NOTIFICATION_JOB_TYPE_DAY_ECONOMICS_SUMMARY,
        status=_NOTIFICATION_JOB_STATUS_PENDING,
        payload_json=json.dumps(
            {
                "venue_id": int(venue_id),
                "target_date": target_date.isoformat(),
                "shift_slot": slot,
                "event_key": str(event_key or "legacy"),
            },
            ensure_ascii=False,
        ),
        attempts=0,
        max_attempts=max(int(_NOTIFICATION_JOB_MAX_ATTEMPTS), 1),
        run_after=datetime.utcnow(),
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()
    return job


def _claim_notification_job(db: Session) -> NotificationJob | None:
    now = datetime.utcnow()
    stale_before = now - timedelta(minutes=max(int(_NOTIFICATION_JOB_STALE_MINUTES), 1))
    stmt = (
        select(NotificationJob)
        .where(
            sa.or_(
                sa.and_(
                    NotificationJob.status == _NOTIFICATION_JOB_STATUS_PENDING,
                    NotificationJob.run_after <= now,
                ),
                sa.and_(
                    NotificationJob.status == _NOTIFICATION_JOB_STATUS_PROCESSING,
                    NotificationJob.locked_at.is_not(None),
                    NotificationJob.locked_at <= stale_before,
                ),
            )
        )
        .order_by(NotificationJob.run_after.asc(), NotificationJob.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        return None
    job.status = _NOTIFICATION_JOB_STATUS_PROCESSING
    job.locked_at = now
    job.attempts = int(job.attempts or 0) + 1
    job.updated_at = now
    db.flush()
    return job


def _complete_notification_job(
    db: Session,
    job: NotificationJob,
    *,
    status: str,
    last_error: str | None = None,
    retryable: bool = True,
) -> None:
    now = datetime.utcnow()
    if (
        status == _NOTIFICATION_JOB_STATUS_FAILED
        and retryable
        and int(job.attempts or 0) < int(job.max_attempts or _NOTIFICATION_JOB_MAX_ATTEMPTS)
    ):
        job.status = _NOTIFICATION_JOB_STATUS_PENDING
        job.run_after = now + timedelta(minutes=max(int(_NOTIFICATION_JOB_RETRY_MINUTES), 1))
        job.locked_at = None
        job.last_error = last_error or None
        job.updated_at = now
    else:
        job.status = status
        job.processed_at = now
        job.locked_at = None
        job.last_error = last_error or None
        job.updated_at = now


def process_pending_notification_jobs_once(limit: int = 10) -> int:
    processed = 0
    hard_limit = max(int(limit or 0), 0)
    if hard_limit <= 0:
        return 0

    while processed < hard_limit:
        with SessionLocal() as db:
            job = _claim_notification_job(db)
            if job is None:
                db.rollback()
                break
            job_id = int(job.id)
            db.commit()

        with SessionLocal() as db:
            job = db.get(NotificationJob, job_id)
            if job is None:
                processed += 1
                continue
            try:
                payload = json.loads(job.payload_json or "{}")
                if job.job_type == _NOTIFICATION_JOB_TYPE_DAY_ECONOMICS_SUMMARY:
                    _send_day_economics_summary_notifications(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        target_date=date.fromisoformat(str(payload.get("target_date"))),
                        shift_slot=str(payload.get("shift_slot") or "TOTAL"),
                        event_key=payload.get("event_key"),
                    )
                elif job.job_type == _NOTIFICATION_JOB_TYPE_SALARY_DAY_BREAKDOWN:
                    _send_salary_day_breakdown_notifications(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        target_date=date.fromisoformat(str(payload.get("target_date"))),
                        shift_slot=str(payload.get("shift_slot") or "TOTAL"),
                        event_key=payload.get("event_key"),
                    )
                elif job.job_type == _NOTIFICATION_JOB_TYPE_SOFT_ALERTS:
                    _send_soft_alert_notifications(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        target_date=date.fromisoformat(str(payload.get("target_date"))),
                        shift_slot=str(payload.get("shift_slot") or "TOTAL"),
                        event_key=payload.get("event_key"),
                    )
                elif job.job_type == _NOTIFICATION_JOB_TYPE_ADJUSTMENT_ASSIGNED:
                    _send_adjustment_assigned_notification(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        adjustment_id=int(payload.get("adjustment_id")),
                    )
                elif job.job_type == _NOTIFICATION_JOB_TYPE_ADJUSTMENT_DISPUTE_EVENT:
                    _send_adjustment_dispute_event_notifications(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        dispute_id=int(payload.get("dispute_id")),
                        comment_id=int(payload.get("comment_id")),
                        event_kind=str(payload.get("event_kind") or "comment"),
                    )
                elif job.job_type == _NOTIFICATION_JOB_TYPE_SHIFT_COMMENT:
                    _send_shift_comment_notifications(
                        db,
                        venue_id=int(payload.get("venue_id")),
                        comment_id=int(payload.get("comment_id")),
                    )
                elif job.job_type == _NOTIFICATION_JOB_TYPE_SHIFT_SWAP:
                    _send_shift_swap_notifications(
                        db,
                        request_id=int(payload.get("request_id")),
                        event_kind=str(payload.get("event_kind") or ""),
                    )
                else:
                    raise ValueError(f"Unsupported notification job type: {job.job_type}")
                _complete_notification_job(db, job, status=_NOTIFICATION_JOB_STATUS_SENT)
                db.commit()
            except Exception as exc:
                db.rollback()
                with SessionLocal() as retry_db:
                    retry_job = retry_db.get(NotificationJob, job_id)
                    if retry_job is not None:
                        _complete_notification_job(
                            retry_db,
                            retry_job,
                            status=_NOTIFICATION_JOB_STATUS_FAILED,
                            last_error=str(exc)[:2000],
                            retryable=bool(getattr(exc, "retryable", True)),
                        )
                        retry_db.commit()
                log.exception("notification job failed id=%s type=%s: %s", job_id, getattr(job, "job_type", None), exc)
            processed += 1

    return processed


def _send_day_economics_summary_notifications(
    db: Session,
    *,
    venue_id: int,
    target_date: date,
    shift_slot: str = "TOTAL",
    event_key: str | None = None,
) -> None:
    slot = _normalize_notification_shift_slot(shift_slot)
    event_token = _notification_event_token(event_key)
    legacy_payload = event_key is None and slot == "TOTAL"
    members = (
        db.execute(
            select(User)
            .join(VenueMember, VenueMember.user_id == User.id)
            .where(
                VenueMember.venue_id == int(venue_id),
                VenueMember.is_active.is_(True),
            )
            .order_by(User.id.asc())
        )
        .scalars()
        .all()
    )
    if not members:
        return

    recipients: list[User] = []
    seen_recipient_ids: set[int] = set()
    seen_tg_user_ids: set[int] = set()
    for user in members:
        if not _can_receive_day_economics_summary(db, venue_id=venue_id, user=user):
            continue
        user_id = int(user.id)
        tg_user_id = int(user.tg_user_id) if getattr(user, "tg_user_id", None) is not None else None
        if user_id in seen_recipient_ids:
            continue
        if tg_user_id is not None and tg_user_id in seen_tg_user_ids:
            continue
        recipients.append(user)
        seen_recipient_ids.add(user_id)
        if tg_user_id is not None:
            seen_tg_user_ids.add(tg_user_id)
    if not recipients:
        return

    economics = get_day_economics(
        db=db,
        venue_id=venue_id,
        target_date=target_date,
        shift_slot=slot,
    )
    venue_name = _venue_name(db, venue_id)
    link = _build_owner_day_economics_link(
        venue_id=venue_id,
        target_date=target_date,
        shift_slot=slot,
    )
    had_delivery_failure = False
    had_retryable_error = False

    for recipient in recipients:
        chat_id = int(recipient.tg_user_id)
        dedupe_scope = (
            f"tg:{chat_id}" if getattr(recipient, "tg_user_id", None) is not None else f"user:{int(recipient.id)}"
        )
        if legacy_payload:
            idempotency_key = f"day_economics_summary:{int(venue_id)}:{target_date.isoformat()}:{dedupe_scope}"
        else:
            idempotency_key = (
                f"day_economics_summary:{int(venue_id)}:{target_date.isoformat()}:{slot}:{event_token}:{dedupe_scope}"
            )
        lock_notification_idempotency_key(db, idempotency_key)
        if notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("pending", "sent")):
            continue

        detail_level = getattr(recipient, "notification_detail_level", "standard")
        locale = user_locale(recipient)
        text = _build_day_economics_notification_text(
            venue_name=venue_name,
            target_date=target_date,
            economics=economics,
            detail_level=detail_level,
            shift_slot=slot,
            locale=locale,
        )

        sent_at = datetime.utcnow().replace(tzinfo=timezone.utc)
        pending_log = log_notification_attempt(
            db,
            notification_type="day_economics_summary",
            status="pending",
            user_id=int(recipient.id),
            venue_id=int(venue_id),
            planned_at=sent_at,
            idempotency_key=idempotency_key,
            payload_preview=text[:2000],
        )
        db.flush()
        db.commit()

        result = tg_notify.notify_result(
            chat_id=chat_id,
            text=text,
            url=link,
            button_text=localized(locale, ru="Открыть экономику дня", en="Open daily economics"),
        )
        ok = bool(result.get("ok"))
        retryable = bool(result.get("retryable"))
        error_text = str(result.get("error") or "notify() returned False")[:2000] if not ok else None
        try:
            pending_log.status = "sent" if ok else "failed"
            pending_log.sent_at = sent_at if ok else None
            pending_log.error_text = error_text
            db.add(pending_log)
            db.commit()
        except Exception:
            db.rollback()
            raise

        had_delivery_failure = had_delivery_failure or not ok
        had_retryable_error = had_retryable_error or (retryable and not ok)

    db.commit()
    if had_delivery_failure:
        raise NotificationDeliveryError(
            "day economics summary delivery failed",
            retryable=had_retryable_error,
        )
