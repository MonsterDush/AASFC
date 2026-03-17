from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_auth_identities_user_provider"),
        UniqueConstraint("provider", "provider_user_id", name="uq_auth_identities_provider_user"),
        UniqueConstraint("phone_e164", name="uq_auth_identities_phone_e164"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    provider_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    is_verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User")
