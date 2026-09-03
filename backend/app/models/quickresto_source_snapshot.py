from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuickRestoSourceSnapshot(Base):
    __tablename__ = "quickresto_source_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "source_fingerprint",
            name="uq_quickresto_source_snapshot_fingerprint",
        ),
        CheckConstraint(
            "shift_slot IS NULL OR shift_slot IN ('DAY', 'NIGHT')",
            name="ck_quickresto_source_snapshots_shift_slot",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("quickresto_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # This is a stable, non-secret identity hash for one QuickResto shift. The
    # encrypted payload and payload_hash are replaced when that shift changes.
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")

    # Keep only the metadata required to group and retry a failed import without
    # decrypting every retained snapshot. Guest/order details remain encrypted.
    external_shift_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    external_shift_pk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    business_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    shift_slot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    local_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    local_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    retention_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    connection = relationship("QuickRestoConnection")
    sync_run = relationship("QuickRestoSyncRun")
