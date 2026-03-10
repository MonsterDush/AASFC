from __future__ import annotations

from datetime import date, timedelta
import calendar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import FinanceEntry


def _parse_month_yyyy_mm(month: str) -> tuple[date, date]:
    try:
        y_s, m_s = month.split("-")
        y = int(y_s)
        m = int(m_s)
        start = date(y, m, 1)
        end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
        return start, end
    except Exception:
        raise ValueError("Bad month format, expected YYYY-MM")


def resolve_finance_period(month: str | None, date_from: date | None, date_to: date | None) -> tuple[date, date]:
    if date_from and not date_to:
        date_to = date_from
    if date_to and not date_from:
        date_from = date_to
    if date_from and date_to:
        if date_to < date_from:
            date_from, date_to = date_to, date_from
        return date_from, date_to
    if month:
        start, end_excl = _parse_month_yyyy_mm(month)
        return start, end_excl - timedelta(days=1)
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    return date(today.year, today.month, 1), date(today.year, today.month, last_day)


def _sum_amount(db: Session, *, venue_id: int, period_start: date, period_end: date, direction: str, kind: str) -> int:
    return int(
        db.execute(
            select(func.coalesce(func.sum(FinanceEntry.amount_minor), 0)).where(
                FinanceEntry.venue_id == int(venue_id),
                FinanceEntry.entry_date >= period_start,
                FinanceEntry.entry_date <= period_end,
                FinanceEntry.direction == direction,
                FinanceEntry.kind == kind,
            )
        ).scalar()
        or 0
    )


def get_finance_summary(*, db: Session, venue_id: int, month: str | None = None, date_from: date | None = None, date_to: date | None = None) -> dict:
    period_start, period_end = resolve_finance_period(month, date_from, date_to)

    revenue_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction="INCOME", kind="REVENUE")
    expense_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction="EXPENSE", kind="EXPENSE")
    payroll_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction="EXPENSE", kind="PAYROLL")
    adjustment_expense_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction="EXPENSE", kind="ADJUSTMENT")
    adjustment_income_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction="INCOME", kind="ADJUSTMENT")
    refund_income_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction="INCOME", kind="REFUND")
    refund_expense_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction="EXPENSE", kind="REFUND")

    adjustments_minor = adjustment_income_minor - adjustment_expense_minor
    refunds_minor = refund_income_minor - refund_expense_minor
    profit_minor = revenue_minor - expense_minor - payroll_minor + adjustments_minor + refunds_minor
    margin_bps = int((profit_minor * 10000) / revenue_minor) if revenue_minor > 0 else None

    return {
        "month": month,
        "period_start": period_start,
        "period_end": period_end,
        "revenue_minor": revenue_minor,
        "expense_minor": expense_minor,
        "payroll_minor": payroll_minor,
        "adjustments_minor": adjustments_minor,
        "refunds_minor": refunds_minor,
        "profit_minor": profit_minor,
        "margin_bps": margin_bps,
    }
