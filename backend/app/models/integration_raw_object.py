from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_PORTABLE_JSON = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationRawObject(Base):
    __tablename__ = "integration_raw_objects"
    __table_args__ = (
        UniqueConstraint(
            "integration_connection_id",
            "entity_type",
            "external_id",
            name="uq_integration_raw_objects_external_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[dict | list] = mapped_column(_PORTABLE_JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    normalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    normalization_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    connection = relationship("IntegrationConnection", back_populates="raw_objects")
