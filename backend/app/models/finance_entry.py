from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class FinanceEntry(Base):
    """
    Canonical finance ledger entry.

    IMPORTANT:
    - amount_minor stores money in kopecks (integer), never float.
    - amount_minor is always absolute/non-negative.
    - direction defines whether it is income or expense.
    """

    __tablename__ = "finance_entries"
    __table_args__ = (
        CheckConstraint("amount_minor >= 0", name="ck_finance_entries_amount_minor_non_negative"),
        Index("ix_finance_entries_venue_entry_date", "venue_id", "entry_date"),
        Index("ix_finance_entries_venue_kind_entry_date", "venue_id", "kind", "entry_date"),
        Index("ix_finance_entries_source", "source_type", "source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)

    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)  # INCOME | EXPENSE
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # REVENUE | EXPENSE | PAYROLL | ADJUSTMENT | REFUND

    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # daily_report | expense | payroll_run | adjustment
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"), nullable=True)

    meta_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    venue = relationship("Venue")
    department = relationship("Department")
    payment_method = relationship("PaymentMethod")
