from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ShiftCommentMention(Base):
    __tablename__ = "shift_comment_mentions"
    __table_args__ = (UniqueConstraint("comment_id", "mentioned_user_id", name="uq_shift_comment_mention_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(
        ForeignKey("shift_comments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mentioned_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    comment = relationship("ShiftComment", back_populates="mentions")
    mentioned_user = relationship("User")
