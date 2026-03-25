from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class TelegramBrowserAuthSession(Base):
    __tablename__ = "telegram_browser_auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_token: Mapped[str] = mapped_column(String(48), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", index=True)
    next_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    tg_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
