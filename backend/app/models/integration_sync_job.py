from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_PORTABLE_JSON = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationSyncJob(Base):
    __tablename__ = "integration_sync_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_integration_sync_jobs_idempotency_key"),
        CheckConstraint(
            "job_type IN ('CONNECTION_HEALTH','CAPABILITY_SYNC','HISTORICAL_BACKFILL','ROLLING_RESYNC',"
            "'NIGHT_RECONCILIATION')",
            name="ck_integration_sync_jobs_type",
        ),
        CheckConstraint("queue IN ('CRITICAL','NORMAL','BULK')", name="ck_integration_sync_jobs_queue"),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','PARTIAL','FAILED')",
            name="ck_integration_sync_jobs_status",
        ),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_integration_sync_jobs_attempts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    queue: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    capability: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(_PORTABLE_JSON, nullable=False, default=dict, server_default="{}")
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING", server_default="PENDING", index=True)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    connection = relationship("IntegrationConnection", back_populates="sync_jobs")
