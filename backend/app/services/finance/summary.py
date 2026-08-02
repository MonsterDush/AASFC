from __future__ import annotations

from datetime import date, timedelta
import calendar
import json

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
    PayrollLine,
    PayrollRun,
    RecurringExpenseRule,
    Venue,
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



def _normalize_summary_shift_slot(value: str | None) -> str | None:
    slot = str(value or "TOTAL").strip().upper()
    if slot in {"DAY", "NIGHT"}:
        return slot
    return None


def _is_slot_specific(value: str | None) -> bool:
    return _normalize_summary_shift_slot(value) in {"DAY", "NIGHT"}


def _recognition_scope_filters(shift_slot: str | None) -> list:
    slot = _normalize_summary_shift_slot(shift_slot)
    return [ExpenseRecognitionEntry.shift_slot == slot] if slot is not None else []

def _active_finance_shift_slots(db: Session, *, venue_id: int) -> list[str]:
    night_enabled = db.execute(
        select(Venue.night_shifts_enabled).where(Venue.id == int(venue_id))
    ).scalar_one_or_none()
    return ["DAY", "NIGHT"] if bool(night_enabled) else ["DAY"]


def _amount_share_for_slot(*, amount_minor: int, slots: list[str], shift_slot: str) -> int:
    if shift_slot not in slots:
        return 0
    return _split_amount_for_index(int(amount_minor or 0), len(slots), slots.index(shift_slot))


def _sum_amount(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
    direction: str,
    kind: str,
    shift_slot: str | None = None,
) -> int:
    slot = _normalize_summary_shift_slot(shift_slot)
    base_filters = (
        FinanceEntry.venue_id == int(venue_id),
        FinanceEntry.entry_date >= period_start,
        FinanceEntry.entry_date <= period_end,
        FinanceEntry.direction == direction,
        FinanceEntry.kind == kind,
    )
    if slot is None:
        return int(
            db.execute(
                select(func.coalesce(func.sum(FinanceEntry.amount_minor), 0)).where(*base_filters)
            ).scalar()
            or 0
        )

    slots = _active_finance_shift_slots(db, venue_id=venue_id)
    rows = db.execute(
        select(FinanceEntry.amount_minor, FinanceEntry.meta_json).where(*base_filters)
    ).all()
    total_minor = 0
    for amount_minor, meta_json in rows:
        entry_slot = str((meta_json or {}).get("shift_slot") or "TOTAL").strip().upper()
        if entry_slot in {"DAY", "NIGHT"}:
            if entry_slot == slot:
                total_minor += int(amount_minor or 0)
            continue
        total_minor += _amount_share_for_slot(
            amount_minor=int(amount_minor or 0),
            slots=slots,
            shift_slot=slot,
        )
    return int(total_minor)


def _month_dates(month_start: date) -> list[date]:
    next_month = date(month_start.year + 1, 1, 1) if month_start.month == 12 else date(month_start.year, month_start.month + 1, 1)
    days: list[date] = []
    cursor = month_start
    while cursor < next_month:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _split_amount_for_index(amount_minor: int, parts: int, index: int) -> int:
    parts = int(parts or 0)
    index = int(index or 0)
    if parts <= 0 or index < 0 or index >= parts:
        return 0
    total = int(amount_minor or 0)
    sign = -1 if total < 0 else 1
    abs_total = abs(total)
    base = abs_total // parts
    remainder = abs_total - base * parts
    return sign * (base + (1 if index < remainder else 0))


