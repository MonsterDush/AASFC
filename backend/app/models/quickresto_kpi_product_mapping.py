from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuickRestoKpiProductMapping(Base):
    __tablename__ = "quickresto_kpi_product_mappings"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "external_product_id",
            name="uq_quickresto_kpi_product_mapping_external",
        ),
        CheckConstraint(
            "external_product_id > 0",
            name="ck_quickresto_kpi_product_mapping_external_positive",
        ),
        CheckConstraint(
            "external_group_id IS NULL OR external_group_id > 0",
            name="ck_quickresto_kpi_product_mapping_group_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    external_name: Mapped[str] = mapped_column(String(160), nullable=False)
    external_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    external_group_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    kpi_metric_id: Mapped[int | None] = mapped_column(
        ForeignKey("kpi_metrics.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    exclude_from_percentage_base: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    connection = relationship("QuickRestoConnection", back_populates="kpi_product_mappings")
    kpi_metric = relationship("KpiMetric")
