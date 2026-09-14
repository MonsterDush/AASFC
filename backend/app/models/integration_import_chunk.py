from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import PORTABLE_JSON, utc_now


class IntegrationImportChunk(Base):
    __tablename__ = "integration_import_chunks"
    __table_args__ = (
        UniqueConstraint("batch_id", "sequence", name="uq_integration_import_chunks_sequence"),
        UniqueConstraint(
            "batch_id",
            "period_start",
            "period_end_exclusive",
            name="uq_integration_import_chunks_period",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name="ck_integration_import_chunks_status",
        ),
        CheckConstraint("sequence > 0 AND attempts >= 0", name="ck_integration_import_chunks_sequence_attempts"),
        CheckConstraint(
            "period_end_exclusive > period_start",
            name="ck_integration_import_chunks_period",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("integration_import_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end_exclusive: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    counters_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)
    provenance_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    batch = relationship("IntegrationImportBatch", back_populates="chunks")
    sync_run = relationship("IntegrationSyncRun")
