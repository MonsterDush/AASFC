from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseAllocation
from app.services.finance.ledger import create_finance_entry, delete_finance_entries_for_source
from app.services.finance.recognition import (
    delete_expense_recognition_entries_for_expense,
    rebuild_expense_recognition_entries_for_expense,
)


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, months: int) -> date:
    month_index = (value.month - 1) + months
    year = value.year + month_index // 12
    month = (month_index % 12) + 1
    return date(year, month, 1)


def build_expense_allocation_plan(*, amount_minor: int, expense_date: date, spread_months: int) -> list[tuple[date, int]]:
    if not isinstance(amount_minor, int):
        raise ValueError("amount_minor must be int and must store kopecks")
    if amount_minor < 0:
        raise ValueError("amount_minor must be non-negative")
    if spread_months < 1:
        raise ValueError("spread_months must be >= 1")

    first_month = _month_start(expense_date)
    base = amount_minor // spread_months
    remainder = amount_minor % spread_months

    plan: list[tuple[date, int]] = []
    for index in range(spread_months):
        month = _add_months(first_month, index)
        amount_for_month = base + (1 if index < remainder else 0)
        plan.append((month, amount_for_month))
    return plan


def rebuild_expense_allocations_for_expense(*, db: Session, expense: Expense) -> list[ExpenseAllocation]:
    if expense.id is None:
        raise ValueError("Expense must be flushed before allocations rebuild")

    db.execute(delete(ExpenseAllocation).where(ExpenseAllocation.expense_id == int(expense.id)))
    delete_finance_entries_for_source(db=db, source_type="expense", source_id=int(expense.id))
    delete_expense_recognition_entries_for_expense(db=db, expense_id=int(expense.id))

    expense_status = str(getattr(expense, 'status', 'CONFIRMED') or 'CONFIRMED').upper()
    if expense_status != 'CONFIRMED':
        return []

    allocations: list[ExpenseAllocation] = []
    plan = build_expense_allocation_plan(
        amount_minor=int(expense.amount_minor or 0),
        expense_date=expense.expense_date,
        spread_months=int(expense.spread_months or 1),
    )

    for month, amount_minor in plan:
        allocation = ExpenseAllocation(
            expense_id=int(expense.id),
            venue_id=int(expense.venue_id),
            month=month,
            amount_minor=amount_minor,
        )
        db.add(allocation)
        allocations.append(allocation)

    create_finance_entry(
        db=db,
        venue_id=int(expense.venue_id),
        entry_date=expense.expense_date,
        amount_minor=int(expense.amount_minor or 0),
        direction="EXPENSE",
        kind="EXPENSE",
        source_type="expense",
        source_id=int(expense.id),
        payment_method_id=int(expense.payment_method_id) if expense.payment_method_id is not None else None,
        meta_json={
            "expense_date": expense.expense_date.isoformat(),
            "spread_months": int(expense.spread_months or 1),
            "category_id": int(expense.category_id),
            "supplier_id": int(expense.supplier_id) if expense.supplier_id is not None else None,
            "payment_method_id": int(expense.payment_method_id) if expense.payment_method_id is not None else None,
            "recurring_rule_id": int(expense.recurring_rule_id) if expense.recurring_rule_id is not None else None,
        },
    )
    rebuild_expense_recognition_entries_for_expense(db=db, expense=expense, allocations=allocations)
    return allocations


def delete_expense_allocations_for_expense(*, db: Session, expense_id: int) -> int:
    deleted = db.execute(delete(ExpenseAllocation).where(ExpenseAllocation.expense_id == int(expense_id)))
    delete_finance_entries_for_source(db=db, source_type="expense", source_id=int(expense_id))
    delete_expense_recognition_entries_for_expense(db=db, expense_id=int(expense_id))
    return int(deleted.rowcount or 0)


def list_expense_allocations(*, db: Session, expense_id: int) -> list[ExpenseAllocation]:
    return list(
        db.scalars(
            select(ExpenseAllocation)
            .where(ExpenseAllocation.expense_id == int(expense_id))
            .order_by(ExpenseAllocation.month.asc(), ExpenseAllocation.id.asc())
        ).all()
    )
