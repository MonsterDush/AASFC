from __future__ import annotations

from datetime import datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (
        UniqueConstraint("venue_id", "date", name="uq_daily_reports_venue_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    date: Mapped[object] = mapped_column(Date, nullable=False, index=True)

    # legacy numeric fields (kept for backwards compatibility)
    cash: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cashless: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revenue_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tips_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # shift report lifecycle
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")  # DRAFT|CLOSED
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    updated_by_user = relationship("User", foreign_keys=[updated_by_user_id])
    closed_by_user = relationship("User", foreign_keys=[closed_by_user_id])

    values = relationship("DailyReportValue", back_populates="report", cascade="all, delete-orphan")
    audits = relationship("DailyReportAudit", back_populates="report", cascade="all, delete-orphan")
