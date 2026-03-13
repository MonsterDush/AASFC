from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class VenueEconomicsRule(Base):
    __tablename__ = "venue_economics_rules"
    __table_args__ = (
        UniqueConstraint("venue_id", name="uq_venue_economics_rules_venue"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)

    max_expense_ratio_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_payroll_ratio_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_revenue_per_assigned_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_assigned_shift_coverage_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_profit_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warn_on_draft_expenses: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
