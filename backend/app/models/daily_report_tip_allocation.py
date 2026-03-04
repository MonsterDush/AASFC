from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class DailyReportTipAllocation(Base):
    __tablename__ = "daily_report_tip_allocations"
    __table_args__ = (
        UniqueConstraint("report_id", "user_id", name="uq_tip_alloc_report_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    report_id: Mapped[int] = mapped_column(ForeignKey("daily_reports.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)

    # Money in integer units (same convention as daily_reports.tips_total)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    split_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="EQUAL")  # EQUAL | WEIGHTED_BY_POSITION (stub)
    meta_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    report = relationship("DailyReport")
    user = relationship("User")
