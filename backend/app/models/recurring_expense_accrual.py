from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class RecurringExpenseAccrual(Base):
    __tablename__ = "recurring_expense_accruals"
    __table_args__ = (
        CheckConstraint("amount_minor >= 0", name="ck_recurring_expense_accruals_amount_non_negative"),
        CheckConstraint("basis_minor IS NULL OR basis_minor >= 0", name="ck_recurring_expense_accruals_basis_non_negative"),
        UniqueConstraint("rule_id", "accrual_date", name="uq_recurring_expense_accrual_rule_date"),
        Index("ix_recurring_expense_accruals_venue_date", "venue_id", "accrual_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("recurring_expense_rules.id"), nullable=False, index=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), nullable=False, index=True)
    accrual_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    basis_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rule = relationship("RecurringExpenseRule")
    venue = relationship("Venue")
