"""dynamic catalogs: departments, payment methods, kpi metrics

Revision ID: 9b7a3c2d1e0f
Revises: f4c7a9b1d2e3
Create Date: 2026-03-03

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b7a3c2d1e0f"
down_revision: Union[str, Sequence[str], None] = "20c4c73c0eea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False, index=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("venue_id", "code", name="uq_departments_venue_code"),
    )

    op.create_table(
        "payment_methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False, index=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("venue_id", "code", name="uq_payment_methods_venue_code"),
    )

    op.create_table(
        "kpi_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id"), nullable=False, index=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=24), nullable=False, server_default=sa.text("'QTY'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("venue_id", "code", name="uq_kpi_metrics_venue_code"),
    )

    # ---- permissions + defaults ----
    perms = [
        ("DEPARTMENTS_VIEW", "Catalogs", "Просмотр департаментов", "Видеть список департаментов"),
        ("DEPARTMENTS_CREATE", "Catalogs", "Создание департаментов", "Создавать департаменты"),
        ("DEPARTMENTS_EDIT", "Catalogs", "Редактирование департаментов", "Редактировать департаменты"),
        ("DEPARTMENTS_ARCHIVE", "Catalogs", "Архивирование департаментов", "Архивировать/восстанавливать департаменты"),
        ("PAYMENT_METHODS_VIEW", "Catalogs", "Просмотр способов оплат", "Видеть список способов оплат"),
        ("PAYMENT_METHODS_CREATE", "Catalogs", "Создание способов оплат", "Создавать способы оплат"),
        ("PAYMENT_METHODS_EDIT", "Catalogs", "Редактирование способов оплат", "Редактировать способы оплат"),
        ("PAYMENT_METHODS_ARCHIVE", "Catalogs", "Архивирование способов оплат", "Архивировать/восстанавливать способы оплат"),
        ("KPI_METRICS_VIEW", "Catalogs", "Просмотр KPI", "Видеть список KPI/допродаж"),
        ("KPI_METRICS_CREATE", "Catalogs", "Создание KPI", "Создавать KPI/допродажи"),
        ("KPI_METRICS_EDIT", "Catalogs", "Редактирование KPI", "Редактировать KPI/допродажи"),
        ("KPI_METRICS_ARCHIVE", "Catalogs", "Архивирование KPI", "Архивировать/восстанавливать KPI/допродажи"),
    ]

    for code, group, title, desc in perms:
        op.execute(
            sa.text(
                """
                INSERT INTO permissions(code, \"group\", title, description, is_active)
                VALUES (:code, :group, :title, :desc, true)
                ON CONFLICT (code) DO UPDATE
                SET \"group\" = EXCLUDED.\"group\", title = EXCLUDED.title, description = EXCLUDED.description
                """
            ).bindparams(code=code, group=group, title=title, desc=desc)
        )

        # grant by default for venue owner/manager
        for role in ("VENUE_OWNER", "VENUE_MANAGER"):
            op.execute(
                sa.text(
                    """
                    INSERT INTO role_permission_defaults(role, permission_code, is_granted_by_default)
                    VALUES (:role, :code, true)
                    ON CONFLICT (role, permission_code) DO UPDATE
                    SET is_granted_by_default = true
                    """
                ).bindparams(role=role, code=code)
            )


def downgrade() -> None:
    # tables
    op.drop_table("kpi_metrics")
    op.drop_table("payment_methods")
    op.drop_table("departments")

    # permissions: keep rows (do not delete) to avoid breaking history
