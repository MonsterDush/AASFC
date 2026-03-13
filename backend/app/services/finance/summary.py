from __future__ import annotations

from datetime import date, timedelta
import calendar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    DailyReport,
    DailyReportValue,
    Department,
    Expense,
    ExpenseCategory,
    ExpenseRecognitionEntry,
    FinanceEntry,
    PaymentMethod,
    RecurringExpenseRule,
)
from app.services.finance.expenses import rebuild_expense_allocations_for_expense


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


def _sum_closed_report_revenue_minor(db: Session, *, venue_id: int, period_start: date, period_end: date) -> int:
    return int(
        db.execute(
            select(func.coalesce(func.sum(DailyReport.revenue_total), 0)).where(
                DailyReport.venue_id == int(venue_id),
                DailyReport.status == 'CLOSED',
                DailyReport.date >= period_start,
                DailyReport.date <= period_end,
            )
        ).scalar()
        or 0
    ) * 100


def _backfill_missing_expense_recognition(db: Session, *, venue_id: int) -> int:
    missing = db.execute(
        select(Expense)
        .where(
            Expense.venue_id == int(venue_id),
            Expense.status == 'CONFIRMED',
            Expense.id.not_in(select(ExpenseRecognitionEntry.expense_id)),
        )
        .order_by(Expense.id.asc())
    ).scalars().all()
    if not missing:
        return 0
    for expense in missing:
        rebuild_expense_allocations_for_expense(db=db, expense=expense)
    db.commit()
    return len(missing)


def _closed_reports_subquery(*, venue_id: int, period_start: date, period_end: date):
    return (
        select(DailyReport.id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == 'CLOSED',
            DailyReport.date >= period_start,
            DailyReport.date <= period_end,
        )
        .subquery()
    )


def _group_revenue_breakdown(db: Session, *, venue_id: int, period_start: date, period_end: date, income_mode: str) -> list[dict]:
    mode = str(income_mode or 'PAYMENTS').upper()
    kind = 'DEPT' if mode == 'DEPARTMENTS' else 'PAYMENT'
    Catalog = Department if mode == 'DEPARTMENTS' else PaymentMethod
    closed_reports = _closed_reports_subquery(venue_id=venue_id, period_start=period_start, period_end=period_end)
    rows = db.execute(
        select(DailyReportValue.ref_id, func.coalesce(func.sum(DailyReportValue.value_numeric), 0))
        .where(
            DailyReportValue.kind == kind,
            DailyReportValue.report_id.in_(select(closed_reports.c.id)),
        )
        .group_by(DailyReportValue.ref_id)
    ).all()
    catalog_rows = db.execute(
        select(Catalog.id, getattr(Catalog, 'code', None), Catalog.title).where(Catalog.venue_id == int(venue_id))
    ).all()
    catalog_map = {int(row[0]): row for row in catalog_rows}
    out: list[dict] = []
    for row in rows:
        ref_id = int(row[0])
        amount_minor = int(row[1] or 0) * 100
        catalog = catalog_map.get(ref_id)
        out.append(
            {
                'ref_id': ref_id,
                'code': catalog[1] if catalog else None,
                'title': catalog[2] if catalog else f'ID {ref_id}',
                'subtitle': None,
                'amount_minor': amount_minor,
            }
        )
    out.sort(key=lambda item: (-int(item['amount_minor']), str(item['title'])))
    return out


def _sum_expense_recognition_minor(db: Session, *, venue_id: int, period_start: date, period_end: date) -> int:
    return int(
        db.execute(
            select(func.coalesce(func.sum(ExpenseRecognitionEntry.amount_minor), 0))
            .select_from(ExpenseRecognitionEntry)
            .join(Expense, Expense.id == ExpenseRecognitionEntry.expense_id)
            .where(
                ExpenseRecognitionEntry.venue_id == int(venue_id),
                ExpenseRecognitionEntry.recognition_date >= period_start,
                ExpenseRecognitionEntry.recognition_date <= period_end,
                Expense.status == 'CONFIRMED',
            )
        ).scalar()
        or 0
    )


