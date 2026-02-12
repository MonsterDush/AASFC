"""add venue_positions

Revision ID: 2b7d9c1a8c61
Revises: 957b0901f9a3
Create Date: 2026-02-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b7d9c1a8c61'
down_revision: Union[str, Sequence[str], None] = '957b0901f9a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'venue_positions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('venue_id', sa.Integer(), nullable=False),
        sa.Column('member_user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=100), nullable=False),
        sa.Column('rate', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('percent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('can_make_reports', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('can_edit_schedule', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.ForeignKeyConstraint(['member_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('venue_id', 'member_user_id', name='uq_venue_position_member'),
    )
    op.create_index(op.f('ix_venue_positions_venue_id'), 'venue_positions', ['venue_id'], unique=False)
    op.create_index(op.f('ix_venue_positions_member_user_id'), 'venue_positions', ['member_user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_venue_positions_member_user_id'), table_name='venue_positions')
    op.drop_index(op.f('ix_venue_positions_venue_id'), table_name='venue_positions')
    op.drop_table('venue_positions')
