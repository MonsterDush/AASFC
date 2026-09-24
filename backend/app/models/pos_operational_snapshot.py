from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import utc_now


class POSOperationalSnapshot(Base):
    """Encrypted, compacted realtime state; never a financial source of truth."""

    __tablename__ = "pos_operational_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "object_type", "external_id", "payload_hash", name="uq_pos_operational_snapshots_state"
        ),
        CheckConstraint(
            "object_type IN ('VENUE', 'BUSINESS_SHIFT', 'ORDER', 'STOP_LIST')",
            name="ck_pos_operational_snapshots_object_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_status: Mapped[str | None] = mapped_column(String(96), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    current_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    business_shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("pos_business_shifts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    open_orders_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_tables_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_orders_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    closed_orders_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    closed_revenue_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    connection = relationship("IntegrationConnection")
    venue = relationship("Venue")
    business_shift = relationship("POSBusinessShift")
