from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import PORTABLE_JSON, utc_now


class IntegrationImportBatch(Base):
    __tablename__ = "integration_import_batches"
    __table_args__ = (
        UniqueConstraint("connection_id", "active_guard", name="uq_integration_import_batches_active"),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name="ck_integration_import_batches_status",
        ),
        CheckConstraint(
            "mode IN ('FULL', 'INCREMENTAL')",
            name="ck_integration_import_batches_mode",
        ),
        CheckConstraint(
            "period_end_exclusive > period_start",
            name="ck_integration_import_batches_period",
        ),
        CheckConstraint(
            "next_period_start >= period_start AND next_period_start <= period_end_exclusive",
            name="ck_integration_import_batches_cursor",
        ),
        CheckConstraint(
            "total_chunks > 0 AND completed_chunks >= 0 "
            "AND completed_chunks <= total_chunks AND partial_chunks >= 0 "
            "AND partial_chunks <= completed_chunks AND retry_count >= 0",
            name="ck_integration_import_batches_progress",
        ),
        CheckConstraint(
            "active_guard IS NULL OR active_guard = 1",
            name="ck_integration_import_batches_active_guard",
        ),
        CheckConstraint(
            "coverage_end_exclusive IS NULL OR coverage_start IS NULL OR coverage_end_exclusive > coverage_start",
            name="ck_integration_import_batches_coverage",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sync_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_sync_jobs.id", ondelete="SET NULL"), nullable=True, unique=True, index=True
    )
    last_sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trigger: Mapped[str] = mapped_column(String(24), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default="PENDING")
    active_guard: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end_exclusive: Mapped[date] = mapped_column(Date, nullable=False)
    next_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    current_chunk_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    partial_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    coverage_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    coverage_end_exclusive: Mapped[date | None] = mapped_column(Date, nullable=True)
    counters_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    connection = relationship("IntegrationConnection")
    requested_by_user = relationship("User")
    sync_job = relationship("IntegrationSyncJob", foreign_keys=[sync_job_id])
    last_sync_run = relationship("IntegrationSyncRun", foreign_keys=[last_sync_run_id])
    chunks = relationship(
        "IntegrationImportChunk",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="IntegrationImportChunk.sequence",
    )
