from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class DayEconomicsMonthPlan(Base):
    __tablename__ = "day_economics_month_plans"
    __table_args__ = (
        UniqueConstraint("venue_id", "month_start", name="uq_day_economics_month_plans_venue_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    month_start: Mapped[date] = mapped_column(Date, index=True, nullable=False)

    revenue_plan_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profit_plan_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revenue_per_assigned_plan_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_user_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
