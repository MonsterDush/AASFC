"""Add P0 sync cursors, reconciliation, shadow mode, and guarded read switch."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f5a7c9e1b3d6"
down_revision = "e4f6a8c0b2d7"
branch_labels = None
depends_on = None


JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    with op.batch_alter_table("integration_connections") as batch:
        batch.add_column(
            sa.Column("shadow_sync_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("read_mode", sa.String(length=16), nullable=False, server_default="LEGACY"))
        batch.add_column(sa.Column("canonical_read_enabled_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint(
            "ck_integration_connections_read_mode",
            "read_mode IN ('LEGACY','CANONICAL')",
        )

    op.create_table(
        "integration_sync_cursors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "integration_connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("watermark_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolling_window_hours", sa.Integer(), nullable=False, server_default="72"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="NOT_STARTED"),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("integration_connection_id", "capability", name="uq_integration_sync_cursor"),
        sa.CheckConstraint("rolling_window_hours >= 0", name="ck_integration_sync_cursors_rolling_window"),
        sa.CheckConstraint(
            "status IN ('NOT_STARTED','RUNNING','SUCCEEDED','PARTIAL','FAILED')",
            name="ck_integration_sync_cursors_status",
        ),
    )
    op.create_index(
        "ix_integration_sync_cursors_integration_connection_id",
        "integration_sync_cursors",
        ["integration_connection_id"],
    )
    op.create_index("ix_integration_sync_cursors_capability", "integration_sync_cursors", ["capability"])

    op.create_table(
        "integration_reconciliation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "integration_connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_revenue", sa.Numeric(20, 6), nullable=False),
        sa.Column("canonical_revenue", sa.Numeric(20, 6), nullable=False),
        sa.Column("revenue_difference", sa.Numeric(20, 6), nullable=False),
        sa.Column("source_refunds", sa.Numeric(20, 6), nullable=False),
        sa.Column("canonical_refunds", sa.Numeric(20, 6), nullable=False),
        sa.Column("refund_difference", sa.Numeric(20, 6), nullable=False),
        sa.Column("source_counts_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("canonical_counts_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("discrepancies_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('OK','WARNING','FAILED')", name="ck_integration_reconciliation_status"),
        sa.CheckConstraint("period_start <= period_end", name="ck_integration_reconciliation_period"),
    )
    op.create_index(
        "ix_integration_reconciliation_runs_integration_connection_id",
        "integration_reconciliation_runs",
        ["integration_connection_id"],
    )
    op.create_index(
        "ix_integration_reconciliation_runs_period_start",
        "integration_reconciliation_runs",
        ["period_start"],
    )
    op.create_index(
        "ix_integration_reconciliation_runs_period_end",
        "integration_reconciliation_runs",
        ["period_end"],
    )
    op.create_index(
        "ix_integration_reconciliation_runs_status",
        "integration_reconciliation_runs",
        ["status"],
    )


def downgrade():
    op.drop_table("integration_reconciliation_runs")
    op.drop_table("integration_sync_cursors")
    with op.batch_alter_table("integration_connections") as batch:
        batch.drop_constraint("ck_integration_connections_read_mode", type_="check")
        batch.drop_column("canonical_read_enabled_at")
        batch.drop_column("read_mode")
        batch.drop_column("shadow_sync_enabled")
