from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuickRestoDishCategoryPath(Base):
    __tablename__ = "quickresto_dish_category_paths"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "external_id",
            name="uq_quickresto_dish_category_path_external",
        ),
        CheckConstraint("external_id > 0", name="ck_quickresto_dish_category_path_external_positive"),
        CheckConstraint(
            "parent_external_id IS NULL OR parent_external_id > 0",
            name="ck_quickresto_dish_category_path_parent_positive",
        ),
        CheckConstraint("root_external_id > 0", name="ck_quickresto_dish_category_path_root_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    external_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    parent_external_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    root_external_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    connection = relationship("QuickRestoConnection", back_populates="dish_category_paths")
