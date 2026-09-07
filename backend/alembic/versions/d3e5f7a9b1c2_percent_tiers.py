"""Department plans and multi-step percentages; preserve legacy fields and payroll snapshots."""

from alembic import op
import sqlalchemy as sa

revision = "d3e5f7a9b1c2"
down_revision = "c2f4a6b8d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pay_component_percent_tiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "pay_component_id", sa.Integer(), sa.ForeignKey("pay_components.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("threshold_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("percent_bps", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("pay_component_id", "threshold_value", name="uq_percent_tiers_component_threshold"),
        sa.CheckConstraint("threshold_value >= 0", name="ck_percent_tiers_threshold"),
        sa.CheckConstraint("percent_bps >= 0", name="ck_percent_tiers_percent"),
    )
    op.create_index(
        "ix_pay_component_percent_tiers_pay_component_id", "pay_component_percent_tiers", ["pay_component_id"]
    )
    op.execute(
        sa.text("""
        INSERT INTO pay_component_percent_tiers (pay_component_id, threshold_value, percent_bps, sort_order)
        SELECT id, CASE WHEN boost_source_type = 'KPI_METRIC' THEN boost_threshold_value ELSE 100 END,
               boost_percent_bps, 0
        FROM pay_components
        WHERE boost_enabled = true AND boost_percent_bps > 0
          AND component_type IN ('PERCENT_TOTAL_REVENUE', 'PERCENT_DEPARTMENT_REVENUE')
          AND (boost_source_type IN ('VENUE_MONTH_PLAN', 'VENUE_DAY_PLAN', 'DEPARTMENT_MONTH_PLAN', 'DEPARTMENT_DAY_PLAN')
               OR (boost_source_type = 'KPI_METRIC' AND boost_threshold_value IS NOT NULL))
    """)
    )
    # Zero was previously accepted but must never act as an automatically reached payroll target.
    for table in ("department_day_plans", "department_month_plans"):
        op.execute(sa.text(f"UPDATE {table} SET revenue_plan_minor = NULL WHERE revenue_plan_minor <= 0"))


def downgrade():
    # Legacy columns remain available for application rollback. Saved payroll snapshots are untouched.
    op.drop_index("ix_pay_component_percent_tiers_pay_component_id", table_name="pay_component_percent_tiers")
    op.drop_table("pay_component_percent_tiers")
