from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class PositionPayProfilePeriod(Base):
    """Effective-dated payroll profile for one employee position."""

    __tablename__ = "position_pay_profile_periods"
    __table_args__ = (
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_position_pay_profile_periods_dates",
        ),
        Index(
            "ix_position_pay_profile_periods_lookup",
            "venue_id",
            "member_user_id",
            "venue_position_id",
            "valid_from",
            "valid_to",
        ),
        Index(
            "uq_position_pay_profile_periods_open_position",
            "venue_position_id",
            unique=True,
            postgresql_where=text("is_active = true AND valid_to IS NULL"),
            sqlite_where=text("is_active = true AND valid_to IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), index=True, nullable=False)
    venue_position_id: Mapped[int] = mapped_column(
        ForeignKey("venue_positions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    member_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    pay_profile_id: Mapped[int] = mapped_column(
        ForeignKey("pay_profiles.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
    venue_position = relationship("VenuePosition")
    member_user = relationship("User")
    pay_profile = relationship("PayProfile")
