"""add provider-neutral POS integration v0.3 foundation

Revision ID: f3b7c1d9e5a2
Revises: e9a3c5f7b1d4
"""

from collections.abc import Iterable

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f3b7c1d9e5a2"
down_revision = "e9a3c5f7b1d4"
branch_labels = None
depends_on = None


JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _external_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("source_version", sa.String(length=255), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_timezone", sa.String(length=64), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_metadata_json", JSON_TYPE, nullable=True),
    ]


def _create_external_indexes(table_name: str, *, extra: Iterable[str] = ()) -> None:
    op.create_index(f"ix_{table_name}_connection_id", table_name, ["connection_id"])
    op.create_index(f"ix_{table_name}_payload_hash", table_name, ["payload_hash"])
    for column_name in extra:
        op.create_index(f"ix_{table_name}_{column_name}", table_name, [column_name])


def upgrade() -> None:
    op.add_column(
        "venues",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/Moscow"),
    )

    op.create_table(
        "integration_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="CONNECTING"),
        sa.Column("external_organization_id", sa.String(length=255), nullable=True),
        sa.Column("external_venue_id", sa.String(length=255), nullable=True),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("credentials_key_version", sa.String(length=24), nullable=False, server_default="v1"),
        sa.Column("capabilities_snapshot", JSON_TYPE, nullable=True),
        sa.Column("provider_limits_json", JSON_TYPE, nullable=True),
        sa.Column("shadow_sync_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_mode", sa.String(length=24), nullable=False, server_default="LEGACY"),
        sa.Column("coverage_start", sa.Date(), nullable=True),
        sa.Column("coverage_end_exclusive", sa.Date(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('CONNECTING', 'ACTIVE', 'DEGRADED', 'PAUSED', 'FAILED', 'DISCONNECTED')",
            name="ck_integration_connections_status",
        ),
        sa.CheckConstraint(
            "read_mode IN ('LEGACY', 'POS_CANONICAL')",
            name="ck_integration_connections_read_mode",
        ),
        sa.CheckConstraint(
            "coverage_end_exclusive IS NULL OR coverage_start IS NULL OR coverage_end_exclusive > coverage_start",
            name="ck_integration_connections_coverage",
        ),
    )
    op.create_index("ix_integration_connections_organization_id", "integration_connections", ["organization_id"])
    op.create_index("ix_integration_connections_venue_id", "integration_connections", ["venue_id"])
    op.create_index("ix_integration_connections_provider", "integration_connections", ["provider"])

    op.create_table(
        "integration_capability_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capability", sa.String(length=48), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False, server_default="UNKNOWN"),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=96), nullable=True),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("freshness_seconds", sa.Integer(), nullable=True),
        sa.Column("details_json", JSON_TYPE, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "capability", name="uq_integration_capability_states_identity"),
        sa.CheckConstraint(
            "state IN ('SUPPORTED', 'DERIVED', 'UNAVAILABLE', 'DEGRADED', 'UNKNOWN')",
            name="ck_integration_capability_states_state",
        ),
    )
    op.create_index(
        "ix_integration_capability_states_connection_id", "integration_capability_states", ["connection_id"]
    )

    op.create_table(
        "integration_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capability", sa.String(length=48), nullable=True),
        sa.Column("trigger", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor_before", sa.Text(), nullable=True),
        sa.Column("cursor_after", sa.Text(), nullable=True),
        sa.Column("records_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_persisted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_quarantined", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_json", JSON_TYPE, nullable=True),
        sa.Column("error_code", sa.String(length=96), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name="ck_integration_sync_runs_status",
        ),
    )
    op.create_index("ix_integration_sync_runs_connection_id", "integration_sync_runs", ["connection_id"])
    op.create_index("ix_integration_sync_runs_capability", "integration_sync_runs", ["capability"])

    op.create_table(
        "integration_raw_objects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "integration_connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("source_version", sa.String(length=255), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("encryption_key_version", sa.String(length=24), nullable=False, server_default="v1"),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=True),
        sa.Column("normalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canonical_identity", sa.String(length=255), nullable=True),
        sa.Column(
            "import_run_id",
            sa.Integer(),
            sa.ForeignKey("integration_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "integration_connection_id",
            "entity_type",
            "external_id",
            name="uq_integration_raw_objects_external_identity",
        ),
    )
    op.create_index(
        "ix_integration_raw_objects_integration_connection_id",
        "integration_raw_objects",
        ["integration_connection_id"],
    )
    op.create_index("ix_integration_raw_objects_payload_hash", "integration_raw_objects", ["payload_hash"])
    op.create_index("ix_integration_raw_objects_import_run_id", "integration_raw_objects", ["import_run_id"])
    op.create_index("ix_integration_raw_objects_expires_at", "integration_raw_objects", ["expires_at"])

    op.create_table(
        "integration_sync_cursors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capability", sa.String(length=48), nullable=False),
        sa.Column("cursor_token", sa.Text(), nullable=True),
        sa.Column("watermark_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overlap_seconds", sa.Integer(), nullable=False, server_default="172800"),
        sa.Column(
            "last_confirmed_run_id",
            sa.Integer(),
            sa.ForeignKey("integration_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "capability", name="uq_integration_sync_cursors_identity"),
        sa.CheckConstraint("overlap_seconds >= 0", name="ck_integration_sync_cursors_overlap_non_negative"),
    )
    op.create_index("ix_integration_sync_cursors_connection_id", "integration_sync_cursors", ["connection_id"])
    op.create_index(
        "ix_integration_sync_cursors_last_confirmed_run_id", "integration_sync_cursors", ["last_confirmed_run_id"]
    )

    op.create_table(
        "integration_sync_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sync_run_id",
            sa.Integer(),
            sa.ForeignKey("integration_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("job_type", sa.String(length=48), nullable=False),
        sa.Column("capability", sa.String(length=48), nullable=True),
        sa.Column("queue", sa.String(length=24), nullable=False, server_default="normal"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("job_payload_json", JSON_TYPE, nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=96), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_integration_sync_jobs_idempotency_key"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name="ck_integration_sync_jobs_status",
        ),
        sa.CheckConstraint("priority >= 0", name="ck_integration_sync_jobs_priority_non_negative"),
        sa.CheckConstraint("attempts >= 0 AND max_attempts > 0", name="ck_integration_sync_jobs_attempts"),
    )
    op.create_index("ix_integration_sync_jobs_connection_id", "integration_sync_jobs", ["connection_id"])
    op.create_index("ix_integration_sync_jobs_sync_run_id", "integration_sync_jobs", ["sync_run_id"])
    op.create_index("ix_integration_sync_jobs_next_attempt_at", "integration_sync_jobs", ["next_attempt_at"])
    op.create_index("ix_integration_sync_jobs_lease_expires_at", "integration_sync_jobs", ["lease_expires_at"])

    op.create_table(
        "integration_quarantine",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "raw_object_id",
            sa.Integer(),
            sa.ForeignKey("integration_raw_objects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "sync_run_id",
            sa.Integer(),
            sa.ForeignKey("integration_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("issue_key", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("error_class", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=96), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="ERROR"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="OPEN"),
        sa.Column("user_summary", sa.Text(), nullable=False),
        sa.Column("technical_summary", sa.Text(), nullable=True),
        sa.Column("source_fingerprints_json", JSON_TYPE, nullable=True),
        sa.Column("affected_report_keys_json", JSON_TYPE, nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("connection_id", "issue_key", name="uq_integration_quarantine_issue_key"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'RETRY_PENDING', 'PROCESSING', 'RESOLVED', 'IGNORED')",
            name="ck_integration_quarantine_status",
        ),
        sa.CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')",
            name="ck_integration_quarantine_severity",
        ),
    )
    op.create_index("ix_integration_quarantine_connection_id", "integration_quarantine", ["connection_id"])
    op.create_index("ix_integration_quarantine_raw_object_id", "integration_quarantine", ["raw_object_id"])
    op.create_index("ix_integration_quarantine_sync_run_id", "integration_quarantine", ["sync_run_id"])

    op.create_table(
        "integration_reconciliation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sync_run_id",
            sa.Integer(),
            sa.ForeignKey("integration_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("capability", sa.String(length=48), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end_exclusive", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("source_amount", sa.Numeric(20, 4), nullable=True),
        sa.Column("canonical_amount", sa.Numeric(20, 4), nullable=True),
        sa.Column("amount_delta", sa.Numeric(20, 4), nullable=True),
        sa.Column("counts_json", JSON_TYPE, nullable=True),
        sa.Column("discrepancies_json", JSON_TYPE, nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'WARNING', 'FAILED')",
            name="ck_integration_reconciliation_runs_status",
        ),
        sa.CheckConstraint(
            "period_end_exclusive > period_start",
            name="ck_integration_reconciliation_runs_period",
        ),
    )
    op.create_index(
        "ix_integration_reconciliation_runs_connection_id", "integration_reconciliation_runs", ["connection_id"]
    )
    op.create_index(
        "ix_integration_reconciliation_runs_sync_run_id", "integration_reconciliation_runs", ["sync_run_id"]
    )

    op.create_table(
        "pos_organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_organizations_external_identity"),
    )
    _create_external_indexes("pos_organizations")

    op.create_table(
        "pos_venues",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("pos_organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_venues_external_identity"),
    )
    _create_external_indexes("pos_venues", extra=("venue_id", "organization_id"))

    op.create_table(
        "pos_terminals",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pos_venue_id", sa.Integer(), sa.ForeignKey("pos_venues.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sale_place_external_id", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_terminals_external_identity"),
    )
    _create_external_indexes("pos_terminals", extra=("venue_id", "pos_venue_id"))

    op.create_table(
        "pos_payment_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_operation_type", sa.String(length=96), nullable=True),
        sa.Column("canonical_hint", sa.String(length=96), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_payment_types_external_identity"),
    )
    _create_external_indexes("pos_payment_types")

    op.create_table(
        "pos_product_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("pos_product_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="GROUP"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_product_groups_external_identity"),
        sa.CheckConstraint("kind IN ('GROUP', 'CATEGORY')", name="ck_pos_product_groups_kind"),
    )
    _create_external_indexes("pos_product_groups", extra=("parent_id",))

    op.create_table(
        "pos_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("pos_product_groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("pos_product_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=True),
        sa.Column("barcode", sa.String(length=128), nullable=True),
        sa.Column("product_type", sa.String(length=64), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_products_external_identity"),
    )
    _create_external_indexes("pos_products", extra=("group_id", "category_id"))

    op.create_table(
        "pos_product_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("price", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_product_prices_external_identity"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_pos_product_prices_period"),
    )
    _create_external_indexes("pos_product_prices", extra=("product_id", "venue_id"))

    op.create_table(
        "pos_employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_employees_external_identity"),
    )
    _create_external_indexes("pos_employees")

    op.create_table(
        "pos_warehouses",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("warehouse_type", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_warehouses_external_identity"),
    )
    _create_external_indexes("pos_warehouses", extra=("venue_id",))

    op.create_table(
        "pos_suppliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_suppliers_external_identity"),
    )
    _create_external_indexes("pos_suppliers")

    op.create_table(
        "pos_business_shifts",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("terminal_id", sa.Integer(), sa.ForeignKey("pos_terminals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("shift_number", sa.String(length=128), nullable=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("shift_slot", sa.String(length=16), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="UNKNOWN"),
        sa.Column("orders_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revenue_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("refund_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("writeoff_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_business_shifts_external_identity"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CLOSED', 'CANCELLED', 'DELETED', 'UNKNOWN')",
            name="ck_pos_business_shifts_status",
        ),
    )
    _create_external_indexes("pos_business_shifts", extra=("venue_id", "terminal_id", "business_date"))

    op.create_table(
        "pos_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("venues.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "business_shift_id",
            sa.Integer(),
            sa.ForeignKey("pos_business_shifts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("terminal_id", sa.Integer(), sa.ForeignKey("pos_terminals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_number", sa.String(length=128), nullable=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="UNKNOWN"),
        sa.Column("guests_count", sa.Integer(), nullable=True),
        sa.Column("gross_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("net_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("payment_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("refund_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_orders_external_identity"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CLOSED', 'CANCELLED', 'REFUNDED', 'PARTIALLY_REFUNDED', 'DELETED', 'UNKNOWN')",
            name="ck_pos_orders_status",
        ),
    )
    _create_external_indexes(
        "pos_orders", extra=("venue_id", "business_shift_id", "terminal_id", "employee_id", "business_date")
    )

    op.create_table(
        "pos_order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("pos_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_line_number", sa.String(length=128), nullable=True),
        sa.Column("product_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("group_name_snapshot", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("gross_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("discount_amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("net_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("cost_amount", sa.Numeric(20, 4), nullable=True),
        sa.Column("is_modifier", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_refund", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_order_items_external_identity"),
    )
    _create_external_indexes("pos_order_items", extra=("order_id", "product_id"))

    op.create_table(
        "pos_order_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("canonical_event_type", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details_json", JSON_TYPE, nullable=True),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_order_events_external_identity"),
    )
    _create_external_indexes("pos_order_events", extra=("order_id",))

    op.create_table(
        "pos_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "payment_type_id",
            sa.Integer(),
            sa.ForeignKey("pos_payment_types.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("canonical_type", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_payments_external_identity"),
    )
    _create_external_indexes("pos_payments", extra=("order_id", "payment_type_id"))

    op.create_table(
        "pos_refunds",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("pos_payments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("pos_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_refunds_external_identity"),
    )
    _create_external_indexes("pos_refunds", extra=("order_id", "payment_id", "employee_id"))

    op.create_table(
        "pos_order_discounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_external_columns(),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("pos_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_discount_name", sa.String(length=255), nullable=True),
        sa.Column("canonical_type", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("percent", sa.Numeric(9, 4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_pos_order_discounts_external_identity"),
    )
    _create_external_indexes("pos_order_discounts", extra=("order_id",))


def downgrade() -> None:
    for table_name in (
        "pos_order_discounts",
        "pos_refunds",
        "pos_payments",
        "pos_order_events",
        "pos_order_items",
        "pos_orders",
        "pos_business_shifts",
        "pos_suppliers",
        "pos_warehouses",
        "pos_employees",
        "pos_product_prices",
        "pos_products",
        "pos_product_groups",
        "pos_payment_types",
        "pos_terminals",
        "pos_venues",
        "pos_organizations",
        "integration_reconciliation_runs",
        "integration_quarantine",
        "integration_sync_jobs",
        "integration_sync_cursors",
        "integration_raw_objects",
        "integration_sync_runs",
        "integration_capability_states",
        "integration_connections",
    ):
        op.drop_table(table_name)
    op.drop_column("venues", "timezone")
