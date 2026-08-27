"""multi positions, owner notes and position pay profiles

Revision ID: d4a9f6c2b8e1
Revises: c8e1f4a7b2d9
Create Date: 2026-08-26 23:55:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4a9f6c2b8e1"
down_revision: Union[str, Sequence[str], None] = "c8e1f4a7b2d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_owner_notes() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT venue_id, accepted_user_id, invited_contact_label
            FROM venue_invites
            WHERE accepted_user_id IS NOT NULL
              AND invited_contact_label IS NOT NULL
              AND TRIM(invited_contact_label) <> ''
            ORDER BY accepted_at DESC, id DESC
            """
        )
    ).mappings()
    seen: set[tuple[int, int]] = set()
    for row in rows:
        key = (int(row["venue_id"]), int(row["accepted_user_id"]))
        if key in seen:
            continue
        seen.add(key)
        bind.execute(
            sa.text(
                """
                UPDATE venue_members
                SET owner_note = :owner_note
                WHERE venue_id = :venue_id
                  AND user_id = :user_id
                  AND (owner_note IS NULL OR TRIM(owner_note) = '')
                """
            ),
            {
                "venue_id": key[0],
                "user_id": key[1],
                "owner_note": str(row["invited_contact_label"]).strip()[:500],
            },
        )


def _backfill_position_pay_profiles() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT venue_id, member_user_id, pay_profile_id
            FROM pay_profile_assignments
            WHERE is_active = true
            ORDER BY updated_at DESC, created_at DESC, id DESC
            """
        )
    ).mappings()
    seen: set[tuple[int, int]] = set()
    for row in rows:
        key = (int(row["venue_id"]), int(row["member_user_id"]))
        if key in seen:
            continue
        seen.add(key)
        bind.execute(
            sa.text(
                """
                UPDATE venue_positions
                SET pay_profile_id = :pay_profile_id
                WHERE venue_id = :venue_id
                  AND member_user_id = :member_user_id
                  AND pay_profile_id IS NULL
                """
            ),
            {
                "venue_id": key[0],
                "member_user_id": key[1],
                "pay_profile_id": int(row["pay_profile_id"]),
            },
        )


def upgrade() -> None:
    op.add_column("venue_members", sa.Column("owner_note", sa.String(length=500), nullable=True))
    op.add_column("venue_positions", sa.Column("pay_profile_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("venue_positions") as batch_op:
        batch_op.drop_constraint("uq_venue_position_member", type_="unique")
        batch_op.alter_column("member_user_id", existing_type=sa.Integer(), nullable=True)
        batch_op.create_foreign_key(
            "fk_venue_positions_pay_profile_id_pay_profiles",
            "pay_profiles",
            ["pay_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_venue_positions_pay_profile_id", ["pay_profile_id"], unique=False)

    _backfill_owner_notes()
    _backfill_position_pay_profiles()


def _collapse_positions_for_downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM venue_positions WHERE member_user_id IS NULL"))
    rows = list(
        bind.execute(
            sa.text(
                """
                SELECT id, venue_id, member_user_id
                FROM venue_positions
                ORDER BY venue_id, member_user_id, is_active DESC, id ASC
                """
            )
        ).mappings()
    )
    keep_by_member: dict[tuple[int, int], int] = {}
    for row in rows:
        key = (int(row["venue_id"]), int(row["member_user_id"]))
        keep_id = keep_by_member.get(key)
        if keep_id is None:
            keep_by_member[key] = int(row["id"])
            continue
        drop_id = int(row["id"])
        bind.execute(
            sa.text("UPDATE shift_assignments SET venue_position_id = :keep_id WHERE venue_position_id = :drop_id"),
            {"keep_id": keep_id, "drop_id": drop_id},
        )
        bind.execute(
            sa.text(
                "UPDATE shift_swap_requests SET replacement_position_id = :keep_id "
                "WHERE replacement_position_id = :drop_id"
            ),
            {"keep_id": keep_id, "drop_id": drop_id},
        )
        bind.execute(sa.text("DELETE FROM venue_positions WHERE id = :drop_id"), {"drop_id": drop_id})


def downgrade() -> None:
    _collapse_positions_for_downgrade()
    with op.batch_alter_table("venue_positions") as batch_op:
        batch_op.drop_constraint("fk_venue_positions_pay_profile_id_pay_profiles", type_="foreignkey")
        batch_op.drop_index("ix_venue_positions_pay_profile_id")
        batch_op.alter_column("member_user_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_unique_constraint("uq_venue_position_member", ["venue_id", "member_user_id"])
    op.drop_column("venue_positions", "pay_profile_id")
    op.drop_column("venue_members", "owner_note")
