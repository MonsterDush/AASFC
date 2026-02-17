from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Adjustment(Base):
    __tablename__ = "adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)  # penalty | writeoff | bonus

    # null => adjustment for venue (allowed for writeoffs)
    member_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)

    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
    member_user = relationship("User", foreign_keys=[member_user_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    updated_by_user = relationship("User", foreign_keys=[updated_by_user_id])


