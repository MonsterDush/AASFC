from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_PORTABLE_JSON = JSON().with_variant(JSONB(), "postgresql")


class QuickRestoScopeAudit(Base):
    __tablename__ = "quickresto_scope_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scope_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_scope_json: Mapped[dict] = mapped_column(_PORTABLE_JSON, nullable=False)
    current_scope_json: Mapped[dict] = mapped_column(_PORTABLE_JSON, nullable=False)
    changes_json: Mapped[dict] = mapped_column(_PORTABLE_JSON, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    connection = relationship("QuickRestoConnection")
    actor_user = relationship("User")
