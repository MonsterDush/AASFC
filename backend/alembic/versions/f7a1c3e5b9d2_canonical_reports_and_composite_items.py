"""canonical report reads and provider-neutral composite order items

Revision ID: f7a1c3e5b9d2
Revises: f5d9a2c7e4b1
"""

from datetime import datetime, timezone
import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "f7a1c3e5b9d2"
down_revision = "f5d9a2c7e4b1"
branch_labels = None
depends_on = None


def _source_hash(*, report_id: int, kind: str, ref_id: int, value: int) -> str:
    encoded = json.dumps(
        {"report_id": report_id, "kind": kind, "ref_id": ref_id, "value": value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _backfill_manual_contributions() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    reports = sa.Table("daily_reports", metadata, autoload_with=bind)
    values = sa.Table("daily_report_values", metadata, autoload_with=bind)
    contributions = sa.Table("report_value_contributions", metadata, autoload_with=bind)
    now = datetime.now(timezone.utc)
    payload: list[dict] = []
    existing_source_ids = set(
        bind.execute(
            sa.select(contributions.c.source_id).where(contributions.c.source_type == "MANUAL")
        ).scalars()
    )

    def flush_payload() -> None:
        if payload:
            bind.execute(contributions.insert(), list(payload))
            payload.clear()

    for row in bind.execute(
        sa.select(
            reports.c.id,
            reports.c.revenue_total,
            reports.c.unallocated_revenue_total,
        ).order_by(reports.c.id)
    ).mappings():
        report_id = int(row["id"])
        for kind, value in (
            ("REVENUE", int(row["revenue_total"] or 0)),
            ("UNALLOCATED_REVENUE", int(row["unallocated_revenue_total"] or 0)),
        ):
            source_id = f"DailyReport:{report_id}:{kind}:0"
            if source_id in existing_source_ids:
                continue
            payload.append(
                {
                    "report_id": report_id,
                    "kind": kind,
                    "ref_id": 0,
                    "source_type": "MANUAL",
                    "source_id": source_id,
                    "value_numeric": value,
                    "source_hash": _source_hash(report_id=report_id, kind=kind, ref_id=0, value=value),
                    "created_at": now,
                    "updated_at": now,
                }
            )
        if len(payload) >= 1000:
            flush_payload()

    for row in bind.execute(
        sa.select(values.c.report_id, values.c.kind, values.c.ref_id, values.c.value_numeric).order_by(values.c.id)
    ).mappings():
        report_id = int(row["report_id"])
        kind = str(row["kind"]).upper()
        ref_id = int(row["ref_id"])
        value = int(row["value_numeric"] or 0)
        source_id = f"DailyReport:{report_id}:{kind}:{ref_id}"
        if source_id in existing_source_ids:
            continue
        payload.append(
            {
                "report_id": report_id,
                "kind": kind,
                "ref_id": ref_id,
                "source_type": "MANUAL",
                "source_id": source_id,
                "value_numeric": value,
                "source_hash": _source_hash(report_id=report_id, kind=kind, ref_id=ref_id, value=value),
                "created_at": now,
                "updated_at": now,
            }
        )
        if len(payload) >= 1000:
            flush_payload()
    flush_payload()


def upgrade() -> None:
    with op.batch_alter_table("pos_order_items") as batch_op:
        batch_op.add_column(sa.Column("parent_item_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("item_role", sa.String(length=16), nullable=False, server_default="PRODUCT")
        )
        batch_op.add_column(sa.Column("component_role", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("attributed_net_amount", sa.Numeric(20, 4), nullable=True))
        batch_op.add_column(
            sa.Column("included_in_parent", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.create_foreign_key(
            "fk_pos_order_items_parent_item_id",
            "pos_order_items",
            ["parent_item_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_check_constraint(
            "ck_pos_order_items_item_role",
            "item_role IN ('PRODUCT', 'COMPOUND', 'COMPONENT', 'MODIFIER')",
        )
        batch_op.create_check_constraint(
            "ck_pos_order_items_component_role",
            "component_role IS NULL OR component_role IN ('PRIMARY', 'SECONDARY', 'COMMON', 'MODIFIER')",
        )
    op.create_index("ix_pos_order_items_parent_item_id", "pos_order_items", ["parent_item_id"])
    _backfill_manual_contributions()


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM report_value_contributions WHERE source_type = 'MANUAL'")
    )
    op.drop_index("ix_pos_order_items_parent_item_id", table_name="pos_order_items")
    with op.batch_alter_table("pos_order_items") as batch_op:
        batch_op.drop_constraint("ck_pos_order_items_component_role", type_="check")
        batch_op.drop_constraint("ck_pos_order_items_item_role", type_="check")
        batch_op.drop_constraint("fk_pos_order_items_parent_item_id", type_="foreignkey")
        batch_op.drop_column("included_in_parent")
        batch_op.drop_column("attributed_net_amount")
        batch_op.drop_column("component_role")
        batch_op.drop_column("item_role")
        batch_op.drop_column("parent_item_id")
