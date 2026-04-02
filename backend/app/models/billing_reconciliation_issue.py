from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class BillingReconciliationIssue(Base):
    __tablename__ = "billing_reconciliation_issue"

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("venue_billing_transaction.id", ondelete="SET NULL"), nullable=True, index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("venue_billing_event.id", ondelete="SET NULL"), nullable=True, index=True)

    issue_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default="OPEN")
    fingerprint: Mapped[str] = mapped_column(String(191), nullable=False, unique=True)

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    resolution_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    venue = relationship("Venue")
    transaction = relationship("VenueBillingTransaction")
    event = relationship("VenueBillingEvent")
    resolved_by_user = relationship("User")
