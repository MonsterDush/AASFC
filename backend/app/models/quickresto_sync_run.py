from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuickRestoSyncRun(Base):
    __tablename__ = "quickresto_sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    trigger: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shifts_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shifts_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reports_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reports_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reports_unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    connection = relationship("QuickRestoConnection")
