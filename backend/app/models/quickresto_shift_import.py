from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuickRestoShiftImport(Base):
    __tablename__ = "quickresto_shift_imports"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_shift_id", name="uq_quickresto_shift_import_external"),
        CheckConstraint("shift_slot IN ('DAY', 'NIGHT')", name="ck_quickresto_shift_imports_shift_slot"),
        Index(
            "ix_quickresto_shift_imports_connection_date_slot",
            "connection_id",
            "business_date",
            "shift_slot",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_shift_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_shift_pk: Mapped[int] = mapped_column(Integer, nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    shift_slot: Mapped[str] = mapped_column(String(16), nullable=False, default="DAY", server_default="DAY")
    local_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    daily_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="SET NULL"), nullable=True
    )
    first_imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    connection = relationship("QuickRestoConnection")
    daily_report = relationship("DailyReport")