def _expense_document_stats_for_period(db: Session, *, venue_id: int, period_start: date, period_end: date) -> dict:
    month_start = period_start.replace(day=1)
    last_day = calendar.monthrange(period_start.year, period_start.month)[1]
    month_end = period_start.replace(day=last_day)
    stmt = (
        select(Expense.id, Expense.status, Expense.amount_minor)
        .where(
            Expense.venue_id == int(venue_id),
            (Expense.generated_for_month == month_start)
            | ((Expense.generated_for_month.is_(None)) & (Expense.expense_date >= period_start) & (Expense.expense_date <= period_end))
        )
        .order_by(Expense.id.asc())
    )
    rows = db.execute(stmt).all()
    draft_rows = [row for row in rows if str(row[1] or 'DRAFT').upper() == 'DRAFT']
    return {
        'draft_expense_count': len(draft_rows),
        'draft_expense_total_minor': int(sum(int(row[2] or 0) for row in draft_rows)),
    }


def _group_expense_categories(db: Session, *, venue_id: int, period_start: date, period_end: date) -> list[dict]:
    rows = db.execute(
        select(
            ExpenseCategory.id,
            ExpenseCategory.code,
            ExpenseCategory.title,
            func.coalesce(func.sum(ExpenseRecognitionEntry.amount_minor), 0),
        )
        .select_from(ExpenseRecognitionEntry)
        .join(Expense, Expense.id == ExpenseRecognitionEntry.expense_id)
        .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
        .where(
            ExpenseRecognitionEntry.venue_id == int(venue_id),
            ExpenseRecognitionEntry.recognition_date >= period_start,
            ExpenseRecognitionEntry.recognition_date <= period_end,
            Expense.status == 'CONFIRMED',
        )
        .group_by(ExpenseCategory.id, ExpenseCategory.code, ExpenseCategory.title)
    ).all()

    out = [
        {
            'category_id': int(row[0]),
            'code': row[1],
            'title': row[2],
            'subtitle': None,
            'amount_minor': int(row[3] or 0),
        }
        for row in rows
    ]
    out.sort(key=lambda item: (-int(item['amount_minor']), str(item['title'])))
    return out


def _group_daily_recurring_expenses(db: Session, *, venue_id: int, target_date: date) -> list[dict]:
    rows = db.execute(
        select(
            RecurringExpenseRule.title,
            ExpenseCategory.code,
            ExpenseCategory.title,
            func.coalesce(func.sum(ExpenseRecognitionEntry.amount_minor), 0),
        )
        .select_from(ExpenseRecognitionEntry)
        .join(Expense, Expense.id == ExpenseRecognitionEntry.expense_id)
        .join(RecurringExpenseRule, RecurringExpenseRule.id == Expense.recurring_rule_id)
        .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
        .where(
            ExpenseRecognitionEntry.venue_id == int(venue_id),
            ExpenseRecognitionEntry.recognition_date == target_date,
            Expense.status == 'CONFIRMED',
            Expense.recurring_rule_id.is_not(None),
        )
        .group_by(RecurringExpenseRule.title, ExpenseCategory.code, ExpenseCategory.title)
        .order_by(func.coalesce(func.sum(ExpenseRecognitionEntry.amount_minor), 0).desc(), RecurringExpenseRule.title.asc())
    ).all()
    return [
        {
            'title': row[0],
            'code': row[1],
            'subtitle': row[2],
            'amount_minor': int(row[3] or 0),
        }
        for row in rows
    ]


def _sum_closed_report_payment_minor(
    db: Session,
    *,
    venue_id: int,
    payment_method_id: int | None = None,
    payment_method_ids: list[int] | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> int:
    stmt = (
        select(func.coalesce(func.sum(DailyReportValue.value_numeric), 0))
        .select_from(DailyReportValue)
        .join(DailyReport, DailyReport.id == DailyReportValue.report_id)
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == 'CLOSED',
            DailyReportValue.kind == 'PAYMENT',
        )
    )
    if period_start is not None:
        stmt = stmt.where(DailyReport.date >= period_start)
    if period_end is not None:
        stmt = stmt.where(DailyReport.date <= period_end)
    if payment_method_id is not None:
        stmt = stmt.where(DailyReportValue.ref_id == int(payment_method_id))
    elif payment_method_ids:
        stmt = stmt.where(DailyReportValue.ref_id.in_([int(x) for x in payment_method_ids]))
    return int(db.execute(stmt).scalar() or 0) * 100


