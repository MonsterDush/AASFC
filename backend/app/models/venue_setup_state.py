from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class VenueSetupState(Base):
    __tablename__ = "venue_setup_state"
    __table_args__ = (UniqueConstraint("venue_id", name="uq_venue_setup_state_venue_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)

    wizard_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="NOT_STARTED", index=True)
    phase: Mapped[str] = mapped_column(String(16), nullable=False, default="PREPARE", index=True)
    current_step_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    completed_steps_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    skipped_steps_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    step_meta_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prepare_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    venue = relationship("Venue")
    last_seen_by_user = relationship("User")
