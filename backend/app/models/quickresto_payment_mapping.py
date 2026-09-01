from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuickRestoPaymentMapping(Base):
    __tablename__ = "quickresto_payment_mappings"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_quickresto_payment_mapping_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    external_name: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_mechanism: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payment_method_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_methods.id", ondelete="SET NULL"), nullable=True
    )
    excluded_from_revenue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    allowed_sale_place_ids_json: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    connection = relationship("QuickRestoConnection", back_populates="payment_mappings")
    payment_method = relationship("PaymentMethod")
