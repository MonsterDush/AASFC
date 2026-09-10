"""Add QuickResto product-to-KPI mappings and category display names."""

from alembic import op
import sqlalchemy as sa


revision = "c7e9a1b3d5f8"
down_revision = "b6d8f0a2c4e7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("daily_reports") as batch_op:
        batch_op.add_column(
            sa.Column(
                "unallocated_revenue_total",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_check_constraint(
            "ck_daily_reports_unallocated_revenue_non_negative",
            "unallocated_revenue_total >= 0",
        )
    op.add_column(
        "quickresto_dish_category_paths",
        sa.Column("external_name", sa.String(length=160), nullable=True),
    )
    op.create_table(
        "quickresto_kpi_product_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_product_id", sa.Integer(), nullable=False),
        sa.Column("external_name", sa.String(length=160), nullable=False),
        sa.Column("external_group_id", sa.Integer(), nullable=True),
        sa.Column("external_group_name", sa.String(length=160), nullable=True),
        sa.Column(
            "kpi_metric_id",
            sa.Integer(),
            sa.ForeignKey("kpi_metrics.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "exclude_from_percentage_base",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "connection_id",
            "external_product_id",
            name="uq_quickresto_kpi_product_mapping_external",
        ),
        sa.CheckConstraint(
            "external_product_id > 0",
            name="ck_quickresto_kpi_product_mapping_external_positive",
        ),
        sa.CheckConstraint(
            "external_group_id IS NULL OR external_group_id > 0",
            name="ck_quickresto_kpi_product_mapping_group_positive",
        ),
    )
    op.create_index(
        "ix_quickresto_kpi_product_mappings_connection_id",
        "quickresto_kpi_product_mappings",
        ["connection_id"],
    )
    op.create_index(
        "ix_quickresto_kpi_product_mappings_external_group_id",
        "quickresto_kpi_product_mappings",
        ["external_group_id"],
    )
    op.create_index(
        "ix_quickresto_kpi_product_mappings_kpi_metric_id",
        "quickresto_kpi_product_mappings",
        ["kpi_metric_id"],
    )


def downgrade():
    op.drop_index(
        "ix_quickresto_kpi_product_mappings_kpi_metric_id",
        table_name="quickresto_kpi_product_mappings",
    )
    op.drop_index(
        "ix_quickresto_kpi_product_mappings_external_group_id",
        table_name="quickresto_kpi_product_mappings",
    )
    op.drop_index(
        "ix_quickresto_kpi_product_mappings_connection_id",
        table_name="quickresto_kpi_product_mappings",
    )
    op.drop_table("quickresto_kpi_product_mappings")
    op.drop_column("quickresto_dish_category_paths", "external_name")
    with op.batch_alter_table("daily_reports") as batch_op:
        batch_op.drop_constraint(
            "ck_daily_reports_unallocated_revenue_non_negative",
            type_="check",
        )
        batch_op.drop_column("unallocated_revenue_total")
