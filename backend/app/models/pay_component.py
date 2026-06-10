from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class PayComponent(Base):
    __tablename__ = "pay_components"
    __table_args__ = (
        CheckConstraint(
            "component_type in ('SALARY_FIXED_MONTH','SALARY_HOURLY','SALARY_PER_SHIFT','PERCENT_TOTAL_REVENUE','PERCENT_DEPARTMENT_REVENUE','KPI_BONUS','MINIMUM_PAYOUT')",
            name="ck_pay_components_type",
        ),
        CheckConstraint("amount_minor IS NULL OR amount_minor >= 0", name="ck_pay_components_amount_minor_non_negative"),
        CheckConstraint("rate_minor IS NULL OR rate_minor >= 0", name="ck_pay_components_rate_minor_non_negative"),
        CheckConstraint("percent_bps IS NULL OR percent_bps >= 0", name="ck_pay_components_percent_bps_non_negative"),
        CheckConstraint("threshold_value IS NULL OR threshold_value >= 0", name="ck_pay_components_threshold_value_non_negative"),
        CheckConstraint("boost_percent_bps IS NULL OR boost_percent_bps >= 0", name="ck_pay_components_boost_percent_bps_non_negative"),
        CheckConstraint("boost_threshold_value IS NULL OR boost_threshold_value >= 0", name="ck_pay_components_boost_threshold_value_non_negative"),
        CheckConstraint("minimum_guarantee_minor IS NULL OR minimum_guarantee_minor >= 0", name="ck_pay_components_minimum_guarantee_non_negative"),
        CheckConstraint("maximum_cap_minor IS NULL OR maximum_cap_minor >= 0", name="ck_pay_components_maximum_cap_non_negative"),
        CheckConstraint("minimum_guarantee_scope IS NULL OR minimum_guarantee_scope in ('MONTH','DAY','SHIFT')", name="ck_pay_components_minimum_guarantee_scope"),
        CheckConstraint("sort_order >= 0", name="ck_pay_components_sort_order_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True, nullable=False)
    pay_profile_id: Mapped[int] = mapped_column(ForeignKey("pay_profiles.id", ondelete="CASCADE"), index=True, nullable=False)

    component_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)

    amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    percent_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)

    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    department_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    kpi_metric_id: Mapped[int | None] = mapped_column(ForeignKey("kpi_metrics.id"), nullable=True)
    threshold_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    steps_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    base_scope: Mapped[str | None] = mapped_column(String(24), nullable=True)
    boost_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    boost_percent_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    boost_source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    boost_recalc_mode: Mapped[str | None] = mapped_column(String(24), nullable=True)
    boost_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    boost_department_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    boost_kpi_metric_id: Mapped[int | None] = mapped_column(ForeignKey("kpi_metrics.id"), nullable=True)
    boost_threshold_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minimum_guarantee_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minimum_guarantee_scope: Mapped[str | None] = mapped_column(String(16), nullable=True)
    maximum_cap_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue")
    pay_profile = relationship("PayProfile", back_populates="components")
    department = relationship("Department", foreign_keys=[department_id])
    kpi_metric = relationship("KpiMetric", foreign_keys=[kpi_metric_id])
    boost_department = relationship("Department", foreign_keys=[boost_department_id])
    boost_kpi_metric = relationship("KpiMetric", foreign_keys=[boost_kpi_metric_id])
