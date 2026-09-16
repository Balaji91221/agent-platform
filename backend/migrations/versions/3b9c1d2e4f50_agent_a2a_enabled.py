"""per-agent A2A switch

Revision ID: 3b9c1d2e4f50
Revises: 17866881bddd
Create Date: 2026-09-16 10:05:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b9c1d2e4f50'
down_revision: Union[str, Sequence[str], None] = '17866881bddd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add agents.a2a_enabled, off for every existing agent."""
    op.add_column(
        'agents',
        sa.Column('a2a_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('agents', 'a2a_enabled')
