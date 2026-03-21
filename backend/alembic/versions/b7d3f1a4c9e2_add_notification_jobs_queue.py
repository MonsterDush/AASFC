"""add notification jobs queue

Revision ID: b7d3f1a4c9e2
Revises: a9e1f0c2d3b4
Create Date: 2026-03-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'b7d3f1a4c9e2'
down_revision = 'a9e1f0c2d3b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'notification_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('job_type', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('run_after', sa.DateTime(timezone=True), nullable=False),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('idempotency_key', sa.String(length=190), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_notification_jobs_job_type', 'notification_jobs', ['job_type'])
    op.create_index('ix_notification_jobs_status', 'notification_jobs', ['status'])
    op.create_index('ix_notification_jobs_run_after', 'notification_jobs', ['run_after'])
    op.create_index('ix_notification_jobs_idempotency_key', 'notification_jobs', ['idempotency_key'])


def downgrade() -> None:
    op.drop_index('ix_notification_jobs_idempotency_key', table_name='notification_jobs')
    op.drop_index('ix_notification_jobs_run_after', table_name='notification_jobs')
    op.drop_index('ix_notification_jobs_status', table_name='notification_jobs')
    op.drop_index('ix_notification_jobs_job_type', table_name='notification_jobs')
    op.drop_table('notification_jobs')
