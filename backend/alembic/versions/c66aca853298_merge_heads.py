"""merge heads

Revision ID: c66aca853298
Revises: 1b2c3d4e5f6a, 7c1f6d2a4b10
Create Date: 2026-02-13 18:51:07.855317

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c66aca853298'
down_revision: Union[str, Sequence[str], None] = ('1b2c3d4e5f6a', '7c1f6d2a4b10')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
