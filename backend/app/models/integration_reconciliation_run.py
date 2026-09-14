from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import PORTABLE_JSON, utc_now


class IntegrationReconciliationRun(Base):
    __tablename__ = "integration_reconciliation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'WARNING', 'FAILED')",
            name="ck_integration_reconciliation_runs_status",
        ),
        CheckConstraint(
            "period_end_exclusive > period_start",
            name="ck_integration_reconciliation_runs_period",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("integration_sync_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    capability: Mapped[str] = mapped_column(String(48), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end_exclusive: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", server_default="PENDING")
    source_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    canonical_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    amount_delta: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    counts_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)
    discrepancies_json: Mapped[dict | None] = mapped_column(PORTABLE_JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    connection = relationship("IntegrationConnection")
    sync_run = relationship("IntegrationSyncRun")
