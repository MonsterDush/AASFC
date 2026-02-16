from __future__ import annotations

from datetime import datetime
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Bonus(Base):
    __tablename__ = "bonuses"

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    member_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    date: Mapped[object] = mapped_column(Date, nullable=False, index=True)

    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    venue = relationship("Venue")
    member_user = relationship("User", foreign_keys=[member_user_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])


Index("ix_bonuses_venue_date", Bonus.venue_id, Bonus.date)
Index("ix_bonuses_venue_member_date", Bonus.venue_id, Bonus.member_user_id, Bonus.date)
