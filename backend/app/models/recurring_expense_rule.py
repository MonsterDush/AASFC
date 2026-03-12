from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class RecurringExpenseRule(Base):
    __tablename__ = "recurring_expense_rules"
    __table_args__ = (
        CheckConstraint("day_of_month >= 1 AND day_of_month <= 31", name="ck_recurring_expense_rules_day_of_month_range"),
        CheckConstraint("spread_months >= 1", name="ck_recurring_expense_rules_spread_months_positive"),
        CheckConstraint("amount_minor IS NULL OR amount_minor >= 0", name="ck_recurring_expense_rules_amount_minor_non_negative"),
        CheckConstraint("percent_bps IS NULL OR percent_bps >= 0", name="ck_recurring_expense_rules_percent_bps_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)

    title: Mapped[str] = mapped_column(String(160), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("expense_categories.id"), index=True, nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), index=True, nullable=True)
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"), index=True, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    frequency: Mapped[str] = mapped_column(String(16), nullable=False, default="MONTHLY")
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    generation_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="FIXED")
    amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    percent_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spread_months: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
    category = relationship("ExpenseCategory")
    supplier = relationship("Supplier")
    payment_method = relationship("PaymentMethod")
    created_by_user = relationship("User")
    payment_method_links = relationship(
        "RecurringExpenseRulePaymentMethod",
        back_populates="rule",
        cascade="all, delete-orphan",
    )
