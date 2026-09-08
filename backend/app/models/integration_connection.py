from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_PORTABLE_JSON = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        UniqueConstraint(
            "venue_id",
            "provider",
            "external_organization_id",
            "external_venue_id",
            name="uq_integration_connections_provider_scope",
        ),
        CheckConstraint(
            "provider IN ('IIKO','QUICK_RESTO','R_KEEPER','PALOMA','SYRVE','OTHER')",
            name="ck_integration_connections_provider",
        ),
        CheckConstraint(
            "status IN ('CONNECTING','ACTIVE','DEGRADED','PAUSED','FAILED','DISCONNECTED')",
            name="ck_integration_connections_status",
        ),
        CheckConstraint(
            "historical_sync_status IN ('NOT_STARTED','RUNNING','PARTIAL','COMPLETED','FAILED')",
            name="ck_integration_connections_historical_status",
        ),
        CheckConstraint(
            "coverage_start IS NULL OR coverage_end IS NULL OR coverage_start <= coverage_end",
            name="ck_integration_connections_coverage_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Axelio currently has venue-level tenancy but no Organization aggregate.
    # Keep the contract field nullable until that aggregate is introduced.
    organization_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CONNECTING", server_default="CONNECTING")
    external_organization_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_venue_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    capabilities: Mapped[dict] = mapped_column(_PORTABLE_JSON, nullable=False, default=dict, server_default="{}")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    historical_sync_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="NOT_STARTED", server_default="NOT_STARTED"
    )
    coverage_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    coverage_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    venue = relationship("Venue")
    capability_states = relationship(
        "IntegrationCapabilityState", back_populates="connection", cascade="all, delete-orphan"
    )
    raw_objects = relationship("IntegrationRawObject", back_populates="connection", cascade="all, delete-orphan")
