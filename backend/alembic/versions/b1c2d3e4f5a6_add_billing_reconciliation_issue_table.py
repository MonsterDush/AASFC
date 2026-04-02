"""add billing reconciliation issue table

Revision ID: b1c2d3e4f5a6
Revises: ab31f6c4d9e2
Create Date: 2026-04-02 22:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "ab31f6c4d9e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_reconciliation_issue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("venue_billing_transaction.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("venue_billing_event.id", ondelete="SET NULL"), nullable=True),
        sa.Column("issue_code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("fingerprint", sa.String(length=191), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resolution_comment", sa.Text(), nullable=True),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("fingerprint", name="uq_billing_reconciliation_issue_fingerprint"),
    )
    op.create_index("ix_billing_reconciliation_issue_venue_id", "billing_reconciliation_issue", ["venue_id"], unique=False)
    op.create_index("ix_billing_reconciliation_issue_transaction_id", "billing_reconciliation_issue", ["transaction_id"], unique=False)
    op.create_index("ix_billing_reconciliation_issue_event_id", "billing_reconciliation_issue", ["event_id"], unique=False)
    op.create_index("ix_billing_reconciliation_issue_issue_code", "billing_reconciliation_issue", ["issue_code"], unique=False)
    op.create_index("ix_billing_reconciliation_issue_severity", "billing_reconciliation_issue", ["severity"], unique=False)
    op.create_index("ix_billing_reconciliation_issue_status", "billing_reconciliation_issue", ["status"], unique=False)
    op.create_index("ix_billing_reconciliation_issue_resolved_by_user_id", "billing_reconciliation_issue", ["resolved_by_user_id"], unique=False)
    op.alter_column("billing_reconciliation_issue", "status", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_billing_reconciliation_issue_resolved_by_user_id", table_name="billing_reconciliation_issue")
    op.drop_index("ix_billing_reconciliation_issue_status", table_name="billing_reconciliation_issue")
    op.drop_index("ix_billing_reconciliation_issue_severity", table_name="billing_reconciliation_issue")
    op.drop_index("ix_billing_reconciliation_issue_issue_code", table_name="billing_reconciliation_issue")
    op.drop_index("ix_billing_reconciliation_issue_event_id", table_name="billing_reconciliation_issue")
    op.drop_index("ix_billing_reconciliation_issue_transaction_id", table_name="billing_reconciliation_issue")
    op.drop_index("ix_billing_reconciliation_issue_venue_id", table_name="billing_reconciliation_issue")
    op.drop_table("billing_reconciliation_issue")
