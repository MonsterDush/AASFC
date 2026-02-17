from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, UniqueConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ShiftAssignment(Base):
    """Assignment of a specific venue position (member) to a shift."""

    __tablename__ = "shift_assignments"
    __table_args__ = (
        UniqueConstraint("shift_id", "member_user_id", name="uq_shift_assignment_member"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)

    # Store both member_user_id and venue_position_id for MVP simplicity.
    member_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    venue_position_id: Mapped[int] = mapped_column(ForeignKey("venue_positions.id"), index=True)


    # When we last sent a "shift starts soon" reminder (best-effort). Prevents duplicates.
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    shift = relationship("Shift", back_populates="assignments")
    member_user = relationship("User")
    venue_position = relationship("VenuePosition")
