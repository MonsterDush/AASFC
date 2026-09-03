from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuickRestoImportIssueShift(Base):
    __tablename__ = "quickresto_import_issue_shifts"
    __table_args__ = (
        UniqueConstraint(
            "issue_id",
            "source_key",
            name="uq_quickresto_import_issue_shift_source",
        ),
        CheckConstraint(
            "item_status IN ('FAILED', 'BLOCKED', 'READY', 'RESOLVED', 'IGNORED')",
            name="ck_quickresto_import_issue_shifts_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_import_issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("quickresto_source_snapshots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shift_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("quickresto_shift_imports.id", ondelete="SET NULL"), nullable=True, index=True
    )

    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    external_shift_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    external_shift_pk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    local_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    local_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    item_status: Mapped[str] = mapped_column(String(24), nullable=False, default="FAILED", index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    technical_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    issue = relationship("QuickRestoImportIssue", back_populates="shifts")
    source_snapshot = relationship("QuickRestoSourceSnapshot")
    shift_import = relationship("QuickRestoShiftImport")
