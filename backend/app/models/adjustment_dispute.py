from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class AdjustmentDispute(Base):
    """Dispute thread for a specific adjustment."""

    __tablename__ = "adjustment_disputes"

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    adjustment_id: Mapped[int] = mapped_column(ForeignKey("adjustments.id"), index=True, nullable=False)

    # legacy column (older schema) may exist; we keep it optional and no longer use it in code
    message: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")  # OPEN | CLOSED
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    venue = relationship("Venue")
    adjustment = relationship("Adjustment")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    resolved_by_user = relationship("User", foreign_keys=[resolved_by_user_id])

    comments = relationship(
        "AdjustmentDisputeComment",
        back_populates="dispute",
        order_by="AdjustmentDisputeComment.created_at.asc()",
        lazy="selectin",
        cascade="all, delete-orphan",
    )



Index("ix_adj_disputes_venue_adjustment", AdjustmentDispute.venue_id, AdjustmentDispute.adjustment_id)
