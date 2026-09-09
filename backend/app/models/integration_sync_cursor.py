from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationSyncCursor(Base):
    __tablename__ = "integration_sync_cursors"
    __table_args__ = (
        UniqueConstraint("integration_connection_id", "capability", name="uq_integration_sync_cursor"),
        CheckConstraint("rolling_window_hours >= 0", name="ck_integration_sync_cursors_rolling_window"),
        CheckConstraint(
            "status IN ('NOT_STARTED','RUNNING','SUCCEEDED','PARTIAL','FAILED')",
            name="ck_integration_sync_cursors_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    watermark_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolling_window_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=72, server_default="72")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="NOT_STARTED", server_default="NOT_STARTED"
    )
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    connection = relationship("IntegrationConnection", back_populates="sync_cursors")
