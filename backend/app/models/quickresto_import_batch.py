from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_PORTABLE_JSON = JSON().with_variant(JSONB(), "postgresql")


class QuickRestoImportBatch(Base):
    __tablename__ = "quickresto_import_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="ck_quickresto_import_batches_status",
        ),
        CheckConstraint(
            "period_end_exclusive > period_start",
            name="ck_quickresto_import_batches_period",
        ),
        CheckConstraint(
            "next_period_start >= period_start AND next_period_start <= period_end_exclusive",
            name="ck_quickresto_import_batches_cursor",
        ),
        CheckConstraint(
            "total_periods > 0 AND completed_periods >= 0 "
            "AND completed_periods <= total_periods AND partial_periods >= 0 "
            "AND partial_periods <= completed_periods AND retry_count >= 0",
            name="ck_quickresto_import_batches_progress",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trigger: Mapped[str] = mapped_column(String(24), nullable=False)
    force_full: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default="PENDING")
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end_exclusive: Mapped[date] = mapped_column(Date, nullable=False)
    next_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    current_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_period_end_exclusive: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_periods: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_periods: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    partial_periods: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("quickresto_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(_PORTABLE_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    connection = relationship("QuickRestoConnection", back_populates="import_batches")
    last_sync_run = relationship("QuickRestoSyncRun", foreign_keys=[last_sync_run_id])
