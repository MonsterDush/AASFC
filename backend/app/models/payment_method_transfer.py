from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class PaymentMethodTransfer(Base):
    __tablename__ = "payment_method_transfers"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_payment_method_transfers_amount_positive"),
        CheckConstraint("from_payment_method_id <> to_payment_method_id", name="ck_payment_method_transfers_methods_not_equal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    from_payment_method_id: Mapped[int] = mapped_column(ForeignKey("payment_methods.id"), index=True, nullable=False)
    to_payment_method_id: Mapped[int] = mapped_column(ForeignKey("payment_methods.id"), index=True, nullable=False)
    transfer_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="CONFIRMED")
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
    from_payment_method = relationship("PaymentMethod", foreign_keys=[from_payment_method_id])
    to_payment_method = relationship("PaymentMethod", foreign_keys=[to_payment_method_id])
    created_by_user = relationship("User")
