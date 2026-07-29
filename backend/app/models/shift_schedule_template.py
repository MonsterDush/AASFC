from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class ShiftScheduleTemplate(Base):
    """Reusable weekly pattern for generating shifts for a month."""

    __tablename__ = "shift_schedule_templates"
    __table_args__ = (
        UniqueConstraint("venue_id", "title", name="uq_shift_schedule_templates_venue_title"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    venue = relationship("Venue")
    created_by = relationship("User")
    items = relationship(
        "ShiftScheduleTemplateItem",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="ShiftScheduleTemplateItem.weekday, ShiftScheduleTemplateItem.sort_order, ShiftScheduleTemplateItem.id",
    )


class ShiftScheduleTemplateItem(Base):
    """Single interval assignment inside a weekly schedule template."""

    __tablename__ = "shift_schedule_template_items"
    __table_args__ = (
        CheckConstraint(
            "shift_slot IN ('DAY', 'NIGHT')",
            name="ck_shift_schedule_template_items_shift_slot_valid",
        ),
        UniqueConstraint(
            "template_id",
            "weekday",
            "interval_id",
            "shift_slot",
            name="uq_shift_schedule_template_items_unique_interval",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("shift_schedule_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # 0=Monday ... 6=Sunday
    interval_id: Mapped[int] = mapped_column(ForeignKey("shift_intervals.id"), nullable=False, index=True)
    shift_slot: Mapped[str] = mapped_column(String(16), nullable=False, default="DAY", server_default="DAY", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    template = relationship("ShiftScheduleTemplate", back_populates="items")
    interval = relationship("ShiftInterval")
