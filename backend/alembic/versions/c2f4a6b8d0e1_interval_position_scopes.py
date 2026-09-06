"""Allow multiple interval roles and stable catalog links without changing assigned shifts."""

from alembic import op
import sqlalchemy as sa

revision = "c2f4a6b8d0e1"
down_revision = "b9d2e4f6a8c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("venue_positions") as batch:
        batch.add_column(sa.Column("catalog_position_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_venue_positions_catalog_position",
            "venue_positions",
            ["catalog_position_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_venue_positions_catalog_position_id", ["catalog_position_id"])
    bind = op.get_bind()
    positions = list(
        bind.execute(
            sa.text(
                "SELECT id, venue_id, member_user_id, title, is_active FROM venue_positions ORDER BY is_active DESC, id ASC"
            )
        ).mappings()
    )
    catalog = {}
    exact_catalog = {}
    equivalent_catalog_ids = {}
    for row in positions:
        if row["member_user_id"] is None:
            title = str(row["title"] or "").strip()
            key = (row["venue_id"], title.casefold())
            catalog.setdefault(key, row["id"])
            exact_catalog.setdefault((row["venue_id"], title), row["id"])
            equivalent_catalog_ids.setdefault(key, set()).add(row["id"])
    for row in positions:
        if row["member_user_id"] is not None:
            title = str(row["title"] or "").strip()
            catalog_id = exact_catalog.get((row["venue_id"], title), catalog.get((row["venue_id"], title.casefold())))
            if catalog_id is not None:
                bind.execute(
                    sa.text("UPDATE venue_positions SET catalog_position_id=:catalog_id WHERE id=:id"),
                    {"catalog_id": catalog_id, "id": row["id"]},
                )
    op.create_table(
        "shift_interval_positions",
        sa.Column(
            "interval_id", sa.Integer(), sa.ForeignKey("shift_intervals.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "position_id", sa.Integer(), sa.ForeignKey("venue_positions.id", ondelete="CASCADE"), primary_key=True
        ),
    )
    op.create_index("ix_shift_interval_positions_position_id", "shift_interval_positions", ["position_id"])
    # Legacy matching ignored case and surrounding spaces. Preserve its allowed
    # roles once, then use stable IDs for all subsequent configuration changes.
    by_id = {row["id"]: row for row in positions}
    intervals = list(
        bind.execute(
            sa.text("SELECT id, venue_id, position_id FROM shift_intervals WHERE position_id IS NOT NULL")
        ).mappings()
    )
    for interval in intervals:
        role = by_id[interval["position_id"]]
        key = (interval["venue_id"], str(role["title"] or "").strip().casefold())
        allowed_ids = equivalent_catalog_ids.get(key, set()) | {interval["position_id"]}
        for position_id in sorted(allowed_ids):
            bind.execute(
                sa.text(
                    "INSERT INTO shift_interval_positions (interval_id, position_id) VALUES (:interval_id, :position_id)"
                ),
                {"interval_id": interval["id"], "position_id": position_id},
            )


def downgrade() -> None:
    # An old application cannot represent several allowed roles. Do not silently discard that configuration.
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT interval_id FROM shift_interval_positions GROUP BY interval_id HAVING COUNT(*) > 1 LIMIT 1")
        )
        .first()
    ):
        raise RuntimeError("Set each interval to at most one allowed position before downgrading")
    op.drop_table("shift_interval_positions")
    with op.batch_alter_table("venue_positions") as batch:
        batch.drop_index("ix_venue_positions_catalog_position_id")
        batch.drop_constraint("fk_venue_positions_catalog_position", type_="foreignkey")
        batch.drop_column("catalog_position_id")
