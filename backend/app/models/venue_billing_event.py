from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class VenueBillingEvent(Base):
    __tablename__ = "venue_billing_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    old_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    meta_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    venue = relationship("Venue")
    created_by_user = relationship("User")
