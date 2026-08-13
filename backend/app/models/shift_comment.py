from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ShiftComment(Base):
    """Threaded comments for a shift (simple flat list)."""

    __tablename__ = "shift_comments"

    id: Mapped[int] = mapped_column(primary_key=True)

    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id", ondelete="CASCADE"), index=True)
    author_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    parent_comment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shift_comments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    shift = relationship("Shift", back_populates="comments")
    author = relationship("User")
    parent_comment = relationship("ShiftComment", remote_side=[id], back_populates="replies")
    replies = relationship("ShiftComment", back_populates="parent_comment")
    mentions = relationship("ShiftCommentMention", back_populates="comment", cascade="all, delete-orphan")
