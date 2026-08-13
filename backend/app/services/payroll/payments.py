from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Expense,
    ExpenseCategory,
    PayrollPaymentSettings,
    PayrollRun,
)
from app.services.finance.expenses import rebuild_expense_allocations_for_expense
from app.services.finance.ledger import delete_finance_entries_for_source
from app.services.finance.summary import _group_daily_payroll_allocated_minor


PAYROLL_PAYMENT_CADENCES = {"DAILY", "WEEKLY", "MONTHLY"}
DEFAULT_MONTHLY_RULES = [
    {
        "payment_day": 5,
        "period_start_day": 16,
        "period_end_day": 31,
        "period_month_offset": -1,
    },
    {
        "payment_day": 20,
        "period_start_day": 1,
        "period_end_day": 15,
        "period_month_offset": 0,
    },
]


@dataclass(frozen=True)
class PayrollPaymentWindow:
    payment_date: date
    period_start: date
    period_end: date

    @property
    def payout_key_suffix(self) -> str:
        return f"{self.payment_date.isoformat()}:{self.period_start.isoformat()}:{self.period_end.isoformat()}"


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + int(months)
    return date(month_index // 12, month_index % 12 + 1, 1)


def _clamped_date(month_start: date, day: int) -> date:
    last_day = calendar.monthrange(month_start.year, month_start.month)[1]
    return month_start.replace(day=min(max(int(day), 1), last_day))


def normalize_monthly_rules(value: list[dict] | None) -> list[dict]:
    rows = value if isinstance(value, list) else []
    normalized: list[dict] = []
    seen_payment_days: set[int] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        payment_day = int(item.get("payment_day") or 0)
        period_start_day = int(item.get("period_start_day") or 0)
        period_end_day = int(item.get("period_end_day") or 0)
        period_month_offset = int(item.get("period_month_offset") or 0)
        if not 1 <= payment_day <= 31:
            raise ValueError("День выплаты должен быть от 1 до 31")
        if payment_day in seen_payment_days:
            raise ValueError("Дни выплат не должны повторяться")
        if not 1 <= period_start_day <= 31 or not 1 <= period_end_day <= 31:
            raise ValueError("Границы периода должны быть от 1 до 31")
        if period_start_day > period_end_day:
            raise ValueError("Начало периода не может быть позже окончания")
        if period_month_offset not in {-1, 0}:
            raise ValueError("Период выплаты может относиться только к текущему или предыдущему месяцу")
        seen_payment_days.add(payment_day)
        normalized.append(
            {
                "payment_day": payment_day,
                "period_start_day": period_start_day,
                "period_end_day": period_end_day,
                "period_month_offset": period_month_offset,
            }
        )
    normalized.sort(key=lambda row: row["payment_day"])
    if not normalized:
        raise ValueError("Добавьте хотя бы один период выплаты")
    return normalized


def parse_monthly_rules(settings: PayrollPaymentSettings | None) -> list[dict]:
    if settings is None or not settings.monthly_rules_json:
        return [dict(item) for item in DEFAULT_MONTHLY_RULES]
    try:
        raw = json.loads(settings.monthly_rules_json)
    except Exception:
        raw = DEFAULT_MONTHLY_RULES
    try:
        return normalize_monthly_rules(raw)
    except ValueError:
        return [dict(item) for item in DEFAULT_MONTHLY_RULES]


def build_payment_windows(
    *,
    schedule_month: date,
    cadence: str,
    weekly_payment_weekday: int | None = None,
    monthly_rules: list[dict] | None = None,
) -> list[PayrollPaymentWindow]:
    month_start = _month_start(schedule_month)
    next_month = _add_months(month_start, 1)
    cadence_norm = str(cadence or "MONTHLY").strip().upper()
    if cadence_norm not in PAYROLL_PAYMENT_CADENCES:
        raise ValueError("Неизвестная периодичность выплаты ФОТ")

    windows: list[PayrollPaymentWindow] = []
    if cadence_norm == "DAILY":
        payment_date = month_start
        while payment_date < next_month:
            previous_day = payment_date - timedelta(days=1)
            windows.append(PayrollPaymentWindow(payment_date, previous_day, previous_day))
            payment_date += timedelta(days=1)
        return windows

    if cadence_norm == "WEEKLY":
        weekday = int(weekly_payment_weekday if weekly_payment_weekday is not None else 0)
        if not 0 <= weekday <= 6:
            raise ValueError("День недели выплаты должен быть от 0 до 6")
        payment_date = month_start
        while payment_date < next_month:
            if payment_date.weekday() == weekday:
                windows.append(
                    PayrollPaymentWindow(
                        payment_date=payment_date,
                        period_start=payment_date - timedelta(days=7),
                        period_end=payment_date - timedelta(days=1),
                    )
                )
            payment_date += timedelta(days=1)
        return windows

    for rule in normalize_monthly_rules(monthly_rules or DEFAULT_MONTHLY_RULES):
        payment_date = _clamped_date(month_start, rule["payment_day"])
        period_month = _add_months(month_start, rule["period_month_offset"])
        period_start = _clamped_date(period_month, rule["period_start_day"])
        period_end = _clamped_date(period_month, rule["period_end_day"])
        windows.append(PayrollPaymentWindow(payment_date, period_start, period_end))
    windows.sort(key=lambda item: (item.payment_date, item.period_start, item.period_end))
    periods = sorted(windows, key=lambda item: (item.period_start, item.period_end))
    for previous, current in zip(periods, periods[1:]):
        if current.period_start <= previous.period_end:
            raise ValueError("Расчётные периоды выплат не должны пересекаться")
    return windows


def serialize_payment_settings(settings: PayrollPaymentSettings | None) -> dict:
    return {
        "configured": settings is not None,
        "id": int(settings.id) if settings is not None and settings.id is not None else None,
        "venue_id": int(settings.venue_id) if settings is not None else None,
        "payment_method_id": int(settings.payment_method_id)
        if settings is not None and settings.payment_method_id is not None
        else None,
        "payment_method": (
            {
                "id": int(settings.payment_method.id),
                "code": settings.payment_method.code,
                "title": settings.payment_method.title,
            }
            if settings is not None and getattr(settings, "payment_method", None) is not None
            else None
        ),
        "cadence": str(settings.cadence if settings is not None else "MONTHLY").upper(),
        "weekly_payment_weekday": (
            int(settings.weekly_payment_weekday)
            if settings is not None and settings.weekly_payment_weekday is not None
            else 0
        ),
        "monthly_rules": parse_monthly_rules(settings),
        "is_active": bool(settings.is_active) if settings is not None else True,
        "updated_at": settings.updated_at.isoformat() if settings is not None and settings.updated_at else None,
    }


def payment_windows_for_settings(
    settings: PayrollPaymentSettings, *, schedule_month: date
) -> list[PayrollPaymentWindow]:
    return build_payment_windows(
        schedule_month=schedule_month,
        cadence=settings.cadence,
        weekly_payment_weekday=settings.weekly_payment_weekday,
        monthly_rules=parse_monthly_rules(settings),
    )


def _ensure_payroll_expense_category(db: Session, *, venue_id: int) -> ExpenseCategory:
    category = db.execute(
        select(ExpenseCategory).where(
            ExpenseCategory.venue_id == int(venue_id),
            ExpenseCategory.code == "payroll",
        )
    ).scalar_one_or_none()
    if category is not None:
        if not category.is_active:
            category.is_active = True
        return category
    category = ExpenseCategory(
        venue_id=int(venue_id),
        code="payroll",
        title="Выплата ФОТ",
        is_active=True,
        sort_order=900,
        created_at=datetime.utcnow(),
    )
    db.add(category)
    db.flush()
    return category


def _run_for_window(db: Session, *, venue_id: int, window: PayrollPaymentWindow) -> PayrollRun | None:
    if window.period_start.replace(day=1) != window.period_end.replace(day=1):
        return None
    return db.execute(
        select(PayrollRun).where(
            PayrollRun.venue_id == int(venue_id),
            PayrollRun.period_month == window.period_start.replace(day=1),
        )
    ).scalar_one_or_none()


def _window_amount_minor(db: Session, *, venue_id: int, window: PayrollPaymentWindow) -> int:
    daily = _group_daily_payroll_allocated_minor(
        db,
        venue_id=int(venue_id),
        period_start=window.period_start,
        period_end=window.period_end,
    )
    return int(sum(int(value or 0) for value in daily.values()))


def generate_payroll_draft_expenses(
    db: Session,
    *,
    settings: PayrollPaymentSettings,
    schedule_month: date,
    created_by_user_id: int | None = None,
    only_payment_date: date | None = None,
) -> dict:
    if not settings.is_active:
        raise ValueError("Настройки выплат ФОТ выключены")
    if settings.payment_method_id is None:
        raise ValueError("Выберите способ оплаты ФОТ")

    venue_id = int(settings.venue_id)
    category = _ensure_payroll_expense_category(db, venue_id=venue_id)
    windows = payment_windows_for_settings(settings, schedule_month=schedule_month)
    if only_payment_date is not None:
        windows = [item for item in windows if item.payment_date == only_payment_date]

    created = 0
    updated = 0
    locked = 0
    skipped_zero = 0
    items: list[dict] = []
    legacy_run_ids: set[int] = set()
    for window in windows:
        amount_minor = _window_amount_minor(db, venue_id=venue_id, window=window)
        payout_key = f"payroll:{venue_id}:{window.payout_key_suffix}"
        existing = db.execute(select(Expense).where(Expense.payroll_payout_key == payout_key)).scalar_one_or_none()
        payroll_run = _run_for_window(db, venue_id=venue_id, window=window)
        if payroll_run is not None:
            legacy_run_ids.add(int(payroll_run.id))

        if existing is not None and str(existing.status or "DRAFT").upper() != "DRAFT":
            locked += 1
            items.append(
                {
                    "expense_id": int(existing.id),
                    "status": str(existing.status or "CONFIRMED").upper(),
                    "action": "locked",
                    "amount_minor": int(existing.amount_minor or 0),
                    "payment_date": window.payment_date,
                    "period_start": window.period_start,
                    "period_end": window.period_end,
                }
            )
            continue

        if amount_minor <= 0 and existing is None:
            skipped_zero += 1
            items.append(
                {
                    "expense_id": None,
                    "status": "SKIPPED",
                    "action": "skipped_zero",
                    "amount_minor": 0,
                    "payment_date": window.payment_date,
                    "period_start": window.period_start,
                    "period_end": window.period_end,
                }
            )
            continue

        comment = (
            f"Автоматический черновик выплаты ФОТ за "
            f"{window.period_start.strftime('%d.%m.%Y')}–{window.period_end.strftime('%d.%m.%Y')}"
        )
        if existing is None:
            existing = Expense(
                venue_id=venue_id,
                category_id=int(category.id),
                payment_method_id=int(settings.payment_method_id),
                payroll_run_id=int(payroll_run.id) if payroll_run is not None else None,
                amount_minor=amount_minor,
                expense_date=window.payment_date,
                shift_slot="TOTAL",
                generated_for_month=window.payment_date.replace(day=1),
                spread_months=1,
                comment=comment,
                status="DRAFT",
                expense_kind="PAYROLL",
                payroll_period_start=window.period_start,
                payroll_period_end=window.period_end,
                payroll_payout_key=payout_key,
                created_by_user_id=int(created_by_user_id) if created_by_user_id is not None else None,
                created_at=datetime.utcnow(),
            )
            db.add(existing)
            db.flush()
            created += 1
            action = "created"
            rebuild_expense_allocations_for_expense(db=db, expense=existing)
        else:
            next_values = {
                "category_id": int(category.id),
                "payment_method_id": int(settings.payment_method_id),
                "payroll_run_id": int(payroll_run.id) if payroll_run is not None else None,
                "amount_minor": amount_minor,
                "expense_date": window.payment_date,
                "generated_for_month": window.payment_date.replace(day=1),
                "comment": comment,
                "expense_kind": "PAYROLL",
                "payroll_period_start": window.period_start,
                "payroll_period_end": window.period_end,
            }
            changed = any(getattr(existing, key, None) != value for key, value in next_values.items())
            if changed:
                for key, value in next_values.items():
                    setattr(existing, key, value)
                existing.updated_at = datetime.utcnow()
                updated += 1
                action = "updated"
                rebuild_expense_allocations_for_expense(db=db, expense=existing)
            else:
                action = "unchanged"
        items.append(
            {
                "expense_id": int(existing.id),
                "status": "DRAFT",
                "action": action,
                "amount_minor": amount_minor,
                "payment_date": window.payment_date,
                "period_start": window.period_start,
                "period_end": window.period_end,
            }
        )

    for run_id in legacy_run_ids:
        delete_finance_entries_for_source(db=db, source_type="payroll_run", source_id=run_id)

    return {
        "schedule_month": schedule_month.replace(day=1),
        "created": created,
        "updated": updated,
        "locked": locked,
        "skipped_zero": skipped_zero,
        "items": items,
    }
