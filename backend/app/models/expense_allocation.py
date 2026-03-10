from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ExpenseAllocation(Base):
    __tablename__ = "expense_allocations"
    __table_args__ = (
        CheckConstraint("amount_minor >= 0", name="ck_expense_allocations_amount_minor_non_negative"),
        UniqueConstraint("expense_id", "month", name="uq_expense_allocations_expense_month"),
        Index("ix_expense_allocations_venue_month", "venue_id", "month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"), index=True, nullable=False)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)

    month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    expense = relationship("Expense", back_populates="allocations")
    venue = relationship("Venue")
