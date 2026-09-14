from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.integration_common import utc_now


_MAPPING_STATUS_CHECK = "status IN ('MAPPED', 'EXCLUDED', 'UNMAPPED', 'STALE')"


class _POSMappingMixin:
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="UNMAPPED", server_default="UNMAPPED")
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    source_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class POSPaymentTypeMapping(_POSMappingMixin, Base):
    __tablename__ = "pos_payment_type_mappings"
    __table_args__ = (
        UniqueConstraint("connection_id", "canonical_source_id", name="uq_pos_payment_type_mappings_source"),
        CheckConstraint(_MAPPING_STATUS_CHECK, name="ck_pos_payment_type_mappings_status"),
        CheckConstraint("mapping_version >= 1", name="ck_pos_payment_type_mappings_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_source_id: Mapped[int] = mapped_column(
        ForeignKey("pos_payment_types.id", ondelete="CASCADE"), nullable=False, index=True
    )

    connection = relationship("IntegrationConnection")
    canonical_source = relationship("POSPaymentType")
    updated_by_user = relationship("User")


class POSGroupDepartmentMapping(_POSMappingMixin, Base):
    __tablename__ = "pos_group_department_mappings"
    __table_args__ = (
        UniqueConstraint("connection_id", "canonical_source_id", name="uq_pos_group_department_mappings_source"),
        CheckConstraint(_MAPPING_STATUS_CHECK, name="ck_pos_group_department_mappings_status"),
        CheckConstraint("mapping_version >= 1", name="ck_pos_group_department_mappings_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_source_id: Mapped[int] = mapped_column(
        ForeignKey("pos_product_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )

    connection = relationship("IntegrationConnection")
    canonical_source = relationship("POSProductGroup")
    updated_by_user = relationship("User")
    allocations = relationship("POSGroupDepartmentAllocation", back_populates="mapping", cascade="all, delete-orphan")


class POSGroupDepartmentAllocation(Base):
    __tablename__ = "pos_group_department_allocations"
    __table_args__ = (
        UniqueConstraint("mapping_id", "department_id", name="uq_pos_group_department_allocations_target"),
        CheckConstraint("share_percent > 0 AND share_percent <= 100", name="ck_pos_group_department_allocations_share"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    mapping_id: Mapped[int] = mapped_column(
        ForeignKey("pos_group_department_mappings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    share_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    mapping = relationship("POSGroupDepartmentMapping", back_populates="allocations")
    department = relationship("Department")


class POSProductKpiMapping(_POSMappingMixin, Base):
    __tablename__ = "pos_product_kpi_mappings"
    __table_args__ = (
        UniqueConstraint("connection_id", "canonical_source_id", name="uq_pos_product_kpi_mappings_source"),
        CheckConstraint(_MAPPING_STATUS_CHECK, name="ck_pos_product_kpi_mappings_status"),
        CheckConstraint("mapping_version >= 1", name="ck_pos_product_kpi_mappings_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_source_id: Mapped[int] = mapped_column(
        ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exclude_from_percentage_base: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    connection = relationship("IntegrationConnection")
    canonical_source = relationship("POSProduct")
    updated_by_user = relationship("User")


class POSEmployeeMapping(Base):
    __tablename__ = "pos_employee_mappings"
    __table_args__ = (
        UniqueConstraint("connection_id", "pos_employee_id", name="uq_pos_employee_mappings_source"),
        CheckConstraint(
            "match_type IN ('UNMAPPED', 'NAME_SUGGESTION', 'MANUAL_CONFIRMED')",
            name="ck_pos_employee_mappings_match_type",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_pos_employee_mappings_confidence",
        ),
        CheckConstraint(
            "(confirmed = false AND venue_member_id IS NULL "
            "AND confirmed_by_user_id IS NULL AND confirmed_at IS NULL) OR "
            "(confirmed = true AND venue_member_id IS NOT NULL "
            "AND confirmed_by_user_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_pos_employee_mappings_confirmation",
        ),
        CheckConstraint("mapping_version >= 1", name="ck_pos_employee_mappings_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pos_employee_id: Mapped[int] = mapped_column(
        ForeignKey("pos_employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    venue_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("venue_members.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    match_type: Mapped[str] = mapped_column(String(24), nullable=False, default="UNMAPPED", server_default="UNMAPPED")
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    source_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    connection = relationship("IntegrationConnection")
    pos_employee = relationship("POSEmployee")
    venue_member = relationship("VenueMember")
    confirmed_by_user = relationship("User")
