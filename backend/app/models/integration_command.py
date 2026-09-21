from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import utc_now


class IntegrationCommand(Base):
    __tablename__ = "integration_commands"
    __table_args__ = (
        UniqueConstraint("connection_id", "idempotency_key", name="uq_integration_commands_idempotency"),
        CheckConstraint(
            "status IN ('PENDING', 'SUBMITTING', 'ACCEPTED', 'IN_PROGRESS', 'SUCCEEDED', 'FAILED', "
            "'CANCELLED', 'UNKNOWN')",
            name="ck_integration_commands_status",
        ),
        CheckConstraint("attempts >= 0 AND max_attempts > 0", name="ck_integration_commands_attempts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    command_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    external_command_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default="PENDING")
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    encrypted_request: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    last_error_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    connection = relationship("IntegrationConnection")
    venue = relationship("Venue")
