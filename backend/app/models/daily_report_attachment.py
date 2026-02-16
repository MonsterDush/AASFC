from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class DailyReportAttachment(Base):
    __tablename__ = "daily_report_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    report_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)

    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    venue = relationship("Venue")
    uploaded_by_user = relationship("User")
