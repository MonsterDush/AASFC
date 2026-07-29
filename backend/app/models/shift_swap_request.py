from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ShiftSwapRequest(Base):
    """A request to hand an existing assignment to another venue member."""

    __tablename__ = "shift_swap_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'APPROVED', 'REJECTED', 'CANCELLED')",
            name="ck_shift_swap_requests_status_valid",
        ),
        CheckConstraint(
            "replacement_user_id IS NULL OR replacement_user_id <> requester_user_id",
            name="ck_shift_swap_requests_different_users",
        ),
        Index(
            "uq_shift_swap_requests_open_assignment",
            "assignment_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
            sqlite_where=text("status = 'OPEN'"),
        ),
        Index(
            "ix_shift_swap_requests_venue_status",
            "venue_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), nullable=False)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), nullable=False, index=True)
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shift_assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requester_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    replacement_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    replacement_position_id: Mapped[int | None] = mapped_column(
        ForeignKey("venue_positions.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="OPEN",
        server_default="OPEN",
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    manager_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    shift = relationship("Shift")
    assignment = relationship("ShiftAssignment")
    requester_user = relationship("User", foreign_keys=[requester_user_id])
    replacement_user = relationship("User", foreign_keys=[replacement_user_id])
    replacement_position = relationship("VenuePosition")
    decided_by_user = relationship("User", foreign_keys=[decided_by_user_id])
