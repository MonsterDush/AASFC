from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ShiftInterval(Base):
    """Reusable time interval for shifts inside a venue (e.g. 12:00-20:00)."""

    __tablename__ = "shift_intervals"
    __table_args__ = (UniqueConstraint("venue_id", "title", name="uq_shift_intervals_title"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("venue_positions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    start_time: Mapped[object] = mapped_column(Time, nullable=False)
    end_time: Mapped[object] = mapped_column(Time, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    venue = relationship("Venue")
    position = relationship("VenuePosition")


class ShiftIntervalPosition(Base):
    __tablename__ = "shift_interval_positions"

    interval_id: Mapped[int] = mapped_column(ForeignKey("shift_intervals.id", ondelete="CASCADE"), primary_key=True)
    position_id: Mapped[int] = mapped_column(
        ForeignKey("venue_positions.id", ondelete="CASCADE"), primary_key=True, index=True
    )
