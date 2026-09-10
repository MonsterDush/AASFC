from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuickRestoDepartmentMapping(Base):
    __tablename__ = "quickresto_department_mappings"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_quickresto_department_mapping_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    external_name: Mapped[str] = mapped_column(String(160), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    connection = relationship("QuickRestoConnection", back_populates="department_mappings")
    department = relationship("Department")
    allocations = relationship(
        "QuickRestoDepartmentAllocation",
        back_populates="mapping",
        cascade="all, delete-orphan",
        order_by="QuickRestoDepartmentAllocation.department_id",
    )


class QuickRestoDepartmentAllocation(Base):
    __tablename__ = "quickresto_department_allocations"
    __table_args__ = (
        UniqueConstraint(
            "mapping_id",
            "department_id",
            name="uq_quickresto_department_allocation_target",
        ),
        CheckConstraint(
            "share_percent >= 1 AND share_percent <= 100",
            name="ck_quickresto_department_allocation_share",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    mapping_id: Mapped[int] = mapped_column(
        ForeignKey("quickresto_department_mappings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    share_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    mapping = relationship("QuickRestoDepartmentMapping", back_populates="allocations")
    department = relationship("Department")
