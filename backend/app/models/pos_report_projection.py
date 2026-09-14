from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import PORTABLE_JSON, utc_now


class POSReportProjection(Base):
    __tablename__ = "pos_report_projections"
    __table_args__ = (
        UniqueConstraint("daily_report_id", name="uq_pos_report_projections_report"),
        UniqueConstraint(
            "connection_id", "business_date", "shift_slot", name="uq_pos_report_projections_connection_date_slot"
        ),
        CheckConstraint("shift_slot IN ('DAY', 'NIGHT')", name="ck_pos_report_projections_shift_slot"),
        CheckConstraint(
            "status IN ('PENDING', 'MATCHED', 'MISMATCH', 'INCOMPLETE', 'FAILED')",
            name="ck_pos_report_projections_status",
        ),
        CheckConstraint("mapping_version >= 1 AND policy_version >= 1", name="ck_pos_report_projections_versions"),
        CheckConstraint("shift_count >= 0", name="ck_pos_report_projections_shift_count"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_report_id: Mapped[int] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    shift_slot: Mapped[str] = mapped_column(String(16), nullable=False, default="DAY", server_default="DAY")
    aggregate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    shift_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    canonical_coverage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING", server_default="PENDING")
    summary_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    daily_report = relationship("DailyReport")
    connection = relationship("IntegrationConnection")
    last_sync_run = relationship("IntegrationSyncRun")
