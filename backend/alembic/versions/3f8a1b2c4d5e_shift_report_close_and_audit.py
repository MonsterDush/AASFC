"""shift report close + dynamic values + audit

Revision ID: 3f8a1b2c4d5e
Revises: 9b7a3c2d1e0f
Create Date: 2026-03-03

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "3f8a1b2c4d5e"
down_revision: Union[str, Sequence[str], None] = "9b7a3c2d1e0f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- daily_reports lifecycle fields ---
    op.add_column("daily_reports", sa.Column("status", sa.String(length=16), nullable=False, server_default="DRAFT"))
    op.alter_column("daily_reports", "status", server_default=None)

    op.add_column("daily_reports", sa.Column("closed_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_daily_reports_closed_by_user_id_users",
        "daily_reports",
        "users",
        ["closed_by_user_id"],
        ["id"],
    )

    op.add_column("daily_reports", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("daily_reports", sa.Column("comment", sa.Text(), nullable=True))

    # --- daily_report_values ---
    op.create_table(
        "daily_report_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=False),
        sa.Column("value_numeric", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("report_id", "kind", "ref_id", name="uq_daily_report_values_report_kind_ref"),
        sa.CheckConstraint("kind in ('PAYMENT','DEPT','KPI')", name="ck_daily_report_values_kind"),
    )
    op.alter_column("daily_report_values", "value_numeric", server_default=None)

    # --- audit for edits to CLOSED reports ---
    op.create_table(
        "daily_report_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("diff_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.alter_column("daily_report_audit", "diff_json", server_default=None)

    # ---- permissions + defaults ----
    perms = [
        ("SHIFT_REPORT_VIEW", "Reports", "Закрытие смены: просмотр", "Просматривать отчёт закрытия смены"),
        ("SHIFT_REPORT_EDIT", "Reports", "Закрытие смены: правка закрытых", "Редактировать закрытые отчёты (с аудитом)"),
        ("SHIFT_REPORT_CLOSE", "Reports", "Закрытие смены: закрыть", "Закрывать смену (переводить отчёт в статус CLOSED)"),
        ("SHIFT_REPORT_REOPEN", "Reports", "Закрытие смены: переоткрыть", "Переоткрывать закрытые отчёты (CLOSED -> DRAFT)"),
    ]

    for code, group, title, desc in perms:
        op.execute(
            sa.text(
                """
                INSERT INTO permissions(code, "group", title, description, is_active)
                VALUES (:code, :group, :title, :desc, true)
                ON CONFLICT (code) DO UPDATE
                SET "group" = EXCLUDED."group", title = EXCLUDED.title, description = EXCLUDED.description
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
    op.drop_table("daily_report_audit")
    op.drop_table("daily_report_values")

    op.drop_constraint("fk_daily_reports_closed_by_user_id_users", "daily_reports", type_="foreignkey")
    op.drop_column("daily_reports", "comment")
    op.drop_column("daily_reports", "closed_at")
    op.drop_column("daily_reports", "closed_by_user_id")
    op.drop_column("daily_reports", "status")

    # permissions: keep rows (do not delete) to avoid breaking history
