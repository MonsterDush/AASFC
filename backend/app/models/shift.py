from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Shift(Base):
    """A shift for a specific venue and date, based on a reusable interval."""

    __tablename__ = "shifts"
    __table_args__ = (
        UniqueConstraint("venue_id", "date", "interval_id", name="uq_shifts_venue_date_interval"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True)
    date: Mapped[object] = mapped_column(Date, nullable=False, index=True)

    interval_id: Mapped[int] = mapped_column(ForeignKey("shift_intervals.id"), index=True)

    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    venue = relationship("Venue")
    interval = relationship("ShiftInterval")
    assignments = relationship("ShiftAssignment", back_populates="shift", cascade="all, delete-orphan")
