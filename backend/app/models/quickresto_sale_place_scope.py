from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuickRestoSalePlaceScope(Base):
    __tablename__ = "quickresto_sale_place_scopes"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "external_id",
            name="uq_quickresto_sale_place_scope_connection_external",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    external_name: Mapped[str] = mapped_column(String(160), nullable=False)
    external_venue_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    default_cooking_place_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    connection = relationship("QuickRestoConnection", back_populates="sale_place_scopes")
