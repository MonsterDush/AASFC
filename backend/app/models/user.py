from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    tg_username: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Профиль
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)   # ФИО
    short_name: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Краткое имя (для UI)

    # храним строкой, а в коде валидируем enum-ом
    system_role: Mapped[str] = mapped_column(String(32), default="NONE", nullable=False)
