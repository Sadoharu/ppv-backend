"""add expires_at to access_codes

Revision ID: d7a91cacbc7b
Revises: d3337c4381fd
Create Date: 2025-08-09 05:29:03.619192

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7a91cacbc7b'
down_revision: Union[str, Sequence[str], None] = 'd3337c4381fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'access_codes',
        sa.Column('expires_at', sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('access_codes', 'expires_at')