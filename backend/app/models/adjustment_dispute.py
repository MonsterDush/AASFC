from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class AdjustmentDispute(Base):
    """Dispute for penalty/writeoff/bonus.

    target_type: 'penalty' | 'writeoff' | 'bonus'
    target_id: id of the corresponding row.
    """

    __tablename__ = "adjustment_disputes"

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)

    target_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")  # OPEN | CLOSED
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    venue = relationship("Venue")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    resolved_by_user = relationship("User", foreign_keys=[resolved_by_user_id])


Index("ix_adj_disputes_venue_target", AdjustmentDispute.venue_id, AdjustmentDispute.target_type, AdjustmentDispute.target_id)
