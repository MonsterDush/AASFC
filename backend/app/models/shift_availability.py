from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ShiftAvailability(Base):
    """A staff member's availability for a concrete reporting date and shift slot."""

    __tablename__ = "shift_availabilities"
    __table_args__ = (
        CheckConstraint("shift_slot IN ('DAY', 'NIGHT')", name="ck_shift_availabilities_slot_valid"),
        CheckConstraint(
            "status IN ('AVAILABLE', 'UNAVAILABLE')",
            name="ck_shift_availabilities_status_valid",
        ),
        UniqueConstraint(
            "venue_id",
            "member_user_id",
            "date",
            "shift_slot",
            name="uq_shift_availability_member_date_slot",
        ),
        Index(
            "ix_shift_availabilities_venue_date_slot",
            "venue_id",
            "date",
            "shift_slot",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), nullable=False)
    member_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_slot: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="DAY",
        server_default="DAY",
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    venue = relationship("Venue")
    member_user = relationship("User")
