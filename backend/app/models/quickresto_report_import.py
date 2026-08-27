from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuickRestoReportImport(Base):
    __tablename__ = "quickresto_report_imports"
    __table_args__ = (
        UniqueConstraint("connection_id", "business_date", "shift_slot", name="uq_quickresto_report_import_date_slot"),
        UniqueConstraint("daily_report_id", name="uq_quickresto_report_import_report"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    daily_report_id: Mapped[int] = mapped_column(ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    shift_slot: Mapped[str] = mapped_column(String(16), nullable=False, default="DAY", server_default="DAY")
    aggregate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    shift_count: Mapped[int] = mapped_column(Integer, nullable=False)
    writeoff_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discount_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    last_sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("quickresto_sync_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    connection = relationship("QuickRestoConnection")
    daily_report = relationship("DailyReport")
    last_sync_run = relationship("QuickRestoSyncRun")
