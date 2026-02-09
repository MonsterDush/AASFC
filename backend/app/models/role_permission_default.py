from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RolePermissionDefault(Base):
    __tablename__ = "role_permission_defaults"
    __table_args__ = (
        UniqueConstraint("role", "permission_code", name="uq_role_permission"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    role: Mapped[str] = mapped_column(String(32), nullable=False)  # SUPER_ADMIN/MODERATOR/... (или VENUE_OWNER отдельно)
    permission_code: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("permissions.code", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    is_granted_by_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
