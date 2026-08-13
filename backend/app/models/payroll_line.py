from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class PayrollLine(Base):
    __tablename__ = "payroll_lines"
    __table_args__ = (UniqueConstraint("payroll_run_id", "member_user_id", name="uq_payroll_lines_run_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    payroll_run_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    member_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    pay_profile_id: Mapped[int | None] = mapped_column(ForeignKey("pay_profiles.id"), nullable=True)

    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    breakdown_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    payroll_run = relationship("PayrollRun", back_populates="lines")
    venue = relationship("Venue")
    member_user = relationship("User")
    pay_profile = relationship("PayProfile")
