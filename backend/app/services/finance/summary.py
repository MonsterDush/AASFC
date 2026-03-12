from __future__ import annotations

from datetime import date, timedelta
import calendar

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseAllocation, ExpenseCategory, FinanceEntry, PaymentMethod
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


def _group_revenue_breakdown(db: Session, *, venue_id: int, period_start: date, period_end: date, income_mode: str) -> list[dict]:
    summary = compute_revenue_summary(
        venue_id=int(venue_id),
        month=None,
        date_from=period_start,
        date_to=period_end,
        mode='departments' if str(income_mode or 'PAYMENTS').upper() == 'DEPARTMENTS' else 'payments',
        db=db,
    )
    return [
        {
            'ref_id': int(row['ref_id']),
            'code': row.get('code'),
            'title': row.get('title') or f"ID {int(row['ref_id'])}",
            'amount_minor': int(row.get('amount') or 0) * 100,
        }
        for row in (summary.get('rows') or [])
    ]


def _group_expense_categories(db: Session, *, venue_id: int, period_start: date, period_end: date) -> list[dict]:
    rows = db.execute(
        select(ExpenseCategory.id, ExpenseCategory.code, ExpenseCategory.title, func.coalesce(func.sum(ExpenseAllocation.amount_minor), 0))
        .join(Expense, Expense.category_id == ExpenseCategory.id)
        .join(ExpenseAllocation, ExpenseAllocation.expense_id == Expense.id)
        .where(
            Expense.venue_id == int(venue_id),
            ExpenseAllocation.month >= period_start.replace(day=1),
            ExpenseAllocation.month <= period_end.replace(day=1),
            Expense.status == 'CONFIRMED',
        )
        .group_by(ExpenseCategory.id, ExpenseCategory.code, ExpenseCategory.title)
        .order_by(func.coalesce(func.sum(ExpenseAllocation.amount_minor), 0).desc(), ExpenseCategory.title.asc())
    ).all()
    return [
        {
            'category_id': int(row[0]),
            'code': row[1],
            'title': row[2],
            'amount_minor': int(row[3] or 0),
        }
        for row in rows
    ]


def _group_payment_method_balances(db: Session, *, venue_id: int, period_start: date, period_end: date) -> list[dict]:
    rows = db.execute(
        select(
            PaymentMethod.id,
            PaymentMethod.code,
            PaymentMethod.title,
            PaymentMethod.is_active,
            PaymentMethod.sort_order,
            func.coalesce(
                func.sum(
                    case(
                        (
                            (FinanceEntry.entry_date >= period_start)
                            & (FinanceEntry.entry_date <= period_end)
                            & (FinanceEntry.direction == 'INCOME'),
                            FinanceEntry.amount_minor,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label('inflow_minor'),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (FinanceEntry.entry_date >= period_start)
                            & (FinanceEntry.entry_date <= period_end)
                            & (FinanceEntry.direction == 'EXPENSE'),
                            FinanceEntry.amount_minor,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label('outflow_minor'),
            func.coalesce(
                func.sum(
                    case(
                        (FinanceEntry.direction == 'INCOME', FinanceEntry.amount_minor),
                        (FinanceEntry.direction == 'EXPENSE', -FinanceEntry.amount_minor),
                        else_=0,
                    )
                ),
                0,
            ).label('balance_minor'),
        )
        .outerjoin(
            FinanceEntry,
            (FinanceEntry.payment_method_id == PaymentMethod.id)
            & (FinanceEntry.venue_id == int(venue_id))
            & (FinanceEntry.entry_date <= period_end),
        )
        .where(PaymentMethod.venue_id == int(venue_id))
        .group_by(PaymentMethod.id, PaymentMethod.code, PaymentMethod.title, PaymentMethod.is_active, PaymentMethod.sort_order)
        .order_by(PaymentMethod.sort_order.asc(), PaymentMethod.id.asc())
    ).all()
    out: list[dict] = []
    for row in rows:
        inflow_minor = int(row[5] or 0)
        outflow_minor = int(row[6] or 0)
        balance_minor = int(row[7] or 0)
        is_active = bool(row[3])
        if not is_active and inflow_minor == 0 and outflow_minor == 0 and balance_minor == 0:
            continue
        out.append(
            {
                'payment_method_id': int(row[0]),
                'code': row[1],
                'title': row[2],
                'inflow_minor': inflow_minor,
                'outflow_minor': outflow_minor,
                'balance_minor': balance_minor,
            }
        )
    return out


def get_finance_summary(*, db: Session, venue_id: int, month: str | None = None, date_from: date | None = None, date_to: date | None = None) -> dict:
    period_start, period_end = resolve_finance_period(month, date_from, date_to)

    revenue_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='INCOME', kind='REVENUE')
    expense_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='EXPENSE', kind='EXPENSE')
    payroll_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='EXPENSE', kind='PAYROLL')
    adjustment_expense_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='EXPENSE', kind='ADJUSTMENT')
    adjustment_income_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='INCOME', kind='ADJUSTMENT')
    refund_income_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='INCOME', kind='REFUND')
    refund_expense_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='EXPENSE', kind='REFUND')

    adjustments_minor = adjustment_income_minor - adjustment_expense_minor
    refunds_minor = refund_income_minor - refund_expense_minor
    profit_minor = revenue_minor - expense_minor - payroll_minor + adjustments_minor + refunds_minor
    margin_bps = int((profit_minor * 10000) / revenue_minor) if revenue_minor > 0 else None

    return {
        'month': month,
        'period_start': period_start,
        'period_end': period_end,
        'revenue_minor': revenue_minor,
        'expense_minor': expense_minor,
        'payroll_minor': payroll_minor,
        'adjustments_minor': adjustments_minor,
        'refunds_minor': refunds_minor,
        'profit_minor': profit_minor,
        'margin_bps': margin_bps,
    }


def get_monthly_finance_summary(*, db: Session, venue_id: int, month: str | None, income_mode: str = 'PAYMENTS') -> dict:
    period_start, period_end = resolve_finance_period(month=month, date_from=None, date_to=None)
    base = get_finance_summary(db=db, venue_id=venue_id, month=month)
    mode = str(income_mode or 'PAYMENTS').upper()
    if mode not in {'PAYMENTS', 'DEPARTMENTS'}:
        raise ValueError('Bad income_mode, expected PAYMENTS or DEPARTMENTS')
    return {
        **base,
        'month': month or period_start.strftime('%Y-%m'),
        'income_mode': mode,
        'revenue_breakdown': _group_revenue_breakdown(db, venue_id=venue_id, period_start=period_start, period_end=period_end, income_mode=mode),
        'expense_categories': _group_expense_categories(db, venue_id=venue_id, period_start=period_start, period_end=period_end),
        'payment_method_balances': _group_payment_method_balances(db, venue_id=venue_id, period_start=period_start, period_end=period_end),
    }
