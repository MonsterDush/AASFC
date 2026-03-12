from __future__ import annotations

from datetime import date, timedelta
import calendar

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseAllocation, ExpenseRecognitionEntry


def build_daily_spread_plan(*, amount_minor: int, period_start: date, period_end: date) -> list[tuple[date, int]]:
    if not isinstance(amount_minor, int):
        raise ValueError("amount_minor must be int and must store kopecks")
    if amount_minor < 0:
        raise ValueError("amount_minor must be non-negative")
    if period_end < period_start:
        raise ValueError("period_end must be >= period_start")

    total_days = (period_end - period_start).days + 1
    base = amount_minor // total_days
    remainder = amount_minor % total_days
    out: list[tuple[date, int]] = []
    for idx in range(total_days):
        current = period_start + timedelta(days=idx)
        out.append((current, base + (1 if idx < remainder else 0)))
    return out


def build_expense_recognition_plan(*, expense: Expense, allocations: list[ExpenseAllocation]) -> list[tuple[date, int, dict]]:
    plan: list[tuple[date, int, dict]] = []
    for idx, allocation in enumerate(sorted(allocations, key=lambda x: (x.month, x.id or 0))):
        month_start = allocation.month.replace(day=1)
        last_day = calendar.monthrange(month_start.year, month_start.month)[1]
        month_end = month_start.replace(day=last_day)
        daily_plan = build_daily_spread_plan(
            amount_minor=int(allocation.amount_minor or 0),
            period_start=month_start,
            period_end=month_end,
        )
        for day_idx, (recognition_date, amount_minor) in enumerate(daily_plan):
            if amount_minor <= 0:
                continue
            plan.append(
                (
                    recognition_date,
                    amount_minor,
                    {
                        "expense_date": expense.expense_date.isoformat() if expense.expense_date else None,
                        "allocation_month": allocation.month.isoformat() if allocation.month else None,
                        "allocation_index": idx,
                        "day_index": day_idx,
                        "days_in_period": len(daily_plan),
                        "spread_months": int(expense.spread_months or 1),
                        "category_id": int(expense.category_id),
                        "supplier_id": int(expense.supplier_id) if expense.supplier_id is not None else None,
                        "payment_method_id": int(expense.payment_method_id) if expense.payment_method_id is not None else None,
                        "recurring_rule_id": int(expense.recurring_rule_id) if expense.recurring_rule_id is not None else None,
                    },
                )
            )
    return plan


def rebuild_expense_recognition_entries_for_expense(*, db: Session, expense: Expense, allocations: list[ExpenseAllocation] | None = None) -> list[ExpenseRecognitionEntry]:
    if expense.id is None:
        raise ValueError("Expense must be flushed before recognition rebuild")

    db.execute(delete(ExpenseRecognitionEntry).where(ExpenseRecognitionEntry.expense_id == int(expense.id)))

    expense_status = str(getattr(expense, "status", "CONFIRMED") or "CONFIRMED").upper()
    if expense_status != "CONFIRMED":
        return []

    allocation_rows = allocations if allocations is not None else list(
        db.scalars(
            select(ExpenseAllocation)
            .where(ExpenseAllocation.expense_id == int(expense.id))
            .order_by(ExpenseAllocation.month.asc(), ExpenseAllocation.id.asc())
        ).all()
    )
    plan = build_expense_recognition_plan(expense=expense, allocations=allocation_rows)
    created: list[ExpenseRecognitionEntry] = []
    for recognition_date, amount_minor, meta_json in plan:
        entry = ExpenseRecognitionEntry(
            expense_id=int(expense.id),
            venue_id=int(expense.venue_id),
            recognition_date=recognition_date,
            amount_minor=int(amount_minor),
            meta_json=meta_json,
        )
        db.add(entry)
        created.append(entry)
    return created


def delete_expense_recognition_entries_for_expense(*, db: Session, expense_id: int) -> int:
    deleted = db.execute(delete(ExpenseRecognitionEntry).where(ExpenseRecognitionEntry.expense_id == int(expense_id)))
    return int(deleted.rowcount or 0)
