from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, JSON, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


_PORTABLE_JSON = JSON().with_variant(JSONB(), "postgresql")
_MONEY_TYPE = Numeric(20, 6)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationReconciliationRun(Base):
    __tablename__ = "integration_reconciliation_runs"
    __table_args__ = (
        CheckConstraint("status IN ('OK','WARNING','FAILED')", name="ck_integration_reconciliation_status"),
        CheckConstraint("period_start <= period_end", name="ck_integration_reconciliation_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    integration_connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_revenue: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    canonical_revenue: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    revenue_difference: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    source_refunds: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    canonical_refunds: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    refund_difference: Mapped[Decimal] = mapped_column(_MONEY_TYPE, nullable=False, default=Decimal("0"))
    source_counts_json: Mapped[dict] = mapped_column(_PORTABLE_JSON, nullable=False, default=dict, server_default="{}")
    canonical_counts_json: Mapped[dict] = mapped_column(_PORTABLE_JSON, nullable=False, default=dict, server_default="{}")
    discrepancies_json: Mapped[dict] = mapped_column(_PORTABLE_JSON, nullable=False, default=dict, server_default="{}")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    connection = relationship("IntegrationConnection", back_populates="reconciliation_runs")
