from __future__ import annotations

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class RecurringExpenseRulePaymentMethod(Base):
    __tablename__ = "recurring_expense_rule_payment_methods"
    __table_args__ = (
        UniqueConstraint("rule_id", "payment_method_id", name="uq_recurring_expense_rule_payment_method"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("recurring_expense_rules.id"), index=True, nullable=False)
    payment_method_id: Mapped[int] = mapped_column(ForeignKey("payment_methods.id"), index=True, nullable=False)

    rule = relationship("RecurringExpenseRule", back_populates="payment_method_links")
    payment_method = relationship("PaymentMethod")
