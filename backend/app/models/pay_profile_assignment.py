from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class PayProfileAssignment(Base):
    __tablename__ = "pay_profile_assignments"
    __table_args__ = (
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="ck_pay_profile_assignments_dates"
        ),
        Index("ix_pay_profile_assignments_venue_member_dates", "venue_id", "member_user_id", "start_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    pay_profile_id: Mapped[int] = mapped_column(
        ForeignKey("pay_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    member_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
    pay_profile = relationship("PayProfile", back_populates="assignments")
    member_user = relationship("User")
