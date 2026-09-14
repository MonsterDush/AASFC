"""connect QuickResto monthly imports to the ACDM shadow pipeline

Revision ID: f5d9a2c7e4b1
Revises: f3b7c1d9e5a2
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f5d9a2c7e4b1"
down_revision = "f3b7c1d9e5a2"
branch_labels = None
depends_on = None


JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
MAPPING_STATUS = "status IN ('MAPPED', 'EXCLUDED', 'UNMAPPED', 'STALE')"

RAW_IDENTITY_LEGACY_NAME = "uq_integration_raw_objects_external_identity"
RAW_IDENTITY_VERSIONED_NAME = "uq_integration_raw_objects_version_payload"

RAW_IDENTITY_LEGACY_COLUMNS = [
    "integration_connection_id",
    "entity_type",
    "external_id",
]

RAW_IDENTITY_VERSIONED_COLUMNS = [
    "integration_connection_id",
    "entity_type",
    "external_id",
    "source_version",
    "payload_hash",
]


def _mapping_columns(source_table: str) -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "canonical_source_id",
            sa.Integer(),
            sa.ForeignKey(f"{source_table}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=48), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="UNMAPPED"),
        sa.Column("mapping_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _mapping_indexes(table_name: str) -> None:
    for column_name in ("connection_id", "canonical_source_id", "target_id", "updated_by_user_id"):
        op.create_index(f"ix_{table_name}_{column_name}", table_name, [column_name])


def _replace_raw_identity_constraint(*, versioned: bool) -> None:
    if versioned:
        old_name = RAW_IDENTITY_LEGACY_NAME
        new_name = RAW_IDENTITY_VERSIONED_NAME
        new_columns = RAW_IDENTITY_VERSIONED_COLUMNS
    else:
        old_name = RAW_IDENTITY_VERSIONED_NAME
        new_name = RAW_IDENTITY_LEGACY_NAME
        new_columns = RAW_IDENTITY_LEGACY_COLUMNS

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("integration_raw_objects", recreate="always") as batch_op:
            batch_op.drop_constraint(old_name, type_="unique")
            batch_op.create_unique_constraint(new_name, new_columns)
        return

    op.drop_constraint(
        old_name,
        "integration_raw_objects",
        type_="unique",
    )
    op.create_unique_constraint(
        new_name,
        "integration_raw_objects",
        new_columns,
    )


def upgrade() -> None:
    _replace_raw_identity_constraint(versioned=True)

    with op.batch_alter_table("quickresto_connections") as batch_op:
        batch_op.add_column(sa.Column("integration_connection_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_quickresto_connections_integration_connection_id",
            "integration_connections",
            ["integration_connection_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_quickresto_connections_integration_connection_id", ["integration_connection_id"]
        )
    op.create_index(
        "ix_quickresto_connections_integration_connection_id",
        "quickresto_connections",
        ["integration_connection_id"],
    )

    with op.batch_alter_table("quickresto_sync_runs") as batch_op:
        batch_op.add_column(sa.Column("integration_sync_run_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_quickresto_sync_runs_integration_sync_run_id",
            "integration_sync_runs",
            ["integration_sync_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_quickresto_sync_runs_integration_sync_run_id", ["integration_sync_run_id"]
        )
    op.create_index(
        "ix_quickresto_sync_runs_integration_sync_run_id",
        "quickresto_sync_runs",
        ["integration_sync_run_id"],
    )

    op.create_table(
        "integration_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "sync_job_id",
            sa.Integer(),
            sa.ForeignKey("integration_sync_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "last_sync_run_id",
            sa.Integer(),
            sa.ForeignKey("integration_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("trigger", sa.String(length=24), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("active_guard", sa.Integer(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end_exclusive", sa.Date(), nullable=False),
        sa.Column("next_period_start", sa.Date(), nullable=False),
        sa.Column("current_chunk_sequence", sa.Integer(), nullable=True),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.Column("completed_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("partial_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage_start", sa.Date(), nullable=True),
        sa.Column("coverage_end_exclusive", sa.Date(), nullable=True),
        sa.Column("counters_json", JSON_TYPE, nullable=True),
        sa.Column("error_code", sa.String(length=96), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "active_guard", name="uq_integration_import_batches_active"),
        sa.UniqueConstraint("sync_job_id", name="uq_integration_import_batches_sync_job"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name="ck_integration_import_batches_status",
        ),
        sa.CheckConstraint("mode IN ('FULL', 'INCREMENTAL')", name="ck_integration_import_batches_mode"),
        sa.CheckConstraint("period_end_exclusive > period_start", name="ck_integration_import_batches_period"),
        sa.CheckConstraint(
            "next_period_start >= period_start AND next_period_start <= period_end_exclusive",
            name="ck_integration_import_batches_cursor",
        ),
        sa.CheckConstraint(
            "total_chunks > 0 AND completed_chunks >= 0 "
            "AND completed_chunks <= total_chunks AND partial_chunks >= 0 "
            "AND partial_chunks <= completed_chunks AND retry_count >= 0",
            name="ck_integration_import_batches_progress",
        ),
        sa.CheckConstraint(
            "active_guard IS NULL OR active_guard = 1",
            name="ck_integration_import_batches_active_guard",
        ),
        sa.CheckConstraint(
            "coverage_end_exclusive IS NULL OR coverage_start IS NULL OR coverage_end_exclusive > coverage_start",
            name="ck_integration_import_batches_coverage",
        ),
    )
    for column_name in ("connection_id", "requested_by_user_id", "sync_job_id", "last_sync_run_id"):
        op.create_index(f"ix_integration_import_batches_{column_name}", "integration_import_batches", [column_name])

    op.create_table(
        "integration_import_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey("integration_import_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end_exclusive", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "sync_run_id",
            sa.Integer(),
            sa.ForeignKey("integration_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=96), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("counters_json", JSON_TYPE, nullable=True),
        sa.Column("provenance_json", JSON_TYPE, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("batch_id", "sequence", name="uq_integration_import_chunks_sequence"),
        sa.UniqueConstraint(
            "batch_id",
            "period_start",
            "period_end_exclusive",
            name="uq_integration_import_chunks_period",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name="ck_integration_import_chunks_status",
        ),
        sa.CheckConstraint(
            "sequence > 0 AND attempts >= 0",
            name="ck_integration_import_chunks_sequence_attempts",
        ),
        sa.CheckConstraint(
            "period_end_exclusive > period_start",
            name="ck_integration_import_chunks_period",
        ),
    )
    op.create_index("ix_integration_import_chunks_batch_id", "integration_import_chunks", ["batch_id"])
    op.create_index("ix_integration_import_chunks_sync_run_id", "integration_import_chunks", ["sync_run_id"])

    with op.batch_alter_table("quickresto_import_batches", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_quickresto_import_batches_status", type_="check")
        batch_op.add_column(sa.Column("integration_import_batch_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("integration_sync_job_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_quickresto_import_batches_integration_import_batch_id",
            "integration_import_batches",
            ["integration_import_batch_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_quickresto_import_batches_integration_sync_job_id",
            "integration_sync_jobs",
            ["integration_sync_job_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_quickresto_import_batches_integration_import_batch_id", ["integration_import_batch_id"]
        )
        batch_op.create_unique_constraint(
            "uq_quickresto_import_batches_integration_sync_job_id", ["integration_sync_job_id"]
        )
        batch_op.create_check_constraint(
            "ck_quickresto_import_batches_status",
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')",
        )
    op.create_index(
        "ix_quickresto_import_batches_integration_import_batch_id",
        "quickresto_import_batches",
        ["integration_import_batch_id"],
    )
    op.create_index(
        "ix_quickresto_import_batches_integration_sync_job_id",
        "quickresto_import_batches",
        ["integration_sync_job_id"],
    )

    op.create_table(
        "pos_payment_type_mappings",
        *_mapping_columns("pos_payment_types"),
        sa.UniqueConstraint("connection_id", "canonical_source_id", name="uq_pos_payment_type_mappings_source"),
        sa.CheckConstraint(MAPPING_STATUS, name="ck_pos_payment_type_mappings_status"),
        sa.CheckConstraint("mapping_version >= 1", name="ck_pos_payment_type_mappings_version"),
    )
    _mapping_indexes("pos_payment_type_mappings")

    op.create_table(
        "pos_group_department_mappings",
        *_mapping_columns("pos_product_groups"),
        sa.UniqueConstraint("connection_id", "canonical_source_id", name="uq_pos_group_department_mappings_source"),
        sa.CheckConstraint(MAPPING_STATUS, name="ck_pos_group_department_mappings_status"),
        sa.CheckConstraint("mapping_version >= 1", name="ck_pos_group_department_mappings_version"),
    )
    _mapping_indexes("pos_group_department_mappings")

    op.create_table(
        "pos_group_department_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "mapping_id",
            sa.Integer(),
            sa.ForeignKey("pos_group_department_mappings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "department_id",
            sa.Integer(),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("share_percent", sa.Numeric(7, 4), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("mapping_id", "department_id", name="uq_pos_group_department_allocations_target"),
        sa.CheckConstraint(
            "share_percent > 0 AND share_percent <= 100", name="ck_pos_group_department_allocations_share"
        ),
    )
    op.create_index(
        "ix_pos_group_department_allocations_mapping_id", "pos_group_department_allocations", ["mapping_id"]
    )
    op.create_index(
        "ix_pos_group_department_allocations_department_id",
        "pos_group_department_allocations",
        ["department_id"],
    )

    op.create_table(
        "pos_product_kpi_mappings",
        *_mapping_columns("pos_products"),
        sa.Column("exclude_from_percentage_base", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "canonical_source_id", name="uq_pos_product_kpi_mappings_source"),
        sa.CheckConstraint(MAPPING_STATUS, name="ck_pos_product_kpi_mappings_status"),
        sa.CheckConstraint("mapping_version >= 1", name="ck_pos_product_kpi_mappings_version"),
    )
    _mapping_indexes("pos_product_kpi_mappings")

    op.create_table(
        "pos_employee_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pos_employee_id",
            sa.Integer(),
            sa.ForeignKey("pos_employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "venue_member_id",
            sa.Integer(),
            sa.ForeignKey("venue_members.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("match_type", sa.String(length=24), nullable=False, server_default="UNMAPPED"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "confirmed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mapping_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "pos_employee_id", name="uq_pos_employee_mappings_source"),
        sa.CheckConstraint(
            "match_type IN ('UNMAPPED', 'NAME_SUGGESTION', 'MANUAL_CONFIRMED')",
            name="ck_pos_employee_mappings_match_type",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_pos_employee_mappings_confidence",
        ),
        sa.CheckConstraint(
            "(confirmed = false AND venue_member_id IS NULL "
            "AND confirmed_by_user_id IS NULL AND confirmed_at IS NULL) OR "
            "(confirmed = true AND venue_member_id IS NOT NULL "
            "AND confirmed_by_user_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_pos_employee_mappings_confirmation",
        ),
        sa.CheckConstraint("mapping_version >= 1", name="ck_pos_employee_mappings_version"),
    )
    for column_name in ("connection_id", "pos_employee_id", "venue_member_id", "confirmed_by_user_id"):
        op.create_index(f"ix_pos_employee_mappings_{column_name}", "pos_employee_mappings", [column_name])

    op.create_table(
        "pos_report_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "daily_report_id", sa.Integer(), sa.ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("shift_slot", sa.String(length=16), nullable=False, server_default="DAY"),
        sa.Column("aggregate_hash", sa.String(length=64), nullable=False),
        sa.Column("mapping_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("shift_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("canonical_coverage_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "last_sync_run_id",
            sa.Integer(),
            sa.ForeignKey("integration_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("summary_json", JSON_TYPE, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("daily_report_id", name="uq_pos_report_projections_report"),
        sa.UniqueConstraint(
            "connection_id",
            "business_date",
            "shift_slot",
            name="uq_pos_report_projections_connection_date_slot",
        ),
        sa.CheckConstraint("shift_slot IN ('DAY', 'NIGHT')", name="ck_pos_report_projections_shift_slot"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'MATCHED', 'MISMATCH', 'INCOMPLETE', 'FAILED')",
            name="ck_pos_report_projections_status",
        ),
        sa.CheckConstraint("mapping_version >= 1 AND policy_version >= 1", name="ck_pos_report_projections_versions"),
        sa.CheckConstraint("shift_count >= 0", name="ck_pos_report_projections_shift_count"),
    )
    for column_name in ("daily_report_id", "connection_id", "business_date", "last_sync_run_id"):
        op.create_index(f"ix_pos_report_projections_{column_name}", "pos_report_projections", [column_name])

    op.create_table(
        "report_value_contributions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("value_numeric", sa.Numeric(20, 4), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "report_id",
            "kind",
            "ref_id",
            "source_type",
            "source_id",
            name="uq_report_value_contributions_source",
        ),
        sa.CheckConstraint(
            "source_type IN ('MANUAL', 'POS', 'ADJUSTMENT')",
            name="ck_report_value_contributions_source_type",
        ),
    )
    op.create_index("ix_report_value_contributions_report_id", "report_value_contributions", ["report_id"])


def downgrade() -> None:
    duplicate_raw_identity = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM integration_raw_objects "
                "GROUP BY integration_connection_id, entity_type, external_id "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate_raw_identity is not None:
        raise RuntimeError(
            "Cannot downgrade while versioned integration raw objects exist; export or reconcile them first"
        )

    op.drop_table("report_value_contributions")
    op.drop_table("pos_report_projections")
    op.drop_table("pos_employee_mappings")
    op.drop_table("pos_product_kpi_mappings")
    op.drop_table("pos_group_department_allocations")
    op.drop_table("pos_group_department_mappings")
    op.drop_table("pos_payment_type_mappings")

    op.drop_index("ix_quickresto_import_batches_integration_sync_job_id", table_name="quickresto_import_batches")
    op.drop_index("ix_quickresto_import_batches_integration_import_batch_id", table_name="quickresto_import_batches")
    with op.batch_alter_table("quickresto_import_batches", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_quickresto_import_batches_status", type_="check")
        batch_op.drop_constraint("uq_quickresto_import_batches_integration_sync_job_id", type_="unique")
        batch_op.drop_constraint("uq_quickresto_import_batches_integration_import_batch_id", type_="unique")
        batch_op.drop_constraint("fk_quickresto_import_batches_integration_sync_job_id", type_="foreignkey")
        batch_op.drop_constraint("fk_quickresto_import_batches_integration_import_batch_id", type_="foreignkey")
        batch_op.drop_column("integration_sync_job_id")
        batch_op.drop_column("integration_import_batch_id")
        batch_op.create_check_constraint(
            "ck_quickresto_import_batches_status",
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')",
        )

    op.drop_table("integration_import_chunks")
    op.drop_table("integration_import_batches")

    op.drop_index("ix_quickresto_sync_runs_integration_sync_run_id", table_name="quickresto_sync_runs")
    with op.batch_alter_table("quickresto_sync_runs") as batch_op:
        batch_op.drop_constraint("uq_quickresto_sync_runs_integration_sync_run_id", type_="unique")
        batch_op.drop_constraint("fk_quickresto_sync_runs_integration_sync_run_id", type_="foreignkey")
        batch_op.drop_column("integration_sync_run_id")

    op.drop_index("ix_quickresto_connections_integration_connection_id", table_name="quickresto_connections")
    with op.batch_alter_table("quickresto_connections") as batch_op:
        batch_op.drop_constraint("uq_quickresto_connections_integration_connection_id", type_="unique")
        batch_op.drop_constraint("fk_quickresto_connections_integration_connection_id", type_="foreignkey")
        batch_op.drop_column("integration_connection_id")

    _replace_raw_identity_constraint(versioned=False)
