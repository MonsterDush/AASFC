from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import PORTABLE_JSON, utc_now


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        CheckConstraint(
            "status IN ('CONNECTING', 'ACTIVE', 'DEGRADED', 'PAUSED', 'FAILED', 'DISCONNECTED')",
            name="ck_integration_connections_status",
        ),
        CheckConstraint(
            "read_mode IN ('LEGACY', 'POS_CANONICAL')",
            name="ck_integration_connections_read_mode",
        ),
        CheckConstraint(
            "coverage_end_exclusive IS NULL OR coverage_start IS NULL OR coverage_end_exclusive > coverage_start",
            name="ck_integration_connections_coverage",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CONNECTING", server_default="CONNECTING")
    external_organization_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_venue_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    credentials_key_version: Mapped[str] = mapped_column(String(24), nullable=False, default="v1", server_default="v1")
    capabilities_snapshot: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)
    provider_limits_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)
    shadow_sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    read_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="LEGACY", server_default="LEGACY")
    coverage_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    coverage_end_exclusive: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    venue = relationship("Venue")
    capability_states = relationship(
        "IntegrationCapabilityState", back_populates="connection", cascade="all, delete-orphan"
    )
