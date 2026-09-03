from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuickRestoStoreScope(Base):
    __tablename__ = "quickresto_store_scopes"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "external_id",
            name="uq_quickresto_store_scope_connection_external",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    external_name: Mapped[str] = mapped_column(String(160), nullable=False)
    discovered_via_sale_place_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discovered_via_cooking_place_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_sale_place_ids_json: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    source_cooking_place_ids_json: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    connection = relationship("QuickRestoConnection", back_populates="store_scopes")
