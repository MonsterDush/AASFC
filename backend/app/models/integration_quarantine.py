from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import PORTABLE_JSON, utc_now


class IntegrationQuarantine(Base):
    __tablename__ = "integration_quarantine"
    __table_args__ = (
        UniqueConstraint("connection_id", "issue_key", name="uq_integration_quarantine_issue_key"),
        CheckConstraint(
            "status IN ('OPEN', 'RETRY_PENDING', 'PROCESSING', 'RESOLVED', 'IGNORED')",
            name="ck_integration_quarantine_status",
        ),
        CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')",
            name="ck_integration_quarantine_severity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raw_object_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_raw_objects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    issue_key: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_class: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str] = mapped_column(String(96), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="ERROR", server_default="ERROR")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN", server_default="OPEN")
    user_summary: Mapped[str] = mapped_column(Text, nullable=False)
    technical_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_fingerprints_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)
    affected_report_keys_json: Mapped[list | None] = mapped_column(PORTABLE_JSON, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    connection = relationship("IntegrationConnection")
    raw_object = relationship("IntegrationRawObject")
    sync_run = relationship("IntegrationSyncRun")
