from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.venue_permissions import has_venue_permission
from app.core.i18n import user_locale
from app.models import Expense, PayrollPaymentSettings, User, Venue, VenueMember
from app.services import tg_notify
from app.services.notification_logs import (
    lock_notification_idempotency_key,
    log_notification_attempt,
    notification_delivery_exists,
    notification_dedupe_scope,
)
from app.services.payroll.period_summary import build_member_period_summary
from app.settings import settings

from .payments import PayrollPaymentWindow


def _format_money_minor(value: int | None) -> str:
    rubles = int(round(int(value or 0) / 100.0))
    return f"{rubles:,}".replace(",", " ") + " ₽"


def _format_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _venue_name(db: Session, *, venue_id: int) -> str:
    value = db.execute(select(Venue.name).where(Venue.id == int(venue_id))).scalar_one_or_none()
    return str(value or f"Заведение #{int(venue_id)}")


def _frontend_url(path: str, **params: object) -> str:
    query = urlencode({key: value for key, value in params.items() if value is not None})
    return f"{settings.frontend_base_url()}{path}{'?' + query if query else ''}"


def build_payroll_draft_ready_text(
    *,
    venue_name: str,
    window: PayrollPaymentWindow,
    amount_minor: int,
    locale: str = "ru",
) -> str:
    if locale == "en":
        return "\n".join(
            (
                "💼 Payroll calculated",
                venue_name,
                f"Period: {_format_date(window.period_start)}–{_format_date(window.period_end)}",
                f"Amount due: {_format_money_minor(amount_minor)}",
                f"Payment date: {_format_date(window.payment_date)}",
                "An expense draft was created. Review and confirm it before payment.",
            )
        )
    return "\n".join(
        (
            "💼 ФОТ рассчитан",
            venue_name,
            f"Период: {_format_date(window.period_start)}–{_format_date(window.period_end)}",
            f"К выплате: {_format_money_minor(amount_minor)}",
            f"Дата выплаты: {_format_date(window.payment_date)}",
            "Черновик расхода создан. Проверьте и подтвердите его перед выплатой.",
        )
    )


def build_employee_payroll_period_text(
    *,
    venue_name: str,
    window: PayrollPaymentWindow,
    summary: dict,
    locale: str = "ru",
) -> str:
    totals = summary.get("totals") or {}
    items = summary.get("items") or []
    shifts_count = sum(int(item.get("days_count") or 0) for item in items)
    if locale == "en":
        lines = [
            "💰 Pay for the period",
            venue_name,
            f"Period: {_format_date(window.period_start)}–{_format_date(window.period_end)}",
            f"Accrued: {_format_money_minor(totals.get('net_minor'))}",
            f"Shifts: {shifts_count}",
        ]
    else:
        lines = [
            "💰 Начисления за расчётный период",
            venue_name,
            f"Период: {_format_date(window.period_start)}–{_format_date(window.period_end)}",
            f"Начислено: {_format_money_minor(totals.get('net_minor'))}",
            f"Смен: {shifts_count}",
        ]
    bonuses_minor = int(totals.get("bonuses_minor") or 0)
    penalties_minor = int(totals.get("penalties_minor") or 0)
    if bonuses_minor:
        lines.append(
            f"Bonuses: +{_format_money_minor(bonuses_minor)}"
            if locale == "en"
            else f"Премии: +{_format_money_minor(bonuses_minor)}"
        )
    if penalties_minor:
        lines.append(
            f"Adjustments and deductions: −{_format_money_minor(penalties_minor)}"
            if locale == "en"
            else f"Штрафы и списания: −{_format_money_minor(penalties_minor)}"
        )
    lines.append(
        f"Payment is scheduled for {_format_date(window.payment_date)}."
        if locale == "en"
        else f"Выплата запланирована на {_format_date(window.payment_date)}."
    )
    return "\n".join(lines)


def build_due_draft_expenses_text(
    *,
    venue_name: str,
    draft_count: int,
    amount_minor: int,
    locale: str = "ru",
) -> str:
    if locale == "en":
        return "\n".join(
            (
                "🧾 Expense drafts await confirmation",
                venue_name,
                f"Expenses: {int(draft_count)}",
                f"Total: {_format_money_minor(amount_minor)}",
                "Review them and confirm the paid expenses.",
            )
        )
    return "\n".join(
        (
            "🧾 Черновые расходы ждут подтверждения",
            venue_name,
            f"Расходов: {int(draft_count)}",
            f"На сумму: {_format_money_minor(amount_minor)}",
            "Проверьте их и подтвердите оплаченные расходы.",
        )
    )


def _send_once(
    db: Session,
    *,
    notification_type: str,
    event_key: str,
    recipient: User,
    venue_id: int,
    text: str,
    url: str,
    button_text: str,
) -> bool:
    chat_id = getattr(recipient, "tg_user_id", None)
    if not chat_id or not getattr(recipient, "notify_enabled", True):
        return False
    dedupe_scope = notification_dedupe_scope(recipient)
    idempotency_key = f"{notification_type}:venue:{int(venue_id)}:{dedupe_scope}:{event_key}"
    lock_notification_idempotency_key(db, idempotency_key)
    if notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("pending", "sent")):
        return False

    now = datetime.now(timezone.utc)
    entry = log_notification_attempt(
        db,
        notification_type=notification_type,
        status="pending",
        user_id=int(recipient.id),
        venue_id=int(venue_id),
        planned_at=now,
        idempotency_key=idempotency_key,
        payload_preview=text[:1000],
    )
    db.flush()
    db.commit()
    result = tg_notify.notify_result(
        chat_id=int(chat_id),
        text=text,
        url=url,
        button_text=button_text,
    )
    entry.status = "sent" if result.get("ok") else "failed"
    entry.sent_at = datetime.now(timezone.utc) if result.get("ok") else None
    entry.error_text = str(result.get("error") or "")[:500] or None
    db.add(entry)
    db.commit()
    return bool(result.get("ok"))


