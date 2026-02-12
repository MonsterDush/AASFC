"""add shifts and shift_intervals

Revision ID: 4f2c0d1b7a21
Revises: 2b7d9c1a8c61
Create Date: 2026-02-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4f2c0d1b7a21'
down_revision: Union[str, Sequence[str], None] = '2b7d9c1a8c61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'shift_intervals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('venue_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=100), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.ForeignKeyConstraint(['venue_id'], ['venues.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('venue_id', 'title', name='uq_shift_intervals_title'),
    )
    op.create_index(op.f('ix_shift_intervals_venue_id'), 'shift_intervals', ['venue_id'], unique=False)

    op.create_table(
        'shifts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('venue_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('interval_id', sa.Integer(), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['interval_id'], ['shift_intervals.id']),
        sa.ForeignKeyConstraint(['venue_id'], ['venues.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('venue_id', 'date', 'interval_id', name='uq_shifts_venue_date_interval'),
    )
    op.create_index(op.f('ix_shifts_venue_id'), 'shifts', ['venue_id'], unique=False)
    op.create_index(op.f('ix_shifts_date'), 'shifts', ['date'], unique=False)
    op.create_index(op.f('ix_shifts_interval_id'), 'shifts', ['interval_id'], unique=False)

    op.create_table(
        'shift_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('shift_id', sa.Integer(), nullable=False),
        sa.Column('member_user_id', sa.Integer(), nullable=False),
        sa.Column('venue_position_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['member_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['shift_id'], ['shifts.id']),
        sa.ForeignKeyConstraint(['venue_position_id'], ['venue_positions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shift_id', 'member_user_id', name='uq_shift_assignment_member'),
    )
    op.create_index(op.f('ix_shift_assignments_shift_id'), 'shift_assignments', ['shift_id'], unique=False)
    op.create_index(op.f('ix_shift_assignments_member_user_id'), 'shift_assignments', ['member_user_id'], unique=False)
    op.create_index(op.f('ix_shift_assignments_venue_position_id'), 'shift_assignments', ['venue_position_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_shift_assignments_venue_position_id'), table_name='shift_assignments')
    op.drop_index(op.f('ix_shift_assignments_member_user_id'), table_name='shift_assignments')
    op.drop_index(op.f('ix_shift_assignments_shift_id'), table_name='shift_assignments')
    op.drop_table('shift_assignments')

    op.drop_index(op.f('ix_shifts_interval_id'), table_name='shifts')
    op.drop_index(op.f('ix_shifts_date'), table_name='shifts')
    op.drop_index(op.f('ix_shifts_venue_id'), table_name='shifts')
    op.drop_table('shifts')

    op.drop_index(op.f('ix_shift_intervals_venue_id'), table_name='shift_intervals')
    op.drop_table('shift_intervals')
