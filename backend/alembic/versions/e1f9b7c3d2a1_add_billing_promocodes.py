"""add billing promocodes

Revision ID: e1f9b7c3d2a1
Revises: b8c9d0e1f2a3
Create Date: 2026-04-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'e1f9b7c3d2a1'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'billing_promo_code',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('kind', sa.String(length=24), nullable=False),
        sa.Column('percent_value', sa.Integer(), nullable=True),
        sa.Column('amount_minor', sa.Integer(), nullable=True),
        sa.Column('free_days', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_billing_promo_code_code'), 'billing_promo_code', ['code'], unique=True)
    op.create_index(op.f('ix_billing_promo_code_kind'), 'billing_promo_code', ['kind'], unique=False)
    op.create_index(op.f('ix_billing_promo_code_is_active'), 'billing_promo_code', ['is_active'], unique=False)
    op.create_index(op.f('ix_billing_promo_code_created_by_user_id'), 'billing_promo_code', ['created_by_user_id'], unique=False)

    op.create_table(
        'billing_promo_redemption',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('promo_code_id', sa.Integer(), nullable=False),
        sa.Column('venue_id', sa.Integer(), nullable=False),
        sa.Column('billing_transaction_id', sa.Integer(), nullable=True),
        sa.Column('promo_code_value', sa.String(length=64), nullable=False),
        sa.Column('discount_minor', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('free_days_added', sa.Integer(), nullable=True),
        sa.Column('snapshot_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['billing_transaction_id'], ['venue_billing_transaction.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['promo_code_id'], ['billing_promo_code.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('billing_transaction_id'),
        sa.UniqueConstraint('venue_id', name='uq_billing_promo_redemption_venue_id'),
    )
    op.create_index(op.f('ix_billing_promo_redemption_promo_code_id'), 'billing_promo_redemption', ['promo_code_id'], unique=False)
    op.create_index(op.f('ix_billing_promo_redemption_venue_id'), 'billing_promo_redemption', ['venue_id'], unique=False)
    op.create_index(op.f('ix_billing_promo_redemption_billing_transaction_id'), 'billing_promo_redemption', ['billing_transaction_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_billing_promo_redemption_billing_transaction_id'), table_name='billing_promo_redemption')
    op.drop_index(op.f('ix_billing_promo_redemption_venue_id'), table_name='billing_promo_redemption')
    op.drop_index(op.f('ix_billing_promo_redemption_promo_code_id'), table_name='billing_promo_redemption')
    op.drop_table('billing_promo_redemption')

    op.drop_index(op.f('ix_billing_promo_code_created_by_user_id'), table_name='billing_promo_code')
    op.drop_index(op.f('ix_billing_promo_code_is_active'), table_name='billing_promo_code')
    op.drop_index(op.f('ix_billing_promo_code_kind'), table_name='billing_promo_code')
    op.drop_index(op.f('ix_billing_promo_code_code'), table_name='billing_promo_code')
    op.drop_table('billing_promo_code')
