# migrations/alembic/versions/5cf35b8715a6_expires_at_timestamptz.py
"""expires_at -> timestamptz

Revision ID: 5cf35b8715a6
Revises: d7a91cacbc7b
Create Date: 2025-08-09 19:37:54.099124

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5cf35b8715a6'
down_revision: Union[str, Sequence[str], None] = 'd7a91cacbc7b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # якщо колонки ще не існує, цей крок можна пропустити або обгорнути try/except
    op.alter_column(
        'access_codes', 'expires_at',
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(timezone=False),
        postgresql_using="timezone('UTC', expires_at)"
    )

def downgrade():
    op.alter_column(
        'access_codes', 'expires_at',
        type_=sa.DateTime(timezone=False),
        existing_type=sa.DateTime(timezone=True),
        postgresql_using="expires_at AT TIME ZONE 'UTC'"
    )
