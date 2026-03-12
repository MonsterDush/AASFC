from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount_minor >= 0", name="ck_expenses_amount_minor_non_negative"),
        CheckConstraint("spread_months >= 1", name="ck_expenses_spread_months_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)

    category_id: Mapped[int] = mapped_column(ForeignKey("expense_categories.id"), index=True, nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), index=True, nullable=True)
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"), index=True, nullable=True)
    recurring_rule_id: Mapped[int | None] = mapped_column(ForeignKey("recurring_expense_rules.id"), index=True, nullable=True)

    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    generated_for_month: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    spread_months: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='CONFIRMED')

    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
    category = relationship("ExpenseCategory")
    supplier = relationship("Supplier")
    payment_method = relationship("PaymentMethod")
    recurring_rule = relationship("RecurringExpenseRule")
    created_by_user = relationship("User")
    allocations = relationship("ExpenseAllocation", back_populates="expense", cascade="all, delete-orphan")
