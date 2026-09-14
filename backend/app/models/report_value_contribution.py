from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import utc_now


class ReportValueContribution(Base):
    __tablename__ = "report_value_contributions"
    __table_args__ = (
        UniqueConstraint(
            "report_id",
            "kind",
            "ref_id",
            "source_type",
            "source_id",
            name="uq_report_value_contributions_source",
        ),
        CheckConstraint(
            "source_type IN ('MANUAL', 'POS', 'ADJUSTMENT')",
            name="ck_report_value_contributions_source_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    value_numeric: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    report = relationship("DailyReport")
