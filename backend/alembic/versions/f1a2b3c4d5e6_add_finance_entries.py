"""add finance_entries ledger table

Revision ID: f1a2b3c4d5e6
Revises: b2f9c1d0e3a4
Create Date: 2026-03-10

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "b2f9c1d0e3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "finance_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("payment_method_id", sa.Integer(), sa.ForeignKey("payment_methods.id"), nullable=True),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("amount_minor >= 0", name="ck_finance_entries_amount_minor_non_negative"),
    )

    op.create_index("ix_finance_entries_venue_id", "finance_entries", ["venue_id"])
    op.create_index("ix_finance_entries_entry_date", "finance_entries", ["entry_date"])
    op.create_index("ix_finance_entries_venue_entry_date", "finance_entries", ["venue_id", "entry_date"])
    op.create_index("ix_finance_entries_venue_kind_entry_date", "finance_entries", ["venue_id", "kind", "entry_date"])
    op.create_index("ix_finance_entries_source", "finance_entries", ["source_type", "source_id"])

    # remove defaults to match typical application-side writes
    op.alter_column("finance_entries", "amount_minor", server_default=None)
    op.alter_column("finance_entries", "created_at", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_finance_entries_source", table_name="finance_entries")
    op.drop_index("ix_finance_entries_venue_kind_entry_date", table_name="finance_entries")
    op.drop_index("ix_finance_entries_venue_entry_date", table_name="finance_entries")
    op.drop_index("ix_finance_entries_entry_date", table_name="finance_entries")
    op.drop_index("ix_finance_entries_venue_id", table_name="finance_entries")
    op.drop_table("finance_entries")