def _sum_daily_payroll_allocated_minor(
    db: Session,
    *,
    venue_id: int,
    target_date: date,
    shift_slot: str | None = None,
) -> int:
    month_start = target_date.replace(day=1)
    days_in_month = _month_dates(month_start)
    month_day_index = (target_date - month_start).days
    rows = db.execute(
        select(PayrollLine.amount_minor, PayrollLine.breakdown_json)
        .join(PayrollRun, PayrollRun.id == PayrollLine.payroll_run_id)
        .where(
            PayrollLine.venue_id == int(venue_id),
            PayrollRun.period_month == month_start,
        )
    ).all()

    total_minor = 0
    target_date_iso = target_date.isoformat()
    slot = _normalize_summary_shift_slot(shift_slot)
    active_slots = _active_finance_shift_slots(db, venue_id=venue_id)
    for amount_minor, breakdown_json in rows:
        if int(amount_minor or 0) <= 0 or not breakdown_json:
            continue
        try:
            breakdown = json.loads(breakdown_json)
        except Exception:
            continue
        metrics = breakdown.get('metrics') or {}
        shift_allocations = [
            item for item in (breakdown.get('shift_allocations') or [])
            if isinstance(item, dict)
        ]
        if shift_allocations:
            for allocation in shift_allocations:
                if str(allocation.get("date") or "") != target_date_iso:
                    continue
                allocation_slot = str(allocation.get("shift_slot") or "DAY").strip().upper()
                if slot is not None and allocation_slot != slot:
                    continue
                total_minor += int(allocation.get("amount_minor") or 0)
            continue

        worked_dates = [str(day) for day in (metrics.get('worked_dates') or []) if day]
        worked_dates_sorted = sorted(set(worked_dates))
        components = [item for item in (breakdown.get('components') or []) if isinstance(item, dict)]

        if components:
            for component in components:
                component_amount_minor = int(component.get('amount_minor') or 0)
                if component_amount_minor <= 0:
                    continue
                component_type = str(component.get('component_type') or '').strip().upper()
                if component_type == 'SALARY_FIXED_MONTH':
                    day_amount_minor = _split_amount_for_index(component_amount_minor, len(days_in_month), month_day_index)
                    total_minor += (
                        day_amount_minor
                        if slot is None
                        else _amount_share_for_slot(
                            amount_minor=day_amount_minor,
                            slots=active_slots,
                            shift_slot=slot,
                        )
                    )
                    continue
                if target_date_iso not in worked_dates_sorted:
                    continue
                day_amount_minor = _split_amount_for_index(
                    component_amount_minor,
                    len(worked_dates_sorted),
                    worked_dates_sorted.index(target_date_iso),
                )
                total_minor += (
                    day_amount_minor
                    if slot is None
                    else _amount_share_for_slot(
                        amount_minor=day_amount_minor,
                        slots=active_slots,
                        shift_slot=slot,
                    )
                )
            continue

        if target_date_iso not in worked_dates_sorted:
            continue
        day_amount_minor = _split_amount_for_index(
            int(amount_minor or 0),
            len(worked_dates_sorted) or 1,
            worked_dates_sorted.index(target_date_iso) if target_date_iso in worked_dates_sorted else 0,
        )
        total_minor += (
            day_amount_minor
            if slot is None
            else _amount_share_for_slot(
                amount_minor=day_amount_minor,
                slots=active_slots,
                shift_slot=slot,
            )
        )
    return int(total_minor)


def _sum_payroll_minor_for_period(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
    shift_slot: str | None = None,
    daily_amounts: dict[date, int] | None = None,
) -> int:
    if daily_amounts is None:
        daily_amounts = _group_daily_payroll_allocated_minor(
            db,
            venue_id=venue_id,
            period_start=period_start,
            period_end=period_end,
            shift_slot=shift_slot,
        )
    allocated_total_minor = int(sum(int(amount or 0) for amount in daily_amounts.values()))
    if any(int(amount or 0) != 0 for amount in daily_amounts.values()):
        return int(allocated_total_minor)
    return _sum_amount(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
        direction='EXPENSE',
        kind='PAYROLL',
        shift_slot=shift_slot,
    )


def _group_daily_payroll_allocated_minor(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
    shift_slot: str | None = None,
) -> dict[date, int]:
    out: dict[date, int] = {}
    day = period_start
    while day <= period_end:
        out[day] = _sum_daily_payroll_allocated_minor(
            db,
            venue_id=venue_id,
            target_date=day,
            shift_slot=shift_slot,
        )
        day += timedelta(days=1)
    if _normalize_summary_shift_slot(shift_slot) is None:
        from app.services.payroll.adjustments import group_payroll_adjustment_net_by_date

        adjustments_by_date = group_payroll_adjustment_net_by_date(
            db,
            venue_id=int(venue_id),
            period_start=period_start,
            period_end=period_end,
        )
        for adjustment_date, amount_minor in adjustments_by_date.items():
            out[adjustment_date] = int(out.get(adjustment_date, 0) or 0) + int(amount_minor or 0)
    return out


def _sum_closed_report_revenue_minor(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
    shift_slot: str | None = None,
) -> int:
    stmt = select(func.coalesce(func.sum(DailyReport.revenue_total), 0)).where(
        DailyReport.venue_id == int(venue_id),
        DailyReport.status == 'CLOSED',
        DailyReport.date >= period_start,
        DailyReport.date <= period_end,
    )
    slot = _normalize_summary_shift_slot(shift_slot)
    if slot is not None:
        stmt = stmt.where(DailyReport.shift_slot == slot)
    return int(db.execute(stmt).scalar() or 0) * 100


