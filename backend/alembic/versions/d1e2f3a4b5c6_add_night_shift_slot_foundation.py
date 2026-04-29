"""add night shift slot foundation

Revision ID: d1e2f3a4b5c6
Revises: e1f9b7c3d2a1
Create Date: 2026-04-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "e1f9b7c3d2a1"
branch_labels = None
depends_on = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    try:
        return any(col.get("name") == column_name for col in inspector.get_columns(table_name))
    except Exception:
        return False


def _unique_constraints(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    try:
        return {str(item.get("name")) for item in inspector.get_unique_constraints(table_name) if item.get("name")}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_column(bind, "venues", "night_shifts_enabled"):
        op.add_column("venues", sa.Column("night_shifts_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    if not _has_column(bind, "shifts", "shift_slot"):
        op.add_column("shifts", sa.Column("shift_slot", sa.String(length=16), nullable=False, server_default="DAY"))
    if not _has_column(bind, "daily_reports", "shift_slot"):
        op.add_column("daily_reports", sa.Column("shift_slot", sa.String(length=16), nullable=False, server_default="DAY"))
    if not _has_column(bind, "daily_report_attachments", "shift_slot"):
        op.add_column("daily_report_attachments", sa.Column("shift_slot", sa.String(length=16), nullable=False, server_default="DAY"))

    op.execute("UPDATE shifts SET shift_slot = 'DAY' WHERE shift_slot IS NULL OR shift_slot = ''")
    op.execute("UPDATE daily_reports SET shift_slot = 'DAY' WHERE shift_slot IS NULL OR shift_slot = ''")
    op.execute("UPDATE daily_report_attachments SET shift_slot = 'DAY' WHERE shift_slot IS NULL OR shift_slot = ''")

    shift_constraints = _unique_constraints(bind, "shifts")
    if "uq_shifts_venue_date_interval" in shift_constraints:
        op.drop_constraint("uq_shifts_venue_date_interval", "shifts", type_="unique")
    if "uq_shifts_venue_date_interval_slot" not in shift_constraints:
        op.create_unique_constraint("uq_shifts_venue_date_interval_slot", "shifts", ["venue_id", "date", "interval_id", "shift_slot"])

    report_constraints = _unique_constraints(bind, "daily_reports")
    if "uq_daily_reports_venue_date" in report_constraints:
        op.drop_constraint("uq_daily_reports_venue_date", "daily_reports", type_="unique")
    if "uq_daily_reports_venue_date_slot" not in report_constraints:
        op.create_unique_constraint("uq_daily_reports_venue_date_slot", "daily_reports", ["venue_id", "date", "shift_slot"])

    op.create_index(op.f("ix_shifts_shift_slot"), "shifts", ["shift_slot"], unique=False, if_not_exists=True)
    op.create_index(op.f("ix_daily_reports_shift_slot"), "daily_reports", ["shift_slot"], unique=False, if_not_exists=True)
    op.create_index(op.f("ix_daily_report_attachments_shift_slot"), "daily_report_attachments", ["shift_slot"], unique=False, if_not_exists=True)


def downgrade() -> None:
    bind = op.get_bind()

    shift_constraints = _unique_constraints(bind, "shifts")
    if "uq_shifts_venue_date_interval_slot" in shift_constraints:
        op.drop_constraint("uq_shifts_venue_date_interval_slot", "shifts", type_="unique")
    if "uq_shifts_venue_date_interval" not in shift_constraints:
        op.create_unique_constraint("uq_shifts_venue_date_interval", "shifts", ["venue_id", "date", "interval_id"])

    report_constraints = _unique_constraints(bind, "daily_reports")
    if "uq_daily_reports_venue_date_slot" in report_constraints:
        op.drop_constraint("uq_daily_reports_venue_date_slot", "daily_reports", type_="unique")
    if "uq_daily_reports_venue_date" not in report_constraints:
        op.create_unique_constraint("uq_daily_reports_venue_date", "daily_reports", ["venue_id", "date"])

    op.drop_index(op.f("ix_daily_report_attachments_shift_slot"), table_name="daily_report_attachments", if_exists=True)
    op.drop_index(op.f("ix_daily_reports_shift_slot"), table_name="daily_reports", if_exists=True)
    op.drop_index(op.f("ix_shifts_shift_slot"), table_name="shifts", if_exists=True)

    if _has_column(bind, "daily_report_attachments", "shift_slot"):
        op.drop_column("daily_report_attachments", "shift_slot")
    if _has_column(bind, "daily_reports", "shift_slot"):
        op.drop_column("daily_reports", "shift_slot")
    if _has_column(bind, "shifts", "shift_slot"):
        op.drop_column("shifts", "shift_slot")
    if _has_column(bind, "venues", "night_shifts_enabled"):
        op.drop_column("venues", "night_shifts_enabled")
