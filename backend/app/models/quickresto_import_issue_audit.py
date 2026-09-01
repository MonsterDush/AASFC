from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_PORTABLE_JSON = JSON().with_variant(JSONB(), "postgresql")


class QuickRestoImportIssueAudit(Base):
    __tablename__ = "quickresto_import_issue_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_import_issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("quickresto_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metadata_json: Mapped[dict | list | None] = mapped_column(_PORTABLE_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    issue = relationship("QuickRestoImportIssue", back_populates="audits")
    actor_user = relationship("User")
    sync_run = relationship("QuickRestoSyncRun")
