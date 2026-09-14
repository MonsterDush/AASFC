from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import utc_now


class IntegrationSyncCursor(Base):
    __tablename__ = "integration_sync_cursors"
    __table_args__ = (
        UniqueConstraint("connection_id", "capability", name="uq_integration_sync_cursors_identity"),
        CheckConstraint("overlap_seconds >= 0", name="ck_integration_sync_cursors_overlap_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability: Mapped[str] = mapped_column(String(48), nullable=False)
    cursor_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    watermark_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overlap_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=172800, server_default="172800")
    last_confirmed_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    connection = relationship("IntegrationConnection")
    last_confirmed_run = relationship("IntegrationSyncRun")
