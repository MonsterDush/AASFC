from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class PayrollRecalculationLog(Base):
    __tablename__ = "payroll_recalculation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    period_month: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    triggered_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    trigger_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    target_dates_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    venue = relationship("Venue")
    triggered_by_user = relationship("User")
