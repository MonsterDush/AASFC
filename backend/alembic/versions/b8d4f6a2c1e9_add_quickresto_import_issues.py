"""add durable QuickResto import issues

Revision ID: b8d4f6a2c1e9
Revises: a7c9e1f3b5d7
Create Date: 2026-08-31 00:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8d4f6a2c1e9"
down_revision: Union[str, Sequence[str], None] = "a7c9e1f3b5d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _portable_json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notify_integrations", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    # SQLite does not support ``ALTER COLUMN ... DROP DEFAULT``. Production
    # PostgreSQL still drops the temporary backfill default, while SQLite
    # migration fixtures keep the equivalent harmless default.
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("users", "notify_integrations", server_default=None)

    op.add_column(
        "quickresto_connections",
        sa.Column("incremental_cursor_closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "quickresto_connections",
        sa.Column("last_full_reconciliation_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "quickresto_source_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sync_run_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("encryption_key_version", sa.String(length=16), nullable=False),
        sa.Column("external_shift_id", sa.String(length=255), nullable=True),
        sa.Column("external_shift_pk", sa.Integer(), nullable=True),
        sa.Column("source_version", sa.Integer(), nullable=True),
        sa.Column("business_date", sa.Date(), nullable=True),
        sa.Column("shift_slot", sa.String(length=16), nullable=True),
        sa.Column("local_opened_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("local_closed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "shift_slot IS NULL OR shift_slot IN ('DAY', 'NIGHT')",
            name="ck_quickresto_source_snapshots_shift_slot",
        ),
        sa.UniqueConstraint(
            "connection_id",
            "source_fingerprint",
            name="uq_quickresto_source_snapshot_fingerprint",
        ),
    )
    op.create_index(
        "ix_quickresto_source_snapshots_connection_id",
        "quickresto_source_snapshots",
        ["connection_id"],
    )
    op.create_index(
        "ix_quickresto_source_snapshots_sync_run_id",
        "quickresto_source_snapshots",
        ["sync_run_id"],
    )
    op.create_index(
        "ix_quickresto_source_snapshots_external_shift_id",
        "quickresto_source_snapshots",
        ["external_shift_id"],
    )
    op.create_index(
        "ix_quickresto_source_snapshots_business_date",
        "quickresto_source_snapshots",
        ["business_date"],
    )
    op.create_index(
        "ix_quickresto_source_snapshots_retention_expires_at",
        "quickresto_source_snapshots",
        ["retention_expires_at"],
    )

    op.create_table(
        "quickresto_import_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "last_sync_run_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("group_key", sa.String(length=255), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=True),
        sa.Column("shift_slot", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("error_category", sa.String(length=32), nullable=False),
        sa.Column("user_summary", sa.Text(), nullable=False),
        sa.Column("technical_summary", sa.Text(), nullable=True),
        sa.Column("details_json", _portable_json_type(), nullable=True),
        sa.Column("failure_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolution_code", sa.String(length=64), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('OPEN', 'RETRY_PENDING', 'PROCESSING', 'RESOLVED', 'IGNORED')",
            name="ck_quickresto_import_issues_status",
        ),
        sa.CheckConstraint(
            "shift_slot IS NULL OR shift_slot IN ('DAY', 'NIGHT')",
            name="ck_quickresto_import_issues_shift_slot",
        ),
        sa.CheckConstraint("generation >= 1", name="ck_quickresto_import_issues_generation"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_quickresto_import_issues_attempts"),
        sa.CheckConstraint("lock_version >= 1", name="ck_quickresto_import_issues_lock_version"),
        sa.UniqueConstraint(
            "connection_id",
            "group_key",
            name="uq_quickresto_import_issue_group",
        ),
    )
    for column_name in (
        "connection_id",
        "last_sync_run_id",
        "business_date",
        "status",
        "error_code",
        "error_category",
        "correlation_id",
        "next_retry_at",
        "resolved_by_user_id",
    ):
        op.create_index(
            f"ix_quickresto_import_issues_{column_name}",
            "quickresto_import_issues",
            [column_name],
        )

    op.create_table(
        "quickresto_import_issue_shifts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "issue_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_import_issues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_source_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "shift_import_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_shift_imports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_key", sa.String(length=255), nullable=False),
        sa.Column("external_shift_id", sa.String(length=255), nullable=True),
        sa.Column("external_shift_pk", sa.Integer(), nullable=True),
        sa.Column("source_version", sa.Integer(), nullable=True),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("local_opened_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("local_closed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("item_status", sa.String(length=24), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("user_summary", sa.Text(), nullable=True),
        sa.Column("technical_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "item_status IN ('FAILED', 'BLOCKED', 'READY', 'RESOLVED', 'IGNORED')",
            name="ck_quickresto_import_issue_shifts_status",
        ),
        sa.UniqueConstraint(
            "issue_id",
            "source_key",
            name="uq_quickresto_import_issue_shift_source",
        ),
    )
    for column_name in (
        "issue_id",
        "source_snapshot_id",
        "shift_import_id",
        "external_shift_id",
        "item_status",
    ):
        op.create_index(
            f"ix_quickresto_import_issue_shifts_{column_name}",
            "quickresto_import_issue_shifts",
            [column_name],
        )

    op.create_table(
        "quickresto_import_issue_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "issue_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_import_issues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "sync_run_id",
            sa.Integer(),
            sa.ForeignKey("quickresto_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", _portable_json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column_name in ("issue_id", "actor_user_id", "sync_run_id", "event_type", "correlation_id"):
        op.create_index(
            f"ix_quickresto_import_issue_audits_{column_name}",
            "quickresto_import_issue_audits",
            [column_name],
        )


def downgrade() -> None:
    for column_name in ("issue_id", "actor_user_id", "sync_run_id", "event_type", "correlation_id"):
        op.drop_index(
            f"ix_quickresto_import_issue_audits_{column_name}",
            table_name="quickresto_import_issue_audits",
        )
    op.drop_table("quickresto_import_issue_audits")

    for column_name in (
        "issue_id",
        "source_snapshot_id",
        "shift_import_id",
        "external_shift_id",
        "item_status",
    ):
        op.drop_index(
            f"ix_quickresto_import_issue_shifts_{column_name}",
            table_name="quickresto_import_issue_shifts",
        )
    op.drop_table("quickresto_import_issue_shifts")

    for column_name in (
        "connection_id",
        "last_sync_run_id",
        "business_date",
        "status",
        "error_code",
        "error_category",
        "correlation_id",
        "next_retry_at",
        "resolved_by_user_id",
    ):
        op.drop_index(
            f"ix_quickresto_import_issues_{column_name}",
            table_name="quickresto_import_issues",
        )
    op.drop_table("quickresto_import_issues")

    for index_name in (
        "ix_quickresto_source_snapshots_retention_expires_at",
        "ix_quickresto_source_snapshots_business_date",
        "ix_quickresto_source_snapshots_external_shift_id",
        "ix_quickresto_source_snapshots_sync_run_id",
        "ix_quickresto_source_snapshots_connection_id",
    ):
        op.drop_index(index_name, table_name="quickresto_source_snapshots")
    op.drop_table("quickresto_source_snapshots")

    op.drop_column("quickresto_connections", "last_full_reconciliation_at")
    op.drop_column("quickresto_connections", "incremental_cursor_closed_at")
    op.drop_column("users", "notify_integrations")
