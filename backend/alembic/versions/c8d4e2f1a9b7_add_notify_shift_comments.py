"""add notify_shift_comments user preference

Revision ID: c8d4e2f1a9b7
Revises: e8f1a2b3c4d5
Create Date: 2026-03-25 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'c8d4e2f1a9b7'
down_revision = 'e8f1a2b3c4d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('notify_shift_comments', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('notify_shift_comments')
