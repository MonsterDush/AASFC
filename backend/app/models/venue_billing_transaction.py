from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class VenueBillingTransaction(Base):
    __tablename__ = "venue_billing_transaction"

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)

    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    days_added: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    provider_invoice_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    provider_payload_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
    created_by_user = relationship("User")
