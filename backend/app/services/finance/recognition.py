from __future__ import annotations

from datetime import date, timedelta
import calendar

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseAllocation, ExpenseRecognitionEntry, Venue


def _normalize_expense_shift_slot(value: str | None) -> str:
    slot = str(value or "TOTAL").strip().upper()
    return slot if slot in {"TOTAL", "DAY", "NIGHT"} else "TOTAL"


def _normalize_available_shift_slots(values: list[str] | tuple[str, ...] | None) -> list[str]:
    out: list[str] = []
    for value in values or ["DAY"]:
        slot = str(value or "").strip().upper()
        if slot in {"DAY", "NIGHT"} and slot not in out:
            out.append(slot)
    return out or ["DAY"]


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


def build_expense_recognition_plan(
    *,
    expense: Expense,
    allocations: list[ExpenseAllocation],
    available_shift_slots: list[str] | tuple[str, ...] | None = None,
) -> list[tuple[date, int, dict]]:
    plan: list[tuple[date, int, dict]] = []
    expense_slot = _normalize_expense_shift_slot(getattr(expense, "shift_slot", "TOTAL"))
    venue_slots = _normalize_available_shift_slots(available_shift_slots)
    recognition_slots = venue_slots if expense_slot == "TOTAL" else [expense_slot]
    for idx, allocation in enumerate(sorted(allocations, key=lambda x: (x.month, x.id or 0))):
        month_start = allocation.month.replace(day=1)
        last_day = calendar.monthrange(month_start.year, month_start.month)[1]
        month_end = month_start.replace(day=last_day)
        period_days = (month_end - month_start).days + 1
        recognition_points = [
            (month_start + timedelta(days=day_idx), day_idx, shift_slot, shift_index)
            for day_idx in range(period_days)
            for shift_index, shift_slot in enumerate(recognition_slots)
        ]
        total_minor = int(allocation.amount_minor or 0)
        base_minor = total_minor // len(recognition_points)
        remainder_minor = total_minor % len(recognition_points)
        for recognition_index, (recognition_date, day_idx, shift_slot, shift_index) in enumerate(recognition_points):
            amount_minor = base_minor + (1 if recognition_index < remainder_minor else 0)
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
                        "days_in_period": period_days,
                        "recognition_index": recognition_index,
                        "recognitions_in_period": len(recognition_points),
                        "shift_slot": shift_slot,
                        "shift_index": shift_index,
                        "shifts_in_period": len(recognition_slots),
                        "expense_shift_slot": expense_slot,
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
    venue = db.execute(
        select(Venue).where(Venue.id == int(expense.venue_id))
    ).scalar_one_or_none()
    available_shift_slots = ["DAY", "NIGHT"] if bool(getattr(venue, "night_shifts_enabled", False)) else ["DAY"]
    plan = build_expense_recognition_plan(
        expense=expense,
        allocations=allocation_rows,
        available_shift_slots=available_shift_slots,
    )
    created: list[ExpenseRecognitionEntry] = []
    for recognition_date, amount_minor, meta_json in plan:
        entry = ExpenseRecognitionEntry(
            expense_id=int(expense.id),
            venue_id=int(expense.venue_id),
            recognition_date=recognition_date,
            shift_slot=str(meta_json.get("shift_slot") or "DAY"),
            amount_minor=int(amount_minor),
            meta_json=meta_json,
        )
        db.add(entry)
        created.append(entry)
    return created


def delete_expense_recognition_entries_for_expense(*, db: Session, expense_id: int) -> int:
    deleted = db.execute(delete(ExpenseRecognitionEntry).where(ExpenseRecognitionEntry.expense_id == int(expense_id)))
    return int(deleted.rowcount or 0)