def _sum_non_revenue_payment_entries(
    db: Session,
    *,
    venue_id: int,
    payment_method_id: int,
    direction: str,
    period_start: date | None = None,
    period_end: date | None = None,
) -> int:
    stmt = select(func.coalesce(func.sum(FinanceEntry.amount_minor), 0)).where(
        FinanceEntry.venue_id == int(venue_id),
        FinanceEntry.payment_method_id == int(payment_method_id),
        FinanceEntry.direction == str(direction).upper(),
        FinanceEntry.kind != 'REVENUE',
    )
    if period_start is not None:
        stmt = stmt.where(FinanceEntry.entry_date >= period_start)
    if period_end is not None:
        stmt = stmt.where(FinanceEntry.entry_date <= period_end)
    return int(db.execute(stmt).scalar() or 0)


def _group_payment_method_balances(db: Session, *, venue_id: int, period_start: date, period_end: date) -> list[dict]:
    payment_methods = db.execute(
        select(PaymentMethod.id, PaymentMethod.code, PaymentMethod.title, PaymentMethod.is_active)
        .where(PaymentMethod.venue_id == int(venue_id))
        .order_by(PaymentMethod.sort_order.asc(), PaymentMethod.id.asc())
    ).all()
    out: list[dict] = []
    for row in payment_methods:
        payment_method_id = int(row[0])
        revenue_inflow_minor = _sum_closed_report_payment_minor(
            db,
            venue_id=venue_id,
            payment_method_id=payment_method_id,
            period_start=period_start,
            period_end=period_end,
        )
        revenue_cumulative_minor = _sum_closed_report_payment_minor(
            db,
            venue_id=venue_id,
            payment_method_id=payment_method_id,
            period_end=period_end,
        )
        other_income_minor = _sum_non_revenue_payment_entries(
            db,
            venue_id=venue_id,
            payment_method_id=payment_method_id,
            direction='INCOME',
            period_start=period_start,
            period_end=period_end,
        )
        other_income_cumulative_minor = _sum_non_revenue_payment_entries(
            db,
            venue_id=venue_id,
            payment_method_id=payment_method_id,
            direction='INCOME',
            period_end=period_end,
        )
        outflow_minor = _sum_non_revenue_payment_entries(
            db,
            venue_id=venue_id,
            payment_method_id=payment_method_id,
            direction='EXPENSE',
            period_start=period_start,
            period_end=period_end,
        )
        cumulative_outflow_minor = _sum_non_revenue_payment_entries(
            db,
            venue_id=venue_id,
            payment_method_id=payment_method_id,
            direction='EXPENSE',
            period_end=period_end,
        )
        inflow_minor = revenue_inflow_minor + other_income_minor
        balance_minor = revenue_cumulative_minor + other_income_cumulative_minor - cumulative_outflow_minor
        is_active = bool(row[3])
        if not is_active and inflow_minor == 0 and outflow_minor == 0 and balance_minor == 0:
            continue
        out.append(
            {
                'payment_method_id': payment_method_id,
                'code': row[1],
                'title': row[2],
                'inflow_minor': inflow_minor,
                'outflow_minor': outflow_minor,
                'balance_minor': balance_minor,
            }
        )
    return out


def _group_daily_point_expenses(db: Session, *, venue_id: int, target_date: date) -> list[dict]:
    rows = db.execute(
        select(
            ExpenseCategory.id,
            ExpenseCategory.code,
            ExpenseCategory.title,
            func.coalesce(func.sum(ExpenseRecognitionEntry.amount_minor), 0),
        )
        .select_from(ExpenseRecognitionEntry)
        .join(Expense, Expense.id == ExpenseRecognitionEntry.expense_id)
        .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
        .where(
            ExpenseRecognitionEntry.venue_id == int(venue_id),
            ExpenseRecognitionEntry.recognition_date == target_date,
            Expense.status == 'CONFIRMED',
            Expense.recurring_rule_id.is_(None),
        )
        .group_by(ExpenseCategory.id, ExpenseCategory.code, ExpenseCategory.title)
        .order_by(func.coalesce(func.sum(ExpenseRecognitionEntry.amount_minor), 0).desc(), ExpenseCategory.title.asc())
    ).all()
    return [
        {
            'category_id': int(row[0]),
            'code': row[1],
            'title': row[2],
            'subtitle': 'Разовые расходы дня',
            'amount_minor': int(row[3] or 0),
        }
        for row in rows
    ]