def _active_venue_users(db: Session, *, venue_id: int) -> list[tuple[User, str]]:
    rows = db.execute(
        select(User, VenueMember.venue_role)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.is_active.is_(True),
            User.tg_user_id.is_not(None),
        )
        .order_by(User.id.asc())
    ).all()
    return [(row[0], str(row[1] or "").upper()) for row in rows]


def list_expense_notification_recipients(db: Session, *, venue_id: int) -> list[User]:
    recipients: list[User] = []
    for user, _venue_role in _active_venue_users(db, venue_id=venue_id):
        if has_venue_permission(
            db,
            venue_id=int(venue_id),
            user=user,
            permission_code="EXPENSE_VIEW",
        ):
            recipients.append(user)
    return recipients

def send_payroll_window_notifications(
    db: Session,
    *,
    settings_row: PayrollPaymentSettings,
    window: PayrollPaymentWindow,
    amount_minor: int,
) -> dict:
    venue_id = int(settings_row.venue_id)
    venue_name = _venue_name(db, venue_id=venue_id)
    event_key = window.payout_key_suffix
    manager_url = _frontend_url(
        "/owner-expenses.html",
        venue_id=venue_id,
        month=window.payment_date.strftime("%Y-%m"),
        statuses="DRAFT",
        expense_kind="PAYROLL",
    )
    managers_sent = 0
    for recipient in list_expense_notification_recipients(db, venue_id=venue_id):
        locale = user_locale(recipient)
        manager_text = build_payroll_draft_ready_text(
            venue_name=venue_name,
            window=window,
            amount_minor=amount_minor,
            locale=locale,
        )
        managers_sent += int(
            _send_once(
                db,
                notification_type="payroll_draft_ready",
                event_key=event_key,
                recipient=recipient,
                venue_id=venue_id,
                text=manager_text,
                url=manager_url,
                button_text="Open draft" if locale == "en" else "Открыть черновик",
            )
        )

    employees_sent = 0
    cadence = str(settings_row.cadence or "MONTHLY").upper()
    if cadence in {"WEEKLY", "MONTHLY"}:
        salary_url = _frontend_url(
            "/staff-salary.html",
            venue_id=venue_id,
            date_from=window.period_start.isoformat(),
            date_to=window.period_end.isoformat(),
        )
        for recipient, _venue_role in _active_venue_users(db, venue_id=venue_id):
            if not getattr(recipient, "notify_salary", True):
                continue
            summary = build_member_period_summary(
                db,
                member_user_id=int(recipient.id),
                period_start=window.period_start,
                period_end=window.period_end,
                venue_id=venue_id,
            )
            employee_text = build_employee_payroll_period_text(
                venue_name=venue_name,
                window=window,
                summary=summary,
                locale=user_locale(recipient),
            )
            employees_sent += int(
                _send_once(
                    db,
                    notification_type="payroll_period_summary",
                    event_key=event_key,
                    recipient=recipient,
                    venue_id=venue_id,
                    text=employee_text,
                    url=salary_url,
                    button_text="Open pay details" if user_locale(recipient) == "en" else "Открыть начисления",
                )
            )

    return {"managers_sent": managers_sent, "employees_sent": employees_sent}


def send_due_draft_expense_reminders_once(db: Session, *, today: date) -> int:
    rows = db.execute(
        select(
            Expense.venue_id,
            func.count(Expense.id),
            func.coalesce(func.sum(Expense.amount_minor), 0),
        )
        .where(
            Expense.status == "DRAFT",
            Expense.expense_date <= today,
        )
        .group_by(Expense.venue_id)
        .order_by(Expense.venue_id.asc())
    ).all()
    sent = 0
    for venue_id, draft_count, amount_minor in rows:
        venue_id_int = int(venue_id)
        venue_name = _venue_name(db, venue_id=venue_id_int)
        url = _frontend_url(
            "/owner-expenses.html",
            venue_id=venue_id_int,
            month=today.strftime("%Y-%m"),
            statuses="DRAFT",
        )
        for recipient in list_expense_notification_recipients(db, venue_id=venue_id_int):
            locale = user_locale(recipient)
            text = build_due_draft_expenses_text(
                venue_name=venue_name,
                draft_count=int(draft_count or 0),
                amount_minor=int(amount_minor or 0),
                locale=locale,
            )
            sent += int(
                _send_once(
                    db,
                    notification_type="draft_expense_reminder",
                    event_key=today.isoformat(),
                    recipient=recipient,
                    venue_id=venue_id_int,
                    text=text,
                    url=url,
                    button_text="Open drafts" if locale == "en" else "Открыть черновики",
                )
            )
    return sent
