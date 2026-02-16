from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class DailyReportAttachment(Base):
    __tablename__ = "daily_report_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    report_id: Mapped[int] = mapped_column(ForeignKey("daily_reports.id"), index=True, nullable=False)

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)

    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    venue = relationship("Venue")
    report = relationship("DailyReport")
    uploaded_by_user = relationship("User")


Index("ix_report_att_report", DailyReportAttachment.report_id)
