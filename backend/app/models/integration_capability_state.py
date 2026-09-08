from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_PORTABLE_JSON = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationCapabilityState(Base):
    __tablename__ = "integration_capability_states"
    __table_args__ = (
        UniqueConstraint("integration_connection_id", "capability", name="uq_integration_capability_state"),
        CheckConstraint(
            "status IN ('UNKNOWN','AVAILABLE','UNAVAILABLE','DEGRADED')",
            name="ck_integration_capability_states_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict] = mapped_column(_PORTABLE_JSON, nullable=False, default=dict, server_default="{}")

    connection = relationship("IntegrationConnection", back_populates="capability_states")
