from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class BillingPromoRedemption(Base):
    __tablename__ = "billing_promo_redemption"
    __table_args__ = (UniqueConstraint("venue_id", name="uq_billing_promo_redemption_venue_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    promo_code_id: Mapped[int] = mapped_column(
        ForeignKey("billing_promo_code.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    billing_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("venue_billing_transaction.id", ondelete="SET NULL"), nullable=True, unique=True, index=True
    )

    promo_code_value: Mapped[str] = mapped_column(String(64), nullable=False)
    discount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    free_days_added: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    promo_code = relationship("BillingPromoCode")
    venue = relationship("Venue")
    billing_transaction = relationship("VenueBillingTransaction")
