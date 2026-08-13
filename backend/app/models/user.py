from sqlalchemy import BigInteger, String, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    tg_username: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Профиль
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # ФИО
    short_name: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Краткое имя (для UI)
    preferred_locale: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # храним строкой, а в коде валидируем enum-ом
    system_role: Mapped[str] = mapped_column(String(32), default="NONE", nullable=False)

    # Уведомления (Telegram bot)
    notify_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_adjustments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_shifts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_shift_comments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_day_economics: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_salary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_soft_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    shift_reminder_lead_time_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=18)
    notification_detail_level: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")

    # Локальная аутентификация по номеру + пароль
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_set_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # DEMO mode
    is_demo_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    demo_persona: Mapped[str | None] = mapped_column(String(16), nullable=True)
