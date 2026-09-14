from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import PORTABLE_JSON, utc_now


class IntegrationCapabilityState(Base):
    __tablename__ = "integration_capability_states"
    __table_args__ = (
        UniqueConstraint("connection_id", "capability", name="uq_integration_capability_states_identity"),
        CheckConstraint(
            "state IN ('SUPPORTED', 'DERIVED', 'UNAVAILABLE', 'DEGRADED', 'UNKNOWN')",
            name="ck_integration_capability_states_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability: Mapped[str] = mapped_column(String(48), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    freshness_seconds: Mapped[int | None] = mapped_column(nullable=True)
    details_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    connection = relationship("IntegrationConnection", back_populates="capability_states")
