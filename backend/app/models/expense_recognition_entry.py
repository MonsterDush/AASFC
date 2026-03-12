from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ExpenseRecognitionEntry(Base):
    __tablename__ = "expense_recognition_entries"
    __table_args__ = (
        CheckConstraint("amount_minor >= 0", name="ck_expense_recognition_entries_amount_non_negative"),
        Index("ix_expense_recognition_entries_venue_date", "venue_id", "recognition_date"),
        Index("ix_expense_recognition_entries_expense", "expense_id", "recognition_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"), nullable=False, index=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), nullable=False, index=True)
    recognition_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meta_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    expense = relationship("Expense")
    venue = relationship("Venue")
