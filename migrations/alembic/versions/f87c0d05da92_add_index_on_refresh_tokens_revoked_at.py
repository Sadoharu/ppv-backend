# migrations/alembic/versions/f87c0d05da92_add_index_on_refresh_tokens_revoked_at.py
"""add index on refresh_tokens.revoked_at

Revision ID: f87c0d05da92
Revises: 9ba1fc602c87
Create Date: 2025-08-12 09:18:32.504362

"""
from typing import Sequence, Union

from alembic import op
from alembic import context
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'f87c0d05da92'
down_revision: Union[str, Sequence[str], None] = '9ba1fc602c87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    ctx = op.get_context()
    if ctx.dialect.name != "postgresql":
        # dev/SQLite — звичайний індекс
        op.create_index(
            "ix_refresh_tokens_revoked_at",
            "refresh_tokens",
            ["revoked_at"],
            unique=False,
            if_not_exists=True,
        )
        return

    # Postgres: потрібен autocommit + правильний порядок ключових слів
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_refresh_tokens_revoked_at "
            "ON refresh_tokens (revoked_at)"
        )

def downgrade():
    ctx = op.get_context()
    if ctx.dialect.name != "postgresql":
        op.drop_index(
            "ix_refresh_tokens_revoked_at",
            table_name="refresh_tokens",
            if_exists=True,
        )
        return

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_refresh_tokens_revoked_at")