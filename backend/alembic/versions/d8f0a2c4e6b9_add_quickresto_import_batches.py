"""Add durable monthly QuickResto import batches.

Revision ID: d8f0a2c4e6b9
Revises: c7e9a1b3d5f8
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d8f0a2c4e6b9"
down_revision = "c7e9a1b3d5f8"
branch_labels = None
depends_on = None


_PORTABLE_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "quickresto_import_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("trigger", sa.String(length=24), nullable=False),
        sa.Column("force_full", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="PENDING", nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end_exclusive", sa.Date(), nullable=False),
        sa.Column("next_period_start", sa.Date(), nullable=False),
        sa.Column("current_period_start", sa.Date(), nullable=True),
        sa.Column("current_period_end_exclusive", sa.Date(), nullable=True),
        sa.Column("total_periods", sa.Integer(), nullable=False),
        sa.Column("completed_periods", sa.Integer(), server_default="0", nullable=False),
        sa.Column("partial_periods", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_sync_run_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("summary_json", _PORTABLE_JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="ck_quickresto_import_batches_status",
        ),
        sa.CheckConstraint(
            "period_end_exclusive > period_start",
            name="ck_quickresto_import_batches_period",
        ),
        sa.CheckConstraint(
            "next_period_start >= period_start AND next_period_start <= period_end_exclusive",
            name="ck_quickresto_import_batches_cursor",
        ),
        sa.CheckConstraint(
            "total_periods > 0 AND completed_periods >= 0 "
            "AND completed_periods <= total_periods AND partial_periods >= 0 "
            "AND partial_periods <= completed_periods AND retry_count >= 0",
            name="ck_quickresto_import_batches_progress",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["quickresto_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["last_sync_run_id"], ["quickresto_sync_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quickresto_import_batches_connection_id",
        "quickresto_import_batches",
        ["connection_id"],
    )
    op.create_index(
        "ix_quickresto_import_batches_requested_by_user_id",
        "quickresto_import_batches",
        ["requested_by_user_id"],
    )
    op.create_index(
        "ix_quickresto_import_batches_last_sync_run_id",
        "quickresto_import_batches",
        ["last_sync_run_id"],
    )
    active = sa.text("status IN ('PENDING', 'RUNNING')")
    op.create_index(
        "uq_quickresto_import_batches_active_connection",
        "quickresto_import_batches",
        ["connection_id"],
        unique=True,
        postgresql_where=active,
        sqlite_where=active,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_quickresto_import_batches_active_connection",
        table_name="quickresto_import_batches",
    )
    op.drop_index(
        "ix_quickresto_import_batches_last_sync_run_id",
        table_name="quickresto_import_batches",
    )
    op.drop_index(
        "ix_quickresto_import_batches_requested_by_user_id",
        table_name="quickresto_import_batches",
    )
    op.drop_index(
        "ix_quickresto_import_batches_connection_id",
        table_name="quickresto_import_batches",
    )
    op.drop_table("quickresto_import_batches")
