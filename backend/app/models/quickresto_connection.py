from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuickRestoConnection(Base):
    __tablename__ = "quickresto_connections"
    __table_args__ = (
        UniqueConstraint("venue_id", name="uq_quickresto_connections_venue"),
        CheckConstraint(
            "business_day_cutoff_hour >= 0 AND business_day_cutoff_hour <= 23",
            name="ck_quickresto_connections_cutoff_hour",
        ),
        CheckConstraint(
            "night_shift_start_hour >= 0 AND night_shift_start_hour <= 23",
            name="ck_quickresto_connections_night_start_hour",
        ),
        CheckConstraint(
            "NOT night_shift_split_enabled OR night_shift_start_hour > business_day_cutoff_hour",
            name="ck_quickresto_connections_night_after_cutoff",
        ),
        CheckConstraint(
            "report_import_mode IN ('DRAFT', 'CLOSED')",
            name="ck_quickresto_connections_report_import_mode",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    cloud: Mapped[str] = mapped_column(String(63), nullable=False)
    api_login_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    api_password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    report_import_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="CLOSED", server_default="CLOSED"
    )
    business_day_cutoff_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    night_shift_split_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    night_shift_start_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=22, server_default="22")
    sync_from_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    last_sync_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str] = mapped_column(String(24), nullable=False, default="NEVER", server_default="NEVER")
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    incremental_cursor_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_full_reconciliation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
    payment_mappings = relationship(
        "QuickRestoPaymentMapping", back_populates="connection", cascade="all, delete-orphan"
    )
    department_mappings = relationship(
        "QuickRestoDepartmentMapping", back_populates="connection", cascade="all, delete-orphan"
    )
