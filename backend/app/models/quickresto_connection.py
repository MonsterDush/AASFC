from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_PORTABLE_JSON = JSON().with_variant(JSONB(), "postgresql")


class QuickRestoConnection(Base):
    __tablename__ = "quickresto_connections"
    __table_args__ = (
        UniqueConstraint("venue_id", name="uq_quickresto_connections_venue"),
        UniqueConstraint(
            "cloud",
            "external_venue_id",
            name="uq_quickresto_connections_cloud_external_venue",
        ),
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
        CheckConstraint(
            "scope_status IN ('NEEDS_SELECTION', 'READY', 'STALE')",
            name="ck_quickresto_connections_scope_status",
        ),
        CheckConstraint(
            "scope_generation >= 1",
            name="ck_quickresto_connections_scope_generation",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    cloud: Mapped[str] = mapped_column(String(63), nullable=False)
    api_login_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    api_password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    external_venue_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_venue_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    external_venue_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scope_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="NEEDS_SELECTION", server_default="NEEDS_SELECTION"
    )
    scope_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    scope_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scope_confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    pending_external_venue_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    pending_sale_place_ids_json: Mapped[list[int] | None] = mapped_column(_PORTABLE_JSON, nullable=True)
    pending_store_ids_json: Mapped[list[int] | None] = mapped_column(_PORTABLE_JSON, nullable=True)
    pending_scope_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pending_scope_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pending_scope_requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
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
    external_venues = relationship("QuickRestoExternalVenue", back_populates="connection", cascade="all, delete-orphan")
    sale_place_scopes = relationship(
        "QuickRestoSalePlaceScope", back_populates="connection", cascade="all, delete-orphan"
    )
    store_scopes = relationship("QuickRestoStoreScope", back_populates="connection", cascade="all, delete-orphan")