def get_finance_summary(*, db: Session, venue_id: int, month: str | None = None, date_from: date | None = None, date_to: date | None = None) -> dict:
    period_start, period_end = resolve_finance_period(month, date_from, date_to)
    _backfill_missing_expense_recognition(db, venue_id=venue_id)

    revenue_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='INCOME', kind='REVENUE')
    expense_minor = _sum_expense_recognition_minor(db, venue_id=venue_id, period_start=period_start, period_end=period_end)
    payroll_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='EXPENSE', kind='PAYROLL')
    adjustment_expense_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='EXPENSE', kind='ADJUSTMENT')
    adjustment_income_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='INCOME', kind='ADJUSTMENT')
    refund_income_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='INCOME', kind='REFUND')
    refund_expense_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='EXPENSE', kind='REFUND')

    adjustments_minor = adjustment_income_minor - adjustment_expense_minor
    refunds_minor = refund_income_minor - refund_expense_minor
    profit_minor = revenue_minor - expense_minor - payroll_minor + adjustments_minor + refunds_minor
    margin_bps = int((profit_minor * 10000) / revenue_minor) if revenue_minor > 0 else None

    draft_stats = _expense_document_stats_for_period(db, venue_id=venue_id, period_start=period_start, period_end=period_end)
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
        **draft_stats,
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


def get_day_finance_summary(*, db: Session, venue_id: int, target_date: date, income_mode: str = 'PAYMENTS') -> dict:
    period_start = target_date
    period_end = target_date
    mode = str(income_mode or 'PAYMENTS').upper()
    if mode not in {'PAYMENTS', 'DEPARTMENTS'}:
        raise ValueError('Bad income_mode, expected PAYMENTS or DEPARTMENTS')

    revenue_minor = _sum_closed_report_revenue_minor(db, venue_id=venue_id, period_start=target_date, period_end=target_date)
    point_expenses = _group_daily_point_expenses(db, venue_id=venue_id, target_date=target_date)
    point_expense_minor = int(sum(int(item['amount_minor'] or 0) for item in point_expenses))
    recurring_expenses = _group_daily_recurring_expenses(db, venue_id=venue_id, target_date=target_date)
    recurring_expense_minor = int(sum(int(item['amount_minor'] or 0) for item in recurring_expenses))
    payroll_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='EXPENSE', kind='PAYROLL')
    adjustment_expense_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='EXPENSE', kind='ADJUSTMENT')
    adjustment_income_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='INCOME', kind='ADJUSTMENT')
    refund_income_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='INCOME', kind='REFUND')
    refund_expense_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='EXPENSE', kind='REFUND')
    adjustments_minor = adjustment_income_minor - adjustment_expense_minor
    refunds_minor = refund_income_minor - refund_expense_minor
    expense_minor = point_expense_minor + recurring_expense_minor
    profit_minor = revenue_minor - expense_minor - payroll_minor + adjustments_minor + refunds_minor
    margin_bps = int((profit_minor * 10000) / revenue_minor) if revenue_minor > 0 else None

    draft_stats = _expense_document_stats_for_period(db, venue_id=venue_id, period_start=target_date, period_end=target_date)
    return {
        'date': target_date,
        'month': target_date.strftime('%Y-%m'),
        'period_start': period_start,
        'period_end': period_end,
        'revenue_minor': revenue_minor,
        'expense_minor': expense_minor,
        'payroll_minor': payroll_minor,
        'adjustments_minor': adjustments_minor,
        'refunds_minor': refunds_minor,
        'profit_minor': profit_minor,
        'margin_bps': margin_bps,
        'income_mode': mode,
        'revenue_breakdown': _group_revenue_breakdown(db, venue_id=venue_id, period_start=target_date, period_end=target_date, income_mode=mode),
        'point_expenses': point_expenses,
        'point_expense_minor': point_expense_minor,
        'recurring_expenses': recurring_expenses,
        'recurring_expense_minor': recurring_expense_minor,
        'payment_method_balances': _group_payment_method_balances(db, venue_id=venue_id, period_start=target_date, period_end=target_date),
        **draft_stats,
    }
