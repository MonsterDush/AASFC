"""backfill stable catalog positions for existing venues

Revision ID: b9d2e4f6a8c1
Revises: f6b4d2a8c1e0
Create Date: 2026-09-04
"""

from __future__ import annotations

import json
from typing import Iterator, Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b9d2e4f6a8c1"
down_revision: Union[str, Sequence[str], None] = "f6b4d2a8c1e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _active_setup_presets(bind) -> Iterator[dict]:
    rows = bind.execute(
        sa.text(
            """
            SELECT id, venue_id, step_meta_json
            FROM venue_setup_state
            WHERE step_meta_json IS NOT NULL
            ORDER BY venue_id, id
            """
        )
    ).mappings()

    for row in rows:
        meta = row["step_meta_json"]

        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (TypeError, ValueError):
                continue

        if not isinstance(meta, dict):
            continue

        positions = meta.get("positions") or {}
        if not isinstance(positions, dict):
            continue

        presets = positions.get("presets") or []
        if not isinstance(presets, list):
            continue

        for raw in presets:
            if not isinstance(raw, dict):
                continue
            if raw.get("is_active") is False:
                continue

            title = str(raw.get("title") or "").strip()[:100]
            if not title:
                continue

            yield {
                "venue_id": int(row["venue_id"]),
                "title": title,
                "rate": max(0, _as_int(raw.get("rate"))),
                "percent": max(0, min(100, _as_int(raw.get("percent")))),
                "pay_profile_id": None,
                "permission_codes": None,
            }


def upgrade() -> None:
    bind = op.get_bind()

    desired: dict[tuple[int, str], dict] = {}

    assigned_rows = bind.execute(
        sa.text(
            """
            SELECT
                id,
                venue_id,
                title,
                rate,
                percent,
                pay_profile_id,
                permission_codes
            FROM venue_positions
            WHERE member_user_id IS NOT NULL
              AND is_active = true
              AND TRIM(title) <> ''
            ORDER BY venue_id, title, id
            """
        )
    ).mappings()

    for row in assigned_rows:
        venue_id = int(row["venue_id"])
        title = str(row["title"] or "").strip()

        if not title:
            continue

        key = (venue_id, title)

        desired.setdefault(
            key,
            {
                "venue_id": venue_id,
                "title": title,
                "rate": int(row["rate"] or 0),
                "percent": int(row["percent"] or 0),
                "pay_profile_id": row["pay_profile_id"],
                "permission_codes": row["permission_codes"],
            },
        )

    for preset in _active_setup_presets(bind):
        key = (int(preset["venue_id"]), str(preset["title"]))
        desired.setdefault(key, preset)

    existing_rows = bind.execute(
        sa.text(
            """
            SELECT id, venue_id, title, is_active
            FROM venue_positions
            WHERE member_user_id IS NULL
              AND TRIM(title) <> ''
            ORDER BY venue_id, title, is_active DESC, id
            """
        )
    ).mappings()

    catalog_by_key: dict[tuple[int, str], dict] = {}

    for row in existing_rows:
        key = (
            int(row["venue_id"]),
            str(row["title"] or "").strip(),
        )
        catalog_by_key.setdefault(key, row)

    for key, payload in desired.items():
        current = catalog_by_key.get(key)

        if current is not None:
            if not bool(current["is_active"]):
                bind.execute(
                    sa.text(
                        """
                        UPDATE venue_positions
                        SET is_active = true
                        WHERE id = :position_id
                        """
                    ),
                    {"position_id": int(current["id"])},
                )
            continue

        bind.execute(
            sa.text(
                """
                INSERT INTO venue_positions (
                    venue_id,
                    member_user_id,
                    title,
                    rate,
                    percent,
                    pay_profile_id,
                    permission_codes,
                    is_active
                )
                VALUES (
                    :venue_id,
                    NULL,
                    :title,
                    :rate,
                    :percent,
                    :pay_profile_id,
                    :permission_codes,
                    true
                )
                """
            ),
            payload,
        )


def downgrade() -> None:
    # Data-only compatibility migration.
    #
    # Do not delete catalog positions here. A user may already have manually
    # attached an interval to a catalog position after this migration.
    pass
