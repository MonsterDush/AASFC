from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_PORTABLE_JSON = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationQuarantine(Base):
    __tablename__ = "integration_quarantine"
    __table_args__ = (
        UniqueConstraint(
            "integration_connection_id",
            "entity_type",
            "external_id",
            "error_code",
            name="uq_integration_quarantine_issue",
        ),
        CheckConstraint(
            "status IN ('OPEN','RETRYING','RESOLVED','IGNORED')",
            name="ck_integration_quarantine_status",
        ),
        CheckConstraint(
            "severity IN ('WARNING','ERROR')",
            name="ck_integration_quarantine_severity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[dict | list] = mapped_column(_PORTABLE_JSON, nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="ERROR", server_default="ERROR")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN", server_default="OPEN", index=True)
    attempts: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    connection = relationship("IntegrationConnection", back_populates="quarantine_items")
