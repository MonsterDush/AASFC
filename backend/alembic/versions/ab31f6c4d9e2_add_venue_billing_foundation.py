"""add venue billing foundation

Revision ID: ab31f6c4d9e2
Revises: aa26d4c1e5f0
Create Date: 2026-03-31 19:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "ab31f6c4d9e2"
down_revision: Union[str, Sequence[str], None] = "aa26d4c1e5f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "venue_billing_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_code", sa.String(length=64), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False, server_default="299000"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="RUB"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"),
        sa.Column("paid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_payment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_payment_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_renew_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("venue_id", name="uq_venue_billing_state_venue_id"),
    )
    op.create_index("ix_venue_billing_state_venue_id", "venue_billing_state", ["venue_id"], unique=False)
    op.create_index("ix_venue_billing_state_status", "venue_billing_state", ["status"], unique=False)
    op.create_index("ix_venue_billing_state_paid_until", "venue_billing_state", ["paid_until"], unique=False)
    op.create_index("ix_venue_billing_state_grace_until", "venue_billing_state", ["grace_until"], unique=False)
    op.create_index("ix_venue_billing_state_next_payment_due_at", "venue_billing_state", ["next_payment_due_at"], unique=False)

    op.create_table(
        "venue_billing_transaction",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("days_added", sa.Integer(), nullable=True),
        sa.Column("period_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_invoice_id", sa.String(length=128), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=128), nullable=True),
        sa.Column("provider_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_venue_billing_transaction_venue_id", "venue_billing_transaction", ["venue_id"], unique=False)
    op.create_index("ix_venue_billing_transaction_source", "venue_billing_transaction", ["source"], unique=False)
    op.create_index("ix_venue_billing_transaction_type", "venue_billing_transaction", ["type"], unique=False)
    op.create_index("ix_venue_billing_transaction_status", "venue_billing_transaction", ["status"], unique=False)
    op.create_index("ix_venue_billing_transaction_provider_invoice_id", "venue_billing_transaction", ["provider_invoice_id"], unique=False)
    op.create_index("ix_venue_billing_transaction_provider_payment_id", "venue_billing_transaction", ["provider_payment_id"], unique=False)
    op.create_index("ix_venue_billing_transaction_created_by_user_id", "venue_billing_transaction", ["created_by_user_id"], unique=False)

    op.create_table(
        "venue_billing_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("old_status", sa.String(length=16), nullable=True),
        sa.Column("new_status", sa.String(length=16), nullable=True),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_venue_billing_event_venue_id", "venue_billing_event", ["venue_id"], unique=False)
    op.create_index("ix_venue_billing_event_event_type", "venue_billing_event", ["event_type"], unique=False)
    op.create_index("ix_venue_billing_event_created_by_user_id", "venue_billing_event", ["created_by_user_id"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO venue_billing_state (
                venue_id,
                plan_code,
                price_minor,
                currency,
                status,
                paid_until,
                grace_until,
                last_payment_at,
                next_payment_due_at,
                auto_renew_enabled,
                provider,
                created_at,
                updated_at
            )
            SELECT
                v.id,
                'AXELIO_VENUE_MONTHLY',
                299000,
                'RUB',
                'ACTIVE',
                now() + interval '30 days',
                now() + interval '33 days',
                now(),
                now() + interval '30 days',
                false,
                'ROBOKASSA',
                now(),
                now()
            FROM venues v
            WHERE NOT EXISTS (
                SELECT 1 FROM venue_billing_state s WHERE s.venue_id = v.id
            )
            """
        )
    )

    op.alter_column("venue_billing_state", "price_minor", server_default=None)
    op.alter_column("venue_billing_state", "currency", server_default=None)
    op.alter_column("venue_billing_state", "status", server_default=None)
    op.alter_column("venue_billing_transaction", "amount_minor", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_venue_billing_event_created_by_user_id", table_name="venue_billing_event")
    op.drop_index("ix_venue_billing_event_event_type", table_name="venue_billing_event")
    op.drop_index("ix_venue_billing_event_venue_id", table_name="venue_billing_event")
    op.drop_table("venue_billing_event")

    op.drop_index("ix_venue_billing_transaction_created_by_user_id", table_name="venue_billing_transaction")
    op.drop_index("ix_venue_billing_transaction_provider_payment_id", table_name="venue_billing_transaction")
    op.drop_index("ix_venue_billing_transaction_provider_invoice_id", table_name="venue_billing_transaction")
    op.drop_index("ix_venue_billing_transaction_status", table_name="venue_billing_transaction")
    op.drop_index("ix_venue_billing_transaction_type", table_name="venue_billing_transaction")
    op.drop_index("ix_venue_billing_transaction_source", table_name="venue_billing_transaction")
    op.drop_index("ix_venue_billing_transaction_venue_id", table_name="venue_billing_transaction")
    op.drop_table("venue_billing_transaction")

    op.drop_index("ix_venue_billing_state_next_payment_due_at", table_name="venue_billing_state")
    op.drop_index("ix_venue_billing_state_grace_until", table_name="venue_billing_state")
    op.drop_index("ix_venue_billing_state_paid_until", table_name="venue_billing_state")
    op.drop_index("ix_venue_billing_state_status", table_name="venue_billing_state")
    op.drop_index("ix_venue_billing_state_venue_id", table_name="venue_billing_state")
    op.drop_table("venue_billing_state")