def _backfill_missing_expense_recognition(db: Session, *, venue_id: int) -> int:
    missing = db.execute(
        select(Expense)
        .where(
            Expense.venue_id == int(venue_id),
            Expense.status == 'CONFIRMED',
            Expense.expense_kind == 'OPERATING',
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


def _closed_reports_subquery(*, venue_id: int, period_start: date, period_end: date, shift_slot: str | None = None):
    stmt = select(DailyReport.id).where(
        DailyReport.venue_id == int(venue_id),
        DailyReport.status == 'CLOSED',
        DailyReport.date >= period_start,
        DailyReport.date <= period_end,
    )
    slot = _normalize_summary_shift_slot(shift_slot)
    if slot is not None:
        stmt = stmt.where(DailyReport.shift_slot == slot)
    return stmt.subquery()


def _group_revenue_breakdown(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
    income_mode: str,
    shift_slot: str | None = None,
) -> list[dict]:
    mode = str(income_mode or 'PAYMENTS').upper()
    kind = 'DEPT' if mode == 'DEPARTMENTS' else 'PAYMENT'
    Catalog = Department if mode == 'DEPARTMENTS' else PaymentMethod
    closed_reports = _closed_reports_subquery(venue_id=venue_id, period_start=period_start, period_end=period_end, shift_slot=shift_slot)
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


def _group_daily_recurring_expenses(
    db: Session,
    *,
    venue_id: int,
    target_date: date,
    shift_slot: str | None = None,
) -> list[dict]:
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
            *_recognition_scope_filters(shift_slot),
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
    shift_slot: str | None = None,
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
    slot = _normalize_summary_shift_slot(shift_slot)
    if slot is not None:
        stmt = stmt.where(DailyReport.shift_slot == slot)
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


def _group_payment_method_balances(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
    shift_slot: str | None = None,
) -> list[dict]:
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
            shift_slot=shift_slot,
        )
        revenue_cumulative_minor = _sum_closed_report_payment_minor(
            db,
            venue_id=venue_id,
            payment_method_id=payment_method_id,
            period_end=period_end,
            shift_slot=shift_slot,
        )
        if _is_slot_specific(shift_slot):
            other_income_minor = 0
            other_income_cumulative_minor = 0
            outflow_minor = 0
            cumulative_outflow_minor = 0
        else:
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


def _group_daily_point_expenses(
    db: Session,
    *,
    venue_id: int,
    target_date: date,
    shift_slot: str | None = None,
) -> list[dict]:
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
            *_recognition_scope_filters(shift_slot),
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


def _group_closed_report_revenue_daily_minor(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
) -> dict[date, int]:
    rows = db.execute(
        select(DailyReport.date, func.coalesce(func.sum(DailyReport.revenue_total), 0))
        .where(
            DailyReport.venue_id == int(venue_id),
            DailyReport.status == 'CLOSED',
            DailyReport.date >= period_start,
            DailyReport.date <= period_end,
        )
        .group_by(DailyReport.date)
    ).all()
    return {row[0]: int(row[1] or 0) * 100 for row in rows}


def _group_expense_recognition_daily_minor(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
) -> dict[date, int]:
    rows = db.execute(
        select(
            ExpenseRecognitionEntry.recognition_date,
            func.coalesce(func.sum(ExpenseRecognitionEntry.amount_minor), 0),
        )
        .select_from(ExpenseRecognitionEntry)
        .join(Expense, Expense.id == ExpenseRecognitionEntry.expense_id)
        .where(
            ExpenseRecognitionEntry.venue_id == int(venue_id),
            ExpenseRecognitionEntry.recognition_date >= period_start,
            ExpenseRecognitionEntry.recognition_date <= period_end,
            Expense.status == 'CONFIRMED',
        )
        .group_by(ExpenseRecognitionEntry.recognition_date)
    ).all()
    return {row[0]: int(row[1] or 0) for row in rows}


def _group_finance_entry_daily_minor(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
    direction: str,
    kind: str,
) -> dict[date, int]:
    rows = db.execute(
        select(FinanceEntry.entry_date, func.coalesce(func.sum(FinanceEntry.amount_minor), 0))
        .where(
            FinanceEntry.venue_id == int(venue_id),
            FinanceEntry.entry_date >= period_start,
            FinanceEntry.entry_date <= period_end,
            FinanceEntry.direction == str(direction).upper(),
            FinanceEntry.kind == str(kind).upper(),
        )
        .group_by(FinanceEntry.entry_date)
    ).all()
    return {row[0]: int(row[1] or 0) for row in rows}


def _group_adjustments_refunds_daily_minor(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
) -> tuple[dict[date, int], dict[date, int]]:
    rows = db.execute(
        select(
            FinanceEntry.entry_date,
            FinanceEntry.direction,
            FinanceEntry.kind,
            func.coalesce(func.sum(FinanceEntry.amount_minor), 0),
        )
        .where(
            FinanceEntry.venue_id == int(venue_id),
            FinanceEntry.entry_date >= period_start,
            FinanceEntry.entry_date <= period_end,
            FinanceEntry.kind.in_(['ADJUSTMENT', 'REFUND']),
        )
        .group_by(FinanceEntry.entry_date, FinanceEntry.direction, FinanceEntry.kind)
    ).all()
    adjustments: dict[date, int] = {}
    refunds: dict[date, int] = {}
    for entry_date, direction, kind, amount_minor in rows:
        sign = 1 if str(direction or '').upper() == 'INCOME' else -1
        target = adjustments if str(kind or '').upper() == 'ADJUSTMENT' else refunds
        target[entry_date] = int(target.get(entry_date, 0)) + sign * int(amount_minor or 0)
    return adjustments, refunds


def _build_finance_daily_series(
    *,
    period_start: date,
    period_end: date,
    revenue_by_date: dict[date, int],
    expense_by_date: dict[date, int],
    payroll_by_date: dict[date, int],
    adjustments_by_date: dict[date, int],
    refunds_by_date: dict[date, int],
) -> list[dict]:
    out: list[dict] = []
    day = period_start
    while day <= period_end:
        revenue_minor = int(revenue_by_date.get(day, 0) or 0)
        expense_minor = int(expense_by_date.get(day, 0) or 0)
        payroll_minor = int(payroll_by_date.get(day, 0) or 0)
        adjustments_minor = int(adjustments_by_date.get(day, 0) or 0)
        refunds_minor = int(refunds_by_date.get(day, 0) or 0)
        total_cost_minor = expense_minor + payroll_minor
        out.append({
            'date': day,
            'revenue_minor': revenue_minor,
            'expense_minor': expense_minor,
            'payroll_minor': payroll_minor,
            'total_cost_minor': total_cost_minor,
            'adjustments_minor': adjustments_minor,
            'refunds_minor': refunds_minor,
            'profit_minor': revenue_minor - total_cost_minor + adjustments_minor + refunds_minor,
        })
        day += timedelta(days=1)
    return out


def _build_cost_structure(*, expense_categories: list[dict], expense_minor: int, payroll_minor: int) -> list[dict]:
    rows = [
        {
            'key': f"expense:{int(item.get('category_id') or 0)}",
            'title': str(item.get('title') or 'Расходы'),
            'amount_minor': int(item.get('amount_minor') or 0),
        }
        for item in expense_categories
        if int(item.get('amount_minor') or 0) > 0
    ]
    if not rows and int(expense_minor or 0) > 0:
        rows.append({'key': 'expense:other', 'title': 'Прочие расходы', 'amount_minor': int(expense_minor)})
    if int(payroll_minor or 0) > 0:
        rows.append({'key': 'payroll', 'title': 'ФОТ', 'amount_minor': int(payroll_minor)})
    rows.sort(key=lambda item: (-int(item['amount_minor']), str(item['title'])))
    return rows


def get_finance_summary(
    *,
    db: Session,
    venue_id: int,
    month: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_series: bool = False,
) -> dict:
    period_start, period_end = resolve_finance_period(month, date_from, date_to)
    _backfill_missing_expense_recognition(db, venue_id=venue_id)

    # DailyReport.revenue_total is the canonical sales axis. Payment-method
    # values may intentionally differ from it when a closed report contains a
    # documented reconciliation discrepancy, so ledger inflow must not change
    # revenue, profit, or margin in the management summary.
    revenue_minor = _sum_closed_report_revenue_minor(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
    )
    expense_minor = _sum_expense_recognition_minor(db, venue_id=venue_id, period_start=period_start, period_end=period_end)
    payroll_by_date = None
    if include_series:
        payroll_by_date = _group_daily_payroll_allocated_minor(
            db,
            venue_id=venue_id,
            period_start=period_start,
            period_end=period_end,
        )
    payroll_minor = _sum_payroll_minor_for_period(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
        daily_amounts=payroll_by_date,
    )
    adjustment_expense_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='EXPENSE', kind='ADJUSTMENT')
    adjustment_income_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='INCOME', kind='ADJUSTMENT')
    refund_income_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='INCOME', kind='REFUND')
    refund_expense_minor = _sum_amount(db, venue_id=venue_id, period_start=period_start, period_end=period_end, direction='EXPENSE', kind='REFUND')

    adjustments_minor = adjustment_income_minor - adjustment_expense_minor
    refunds_minor = refund_income_minor - refund_expense_minor
    total_cost_minor = expense_minor + payroll_minor
    profit_minor = revenue_minor - expense_minor - payroll_minor + adjustments_minor + refunds_minor
    margin_bps = int((profit_minor * 10000) / revenue_minor) if revenue_minor > 0 else None
    expense_ratio_bps = (
        int((expense_minor * 10000) / revenue_minor)
        if revenue_minor > 0
        else None
    )
    payroll_ratio_bps = (
        int((payroll_minor * 10000) / revenue_minor)
        if revenue_minor > 0
        else None
    )
    total_cost_ratio_bps = (
        int((total_cost_minor * 10000) / revenue_minor)
        if revenue_minor > 0
        else None
    )

    draft_stats = _expense_document_stats_for_period(db, venue_id=venue_id, period_start=period_start, period_end=period_end)
    payload = {
        'month': month,
        'period_start': period_start,
        'period_end': period_end,
        'revenue_minor': revenue_minor,
        'expense_minor': expense_minor,
        'expense_without_payroll_minor': expense_minor,
        'payroll_minor': payroll_minor,
        'payroll_expense_minor': payroll_minor,
        'total_cost_minor': total_cost_minor,
        'adjustments_minor': adjustments_minor,
        'refunds_minor': refunds_minor,
        'profit_minor': profit_minor,
        'margin_bps': margin_bps,
        'expense_ratio_bps': expense_ratio_bps,
        'payroll_ratio_bps': payroll_ratio_bps,
        'total_cost_ratio_bps': total_cost_ratio_bps,
        **draft_stats,
    }
    if not include_series:
        return payload

    revenue_by_date = _group_closed_report_revenue_daily_minor(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
    )
    expense_by_date = _group_expense_recognition_daily_minor(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
    )
    if payroll_by_date is None:
        payroll_by_date = {}
    if int(sum(payroll_by_date.values())) <= 0 and payroll_minor > 0:
        payroll_by_date = _group_finance_entry_daily_minor(
            db,
            venue_id=venue_id,
            period_start=period_start,
            period_end=period_end,
            direction='EXPENSE',
            kind='PAYROLL',
        )
    adjustments_by_date, refunds_by_date = _group_adjustments_refunds_daily_minor(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
    )
    expense_categories = _group_expense_categories(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
    )
    payload['daily_series'] = _build_finance_daily_series(
        period_start=period_start,
        period_end=period_end,
        revenue_by_date=revenue_by_date,
        expense_by_date=expense_by_date,
        payroll_by_date=payroll_by_date,
        adjustments_by_date=adjustments_by_date,
        refunds_by_date=refunds_by_date,
    )
    payload['cost_structure'] = _build_cost_structure(
        expense_categories=expense_categories,
        expense_minor=expense_minor,
        payroll_minor=payroll_minor,
    )
    return payload


