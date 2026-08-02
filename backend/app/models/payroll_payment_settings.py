from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class PayrollPaymentSettings(Base):
    __tablename__ = "payroll_payment_settings"
    __table_args__ = (
        UniqueConstraint("venue_id", name="uq_payroll_payment_settings_venue"),
        CheckConstraint(
            "cadence IN ('DAILY', 'WEEKLY', 'MONTHLY')",
            name="ck_payroll_payment_settings_cadence",
        ),
        CheckConstraint(
            "weekly_payment_weekday IS NULL OR (weekly_payment_weekday >= 0 AND weekly_payment_weekday <= 6)",
            name="ck_payroll_payment_settings_weekday",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_method_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_methods.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cadence: Mapped[str] = mapped_column(String(16), nullable=False, default="MONTHLY", server_default="MONTHLY")
    weekly_payment_weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_rules_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
    payment_method = relationship("PaymentMethod")
