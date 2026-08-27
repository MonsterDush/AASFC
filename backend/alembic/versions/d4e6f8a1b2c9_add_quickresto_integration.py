"""add QuickResto integration

Revision ID: d4e6f8a1b2c9
Revises: d4a9f6c2b8e1
Create Date: 2026-08-27 23:10:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d4e6f8a1b2c9"
down_revision: Union[str, Sequence[str], None] = "d4a9f6c2b8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quickresto_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cloud", sa.String(length=63), nullable=False),
        sa.Column("api_login_encrypted", sa.Text(), nullable=False),
        sa.Column("api_password_encrypted", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("auto_sync_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("business_day_cutoff_hour", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sync_from_date", sa.Date(), nullable=True),
        sa.Column("last_sync_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=24), nullable=False, server_default="NEVER"),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "business_day_cutoff_hour >= 0 AND business_day_cutoff_hour <= 23",
            name="ck_quickresto_connections_cutoff_hour",
        ),
        sa.UniqueConstraint("venue_id", name="uq_quickresto_connections_venue"),
    )
    op.create_index("ix_quickresto_connections_venue_id", "quickresto_connections", ["venue_id"])

    op.create_table(
        "quickresto_payment_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Integer(), nullable=False),
        sa.Column("external_name", sa.String(length=160), nullable=False),
        sa.Column("operation_type", sa.String(length=32), nullable=False),
        sa.Column("payment_mechanism", sa.String(length=32), nullable=True),
        sa.Column(
            "payment_method_id",
            sa.Integer(),
            sa.ForeignKey("payment_methods.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("excluded_from_revenue", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_quickresto_payment_mapping_external"),
    )
    op.create_index(
        "ix_quickresto_payment_mappings_connection_id",
        "quickresto_payment_mappings",
        ["connection_id"],
    )

    op.create_table(
        "quickresto_department_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Integer(), nullable=False),
        sa.Column("external_name", sa.String(length=160), nullable=False),
        sa.Column(
            "department_id",
            sa.Integer(),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_quickresto_department_mapping_external"),
    )
    op.create_index(
        "ix_quickresto_department_mappings_connection_id",
        "quickresto_department_mappings",
        ["connection_id"],
    )

    op.create_table(
        "quickresto_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("trigger", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shifts_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shifts_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reports_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reports_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reports_unchanged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_quickresto_sync_runs_connection_id", "quickresto_sync_runs", ["connection_id"])

    op.create_table(
        "quickresto_shift_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_shift_id", sa.String(length=255), nullable=False),
        sa.Column("external_shift_pk", sa.Integer(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("local_closed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("normalized_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "daily_report_id",
            sa.Integer(),
            sa.ForeignKey("daily_reports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("first_imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "external_shift_id", name="uq_quickresto_shift_import_external"),
    )
    op.create_index("ix_quickresto_shift_imports_connection_id", "quickresto_shift_imports", ["connection_id"])
    op.create_index("ix_quickresto_shift_imports_business_date", "quickresto_shift_imports", ["business_date"])

    op.create_table(
        "quickresto_report_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "daily_report_id",
            sa.Integer(),
            sa.ForeignKey("daily_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("shift_slot", sa.String(length=16), nullable=False, server_default="DAY"),
        sa.Column("aggregate_hash", sa.String(length=64), nullable=False),
        sa.Column("shift_count", sa.Integer(), nullable=False),
        sa.Column("writeoff_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discount_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "last_sync_run_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "connection_id",
            "business_date",
            "shift_slot",
            name="uq_quickresto_report_import_date_slot",
        ),
        sa.UniqueConstraint("daily_report_id", name="uq_quickresto_report_import_report"),
    )
    op.create_index("ix_quickresto_report_imports_connection_id", "quickresto_report_imports", ["connection_id"])
    op.create_index("ix_quickresto_report_imports_business_date", "quickresto_report_imports", ["business_date"])


def downgrade() -> None:
    op.drop_index("ix_quickresto_report_imports_business_date", table_name="quickresto_report_imports")
    op.drop_index("ix_quickresto_report_imports_connection_id", table_name="quickresto_report_imports")
    op.drop_table("quickresto_report_imports")
    op.drop_index("ix_quickresto_shift_imports_business_date", table_name="quickresto_shift_imports")
    op.drop_index("ix_quickresto_shift_imports_connection_id", table_name="quickresto_shift_imports")
    op.drop_table("quickresto_shift_imports")
    op.drop_index("ix_quickresto_sync_runs_connection_id", table_name="quickresto_sync_runs")
    op.drop_table("quickresto_sync_runs")
    op.drop_index(
        "ix_quickresto_department_mappings_connection_id",
        table_name="quickresto_department_mappings",
    )
    op.drop_table("quickresto_department_mappings")
    op.drop_index(
        "ix_quickresto_payment_mappings_connection_id",
        table_name="quickresto_payment_mappings",
    )
    op.drop_table("quickresto_payment_mappings")
    op.drop_index("ix_quickresto_connections_venue_id", table_name="quickresto_connections")
    op.drop_table("quickresto_connections")
