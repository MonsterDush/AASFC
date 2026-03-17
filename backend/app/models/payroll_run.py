from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class PayrollRun(Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (
        UniqueConstraint("venue_id", "period_month", name="uq_payroll_runs_venue_period_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    period_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    calculated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    total_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    venue = relationship("Venue")
    calculated_by_user = relationship("User")
    lines = relationship("PayrollLine", back_populates="payroll_run", cascade="all, delete-orphan")
