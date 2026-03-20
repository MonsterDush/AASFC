"""expand notification preferences and add delivery logs

Revision ID: a9e1f0c2d3b4
Revises: 9f1e2d3c4b5a
Create Date: 2026-03-21 23:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9e1f0c2d3b4'
down_revision: Union[str, Sequence[str], None] = '9f1e2d3c4b5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('notify_day_economics', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('users', sa.Column('notify_salary', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('users', sa.Column('notify_soft_alerts', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('users', sa.Column('shift_reminder_lead_time_hours', sa.Integer(), nullable=False, server_default='18'))
    op.add_column('users', sa.Column('notification_detail_level', sa.String(length=16), nullable=False, server_default='standard'))
    op.alter_column('users', 'notify_day_economics', server_default=None)
    op.alter_column('users', 'notify_salary', server_default=None)
    op.alter_column('users', 'notify_soft_alerts', server_default=None)
    op.alter_column('users', 'shift_reminder_lead_time_hours', server_default=None)
    op.alter_column('users', 'notification_detail_level', server_default=None)

    op.create_table(
        'notification_delivery_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('notification_type', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('venue_id', sa.Integer(), nullable=True),
        sa.Column('shift_id', sa.Integer(), nullable=True),
        sa.Column('shift_assignment_id', sa.Integer(), nullable=True),
        sa.Column('planned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('idempotency_key', sa.String(length=190), nullable=True),
        sa.Column('error_text', sa.Text(), nullable=True),
        sa.Column('payload_preview', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['shift_assignment_id'], ['shift_assignments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['shift_id'], ['shifts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_notification_delivery_logs_notification_type'), 'notification_delivery_logs', ['notification_type'], unique=False)
    op.create_index(op.f('ix_notification_delivery_logs_status'), 'notification_delivery_logs', ['status'], unique=False)
    op.create_index(op.f('ix_notification_delivery_logs_user_id'), 'notification_delivery_logs', ['user_id'], unique=False)
    op.create_index(op.f('ix_notification_delivery_logs_venue_id'), 'notification_delivery_logs', ['venue_id'], unique=False)
    op.create_index(op.f('ix_notification_delivery_logs_shift_id'), 'notification_delivery_logs', ['shift_id'], unique=False)
    op.create_index(op.f('ix_notification_delivery_logs_shift_assignment_id'), 'notification_delivery_logs', ['shift_assignment_id'], unique=False)
    op.create_index(op.f('ix_notification_delivery_logs_idempotency_key'), 'notification_delivery_logs', ['idempotency_key'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_notification_delivery_logs_idempotency_key'), table_name='notification_delivery_logs')
    op.drop_index(op.f('ix_notification_delivery_logs_shift_assignment_id'), table_name='notification_delivery_logs')
    op.drop_index(op.f('ix_notification_delivery_logs_shift_id'), table_name='notification_delivery_logs')
    op.drop_index(op.f('ix_notification_delivery_logs_venue_id'), table_name='notification_delivery_logs')
    op.drop_index(op.f('ix_notification_delivery_logs_user_id'), table_name='notification_delivery_logs')
    op.drop_index(op.f('ix_notification_delivery_logs_status'), table_name='notification_delivery_logs')
    op.drop_index(op.f('ix_notification_delivery_logs_notification_type'), table_name='notification_delivery_logs')
    op.drop_table('notification_delivery_logs')

    op.drop_column('users', 'notification_detail_level')
    op.drop_column('users', 'shift_reminder_lead_time_hours')
    op.drop_column('users', 'notify_soft_alerts')
    op.drop_column('users', 'notify_salary')
    op.drop_column('users', 'notify_day_economics')
