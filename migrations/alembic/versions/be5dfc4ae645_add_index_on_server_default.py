"""add index on server_default

Revision ID: be5dfc4ae645
Revises: 1b7bd2219bee
Create Date: 2025-08-12 18:50:02.434637

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be5dfc4ae645'
down_revision: Union[str, Sequence[str], None] = '1b7bd2219bee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # підстрахуємо існуючі NULL-и (якщо раптом є)
    op.execute("UPDATE code_batches SET created_at = NOW() WHERE created_at IS NULL;")
    # додаємо дефолт на рівні БД і робимо NOT NULL
    op.alter_column(
        "code_batches",
        "created_at",
        server_default=sa.text("NOW()"),
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

def downgrade():
    # прибираємо server default; NOT NULL залишати/знімати — на твій розсуд.
    op.alter_column(
        "code_batches",
        "created_at",
        server_default=None,
        existing_type=sa.DateTime(timezone=True),
        nullable=True,  # якщо хочеш як було до фіксу
    )
