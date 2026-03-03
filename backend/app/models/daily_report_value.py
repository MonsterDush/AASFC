from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class DailyReportValue(Base):
    __tablename__ = "daily_report_values"
    __table_args__ = (
        UniqueConstraint("report_id", "kind", "ref_id", name="uq_daily_report_values_report_kind_ref"),
        CheckConstraint("kind in ('PAYMENT','DEPT','KPI')", name="ck_daily_report_values_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    report_id: Mapped[int] = mapped_column(ForeignKey("daily_reports.id", ondelete="CASCADE"), index=True, nullable=False)

    # PAYMENT | DEPT | KPI
    kind: Mapped[str] = mapped_column(String(12), nullable=False)

    # id of PaymentMethod / Department / KpiMetric (depending on kind)
    ref_id: Mapped[int] = mapped_column(Integer, nullable=False)

    value_numeric: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    report = relationship("DailyReport", back_populates="values")
