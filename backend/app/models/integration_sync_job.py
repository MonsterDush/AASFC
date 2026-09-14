from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import PORTABLE_JSON, utc_now


class IntegrationSyncJob(Base):
    __tablename__ = "integration_sync_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_integration_sync_jobs_idempotency_key"),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name="ck_integration_sync_jobs_status",
        ),
        CheckConstraint("priority >= 0", name="ck_integration_sync_jobs_priority_non_negative"),
        CheckConstraint("attempts >= 0 AND max_attempts > 0", name="ck_integration_sync_jobs_attempts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(48), nullable=False)
    capability: Mapped[str | None] = mapped_column(String(48), nullable=True)
    queue: Mapped[str] = mapped_column(String(24), nullable=False, default="normal", server_default="normal")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default="PENDING")
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    job_payload_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    connection = relationship("IntegrationConnection")
    sync_run = relationship("IntegrationSyncRun")
