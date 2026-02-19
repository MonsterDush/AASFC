from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class AdjustmentDisputeComment(Base):
    __tablename__ = "adjustment_dispute_comments"

    id: Mapped[int] = mapped_column(primary_key=True)

    dispute_id: Mapped[int] = mapped_column(ForeignKey("adjustment_disputes.id"), index=True, nullable=False)
    author_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    dispute = relationship("AdjustmentDispute", back_populates="comments")
    author_user = relationship("User")
