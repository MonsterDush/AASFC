"""Store QuickResto nested dish category paths for deterministic report retries."""

from alembic import op
import sqlalchemy as sa


revision = "a4c6e8f0b2d1"
down_revision = "d3e5f7a9b1c2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "quickresto_dish_category_paths",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Integer(), nullable=False),
        sa.Column("parent_external_id", sa.Integer(), nullable=True),
        sa.Column("root_external_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "connection_id",
            "external_id",
            name="uq_quickresto_dish_category_path_external",
        ),
        sa.CheckConstraint(
            "external_id > 0",
            name="ck_quickresto_dish_category_path_external_positive",
        ),
        sa.CheckConstraint(
            "parent_external_id IS NULL OR parent_external_id > 0",
            name="ck_quickresto_dish_category_path_parent_positive",
        ),
        sa.CheckConstraint(
            "root_external_id > 0",
            name="ck_quickresto_dish_category_path_root_positive",
        ),
    )
    op.create_index(
        "ix_quickresto_dish_category_paths_connection_id",
        "quickresto_dish_category_paths",
        ["connection_id"],
    )
    op.create_index(
        "ix_quickresto_dish_category_paths_root_external_id",
        "quickresto_dish_category_paths",
        ["root_external_id"],
    )


def downgrade():
    op.drop_index(
        "ix_quickresto_dish_category_paths_root_external_id",
        table_name="quickresto_dish_category_paths",
    )
    op.drop_index(
        "ix_quickresto_dish_category_paths_connection_id",
        table_name="quickresto_dish_category_paths",
    )
    op.drop_table("quickresto_dish_category_paths")
