from __future__ import annotations

from datetime import datetime
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Writeoff(Base):
    __tablename__ = "writeoffs"

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    # If null => writeoff applies to venue (not a specific employee)
    member_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)

    date: Mapped[object] = mapped_column(Date, nullable=False, index=True)

    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    venue = relationship("Venue")
    member_user = relationship("User", foreign_keys=[member_user_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])


Index("ix_writeoffs_venue_date", Writeoff.venue_id, Writeoff.date)
Index("ix_writeoffs_venue_member_date", Writeoff.venue_id, Writeoff.member_user_id, Writeoff.date)
