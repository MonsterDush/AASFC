from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import FinanceEntry


FINANCE_DIRECTIONS = {"INCOME", "EXPENSE"}
FINANCE_KINDS = {"REVENUE", "EXPENSE", "PAYROLL", "ADJUSTMENT", "REFUND"}


def _normalize_upper(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def create_finance_entry(
    *,
    db: Session,
    venue_id: int,
    entry_date: date,
    amount_minor: int,
    direction: str,
    kind: str,
    source_type: str,
    source_id: int | None = None,
    department_id: int | None = None,
    payment_method_id: int | None = None,
    meta_json: dict[str, Any] | None = None,
) -> FinanceEntry:
    """
    Create a single canonical ledger entry.

    Money must be passed as integer kopecks via amount_minor.
    """
    if not isinstance(amount_minor, int):
        raise ValueError("amount_minor must be int and must store kopecks")
    if amount_minor < 0:
        raise ValueError("amount_minor must be non-negative; use direction for sign")

    direction_norm = _normalize_upper(direction, field_name="direction")
    if direction_norm not in FINANCE_DIRECTIONS:
        raise ValueError(f"Unsupported direction: {direction}")

    kind_norm = _normalize_upper(kind, field_name="kind")
    if kind_norm not in FINANCE_KINDS:
        raise ValueError(f"Unsupported kind: {kind}")

    source_type_norm = str(source_type or "").strip().lower()
    if not source_type_norm:
        raise ValueError("source_type is required")

    entry = FinanceEntry(
        venue_id=int(venue_id),
        entry_date=entry_date,
        amount_minor=amount_minor,
        direction=direction_norm,
        kind=kind_norm,
        source_type=source_type_norm,
        source_id=int(source_id) if source_id is not None else None,
        department_id=int(department_id) if department_id is not None else None,
        payment_method_id=int(payment_method_id) if payment_method_id is not None else None,
        meta_json=deepcopy(meta_json) if meta_json is not None else None,
    )
    db.add(entry)
    return entry


def delete_finance_entries_for_source(
    *,
    db: Session,
    source_type: str,
    source_id: int,
) -> int:
    """
    Delete all ledger entries for one source.

    This is the base primitive for future idempotent rebuilds, e.g.:
    - rebuild revenue entries for one daily report
    - rebuild expense entries for one expense
    """
    source_type_norm = str(source_type or "").strip().lower()
    if not source_type_norm:
        raise ValueError("source_type is required")
    if source_id is None:
        raise ValueError("source_id is required")

    result = db.execute(
        delete(FinanceEntry).where(
            FinanceEntry.source_type == source_type_norm,
            FinanceEntry.source_id == int(source_id),
        )
    )
    return int(result.rowcount or 0)
