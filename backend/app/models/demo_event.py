from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DemoEvent(Base):
    __tablename__ = "demo_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int | None] = mapped_column(
        ForeignKey("venues.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    persona: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    page_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cta_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