def get_monthly_finance_summary(
    *,
    db: Session,
    venue_id: int,
    month: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    income_mode: str = 'PAYMENTS',
) -> dict:
    period_start, period_end = resolve_finance_period(month=month, date_from=date_from, date_to=date_to)
    base = get_finance_summary(db=db, venue_id=venue_id, month=month, date_from=date_from, date_to=date_to)
    mode = str(income_mode or 'PAYMENTS').upper()
    if mode not in {'PAYMENTS', 'DEPARTMENTS'}:
        raise ValueError('Bad income_mode, expected PAYMENTS or DEPARTMENTS')
    return {
        **base,
        'month': month or None,
        'income_mode': mode,
        'revenue_breakdown': _group_revenue_breakdown(db, venue_id=venue_id, period_start=period_start, period_end=period_end, income_mode=mode),
        'expense_categories': _group_expense_categories(db, venue_id=venue_id, period_start=period_start, period_end=period_end),
        'payment_method_balances': _group_payment_method_balances(db, venue_id=venue_id, period_start=period_start, period_end=period_end),
    }


def get_day_finance_summary(
    *,
    db: Session,
    venue_id: int,
    target_date: date,
    income_mode: str = 'PAYMENTS',
    shift_slot: str | None = None,
) -> dict:
    period_start = target_date
    period_end = target_date
    mode = str(income_mode or 'PAYMENTS').upper()
    if mode not in {'PAYMENTS', 'DEPARTMENTS'}:
        raise ValueError('Bad income_mode, expected PAYMENTS or DEPARTMENTS')

    slot = _normalize_summary_shift_slot(shift_slot)
    slot_specific = slot is not None

    revenue_minor = _sum_closed_report_revenue_minor(
        db,
        venue_id=venue_id,
        period_start=target_date,
        period_end=target_date,
        shift_slot=slot,
    )
    point_expenses = _group_daily_point_expenses(
        db,
        venue_id=venue_id,
        target_date=target_date,
        shift_slot=slot,
    )
    point_expense_minor = int(sum(int(item['amount_minor'] or 0) for item in point_expenses))
    recurring_expenses = _group_daily_recurring_expenses(
        db,
        venue_id=venue_id,
        target_date=target_date,
        shift_slot=slot,
    )
    recurring_expense_minor = int(sum(int(item['amount_minor'] or 0) for item in recurring_expenses))
    payroll_minor = _sum_payroll_minor_for_period(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
        shift_slot=slot,
    )
    adjustment_expense_minor = _sum_amount(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
        direction='EXPENSE',
        kind='ADJUSTMENT',
        shift_slot=slot,
    )
    adjustment_income_minor = _sum_amount(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
        direction='INCOME',
        kind='ADJUSTMENT',
        shift_slot=slot,
    )
    refund_income_minor = _sum_amount(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
        direction='INCOME',
        kind='REFUND',
        shift_slot=slot,
    )
    refund_expense_minor = _sum_amount(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
        direction='EXPENSE',
        kind='REFUND',
        shift_slot=slot,
    )
    adjustments_minor = adjustment_income_minor - adjustment_expense_minor
    refunds_minor = refund_income_minor - refund_expense_minor
    expense_minor = point_expense_minor + recurring_expense_minor
    total_cost_minor = expense_minor + payroll_minor
    profit_minor = revenue_minor - expense_minor - payroll_minor + adjustments_minor + refunds_minor
    margin_bps = (
        int((profit_minor * 10000) / revenue_minor)
        if revenue_minor > 0
        else None
    )
    expense_ratio_bps = (
        int((expense_minor * 10000) / revenue_minor)
        if revenue_minor > 0
        else None
    )
    payroll_ratio_bps = (
        int((payroll_minor * 10000) / revenue_minor)
        if revenue_minor > 0
        else None
    )
    total_cost_ratio_bps = (
        int((total_cost_minor * 10000) / revenue_minor)
        if revenue_minor > 0
        else None
    )

    draft_stats = _expense_document_stats_for_period(
        db,
        venue_id=venue_id,
        period_start=target_date,
        period_end=target_date,
    )
    return {
        'date': target_date,
        'month': target_date.strftime('%Y-%m'),
        'period_start': period_start,
        'period_end': period_end,
        'revenue_minor': revenue_minor,
        'expense_minor': expense_minor,
        'expense_without_payroll_minor': expense_minor,
        'payroll_minor': payroll_minor,
        'payroll_expense_minor': payroll_minor,
        'total_cost_minor': total_cost_minor,
        'adjustments_minor': adjustments_minor,
        'refunds_minor': refunds_minor,
        'profit_minor': profit_minor,
        'margin_bps': margin_bps,
        'expense_ratio_bps': expense_ratio_bps,
        'payroll_ratio_bps': payroll_ratio_bps,
        'total_cost_ratio_bps': total_cost_ratio_bps,
        'income_mode': mode,
        'shift_slot': slot or 'TOTAL',
        'slot_costs_available': True,
        'slot_profit_available': True,
        'revenue_breakdown': _group_revenue_breakdown(db, venue_id=venue_id, period_start=target_date, period_end=target_date, income_mode=mode, shift_slot=slot),
        'point_expenses': point_expenses,
        'point_expense_minor': point_expense_minor,
        'recurring_expenses': recurring_expenses,
        'recurring_expense_minor': recurring_expense_minor,
        'payment_method_balances': _group_payment_method_balances(db, venue_id=venue_id, period_start=target_date, period_end=target_date, shift_slot=slot),
        **draft_stats,
    }
