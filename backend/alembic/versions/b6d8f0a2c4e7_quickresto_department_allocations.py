"""Allow one QuickResto group to be allocated across Axelio departments."""

from alembic import op
import sqlalchemy as sa


revision = "b6d8f0a2c4e7"
down_revision = "a4c6e8f0b2d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "quickresto_department_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "mapping_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_department_mappings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "department_id",
            sa.Integer(),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("share_percent", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "mapping_id",
            "department_id",
            name="uq_quickresto_department_allocation_target",
        ),
        sa.CheckConstraint(
            "share_percent >= 1 AND share_percent <= 100",
            name="ck_quickresto_department_allocation_share",
        ),
    )
    op.create_index(
        "ix_quickresto_department_allocations_mapping_id",
        "quickresto_department_allocations",
        ["mapping_id"],
    )
    op.create_index(
        "ix_quickresto_department_allocations_department_id",
        "quickresto_department_allocations",
        ["department_id"],
    )


def downgrade():
    op.drop_index(
        "ix_quickresto_department_allocations_department_id",
        table_name="quickresto_department_allocations",
    )
    op.drop_index(
        "ix_quickresto_department_allocations_mapping_id",
        table_name="quickresto_department_allocations",
    )
    op.drop_table("quickresto_department_allocations")
