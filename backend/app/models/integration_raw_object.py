from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import utc_now


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
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(24), nullable=False, default="v1", server_default="v1")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    normalization_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canonical_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    import_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    connection = relationship("IntegrationConnection")
    import_run = relationship("IntegrationSyncRun")
