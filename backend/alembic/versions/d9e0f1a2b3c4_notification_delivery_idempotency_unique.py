"""enforce notification delivery idempotency

Revision ID: d9e0f1a2b3c4
Revises: b7d3f1a4c9e2, e1f9b7c3d2a1, 1b2c3d4e5f6a, 20c4c73c0eea, d93f2cb0f95a, 9f1e2d3c4b5a, c8d4e2f1a9b7, 6f8a0b1c2d3e, 7c1f6d2a4b10
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "3a4b5c6d7e8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "uq_notification_delivery_logs_idempotency_active"


def upgrade() -> None:
    # Keep the first active log for each idempotency key, mark the rest as duplicates
    # so the partial unique index can be created safely on existing databases.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY idempotency_key
                        ORDER BY
                            CASE
                                WHEN status = 'sent' THEN 0
                                WHEN status = 'pending' THEN 1
                                ELSE 2
                            END,
                            id ASC
                    ) AS rn
                FROM notification_delivery_logs
                WHERE idempotency_key IS NOT NULL
                  AND idempotency_key <> ''
                  AND status IN ('pending', 'sent')
            )
            UPDATE notification_delivery_logs AS logs
               SET status = 'duplicate',
                   error_text = COALESCE(NULLIF(logs.error_text, ''), 'deduplicated before idempotency unique index')
              FROM ranked
             WHERE logs.id = ranked.id
               AND ranked.rn > 1
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX_NAME}
                ON notification_delivery_logs (idempotency_key)
             WHERE idempotency_key IS NOT NULL
               AND idempotency_key <> ''
               AND status IN ('pending', 'sent')
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP INDEX IF EXISTS {_INDEX_NAME}"))
