from __future__ import annotations

from datetime import date, timedelta
import calendar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseAllocation, ExpenseCategory, FinanceEntry
from app.services.finance.expenses import CONFIRMED_EXPENSE_STATUS
from app.services.finance.revenue import compute_revenue_summary


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


def get_monthly_finance_summary(*, db: Session, venue_id: int, month: str, income_mode: str = "PAYMENTS") -> dict:
    period_start, period_end = resolve_finance_period(month, None, None)
    base = get_finance_summary(db=db, venue_id=venue_id, month=month)

    revenue = compute_revenue_summary(
        venue_id=venue_id,
        month=month,
        date_from=None,
        date_to=None,
        mode=(income_mode or "PAYMENTS").lower(),
        db=db,
    )

    expense_rows = db.execute(
        select(
            ExpenseCategory.id,
            ExpenseCategory.code,
            ExpenseCategory.title,
            func.coalesce(func.sum(ExpenseAllocation.amount_minor), 0).label("amount_minor"),
        )
        .select_from(ExpenseAllocation)
        .join(Expense, Expense.id == ExpenseAllocation.expense_id)
        .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
        .where(
            ExpenseAllocation.venue_id == int(venue_id),
            ExpenseAllocation.month >= period_start,
            ExpenseAllocation.month <= period_end,
            Expense.status == CONFIRMED_EXPENSE_STATUS,
        )
        .group_by(ExpenseCategory.id, ExpenseCategory.code, ExpenseCategory.title)
        .order_by(func.coalesce(func.sum(ExpenseAllocation.amount_minor), 0).desc(), ExpenseCategory.title.asc())
    ).all()

    return {
        **base,
        "income_mode": str(income_mode or "PAYMENTS").upper(),
        "revenue_breakdown": [
            {
                "ref_id": int(row["ref_id"] if isinstance(row, dict) else row[0]),
                "code": row["code"] if isinstance(row, dict) else row[1],
                "title": row["title"] if isinstance(row, dict) else row[2],
                "amount_minor": int((row["amount"] if isinstance(row, dict) else row[3]) or 0) * 100,
            }
            for row in revenue.get("rows", [])
        ],
        "expense_categories": [
            {
                "category_id": int(row[0]),
                "code": row[1],
                "title": row[2],
                "amount_minor": int(row[3] or 0),
            }
            for row in expense_rows
        ],
    }
