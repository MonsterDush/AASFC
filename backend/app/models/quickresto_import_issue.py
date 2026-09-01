from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_PORTABLE_JSON = JSON().with_variant(JSONB(), "postgresql")


class QuickRestoImportIssue(Base):
    __tablename__ = "quickresto_import_issues"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "group_key",
            name="uq_quickresto_import_issue_group",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'RETRY_PENDING', 'PROCESSING', 'RESOLVED', 'IGNORED')",
            name="ck_quickresto_import_issues_status",
        ),
        CheckConstraint(
            "shift_slot IS NULL OR shift_slot IN ('DAY', 'NIGHT')",
            name="ck_quickresto_import_issues_shift_slot",
        ),
        CheckConstraint("generation >= 1", name="ck_quickresto_import_issues_generation"),
        CheckConstraint("attempt_count >= 0", name="ck_quickresto_import_issues_attempts"),
        CheckConstraint("lock_version >= 1", name="ck_quickresto_import_issues_lock_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    last_sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("quickresto_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # group_key is stable for the lifetime of an issue. A resolved row is
    # reopened with generation+1 instead of deleting operational history.
    group_key: Mapped[str] = mapped_column(String(255), nullable=False)
    business_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    shift_slot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN", index=True)

    error_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    error_category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    user_summary: Mapped[str] = mapped_column(Text, nullable=False)
    technical_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict | list | None] = mapped_column(_PORTABLE_JSON, nullable=True)
    failure_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    last_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    resolution_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    connection = relationship("QuickRestoConnection")
    last_sync_run = relationship("QuickRestoSyncRun")
    resolved_by_user = relationship("User")
    shifts = relationship(
        "QuickRestoImportIssueShift",
        back_populates="issue",
        cascade="all, delete-orphan",
        order_by="QuickRestoImportIssueShift.id",
    )
    audits = relationship(
        "QuickRestoImportIssueAudit",
        back_populates="issue",
        cascade="all, delete-orphan",
        order_by="QuickRestoImportIssueAudit.id",
    )
