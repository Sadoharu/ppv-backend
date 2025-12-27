# migrations/alembic/versions/d48e3a3ea20e_code_batches_created_at_server_default.py
"""code_batches created_at server default

Revision ID: d48e3a3ea20e
Revises: be5dfc4ae645
Create Date: 2025-08-12 19:03:35.891362

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd48e3a3ea20e'
down_revision: Union[str, Sequence[str], None] = 'be5dfc4ae645'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 1) backfill
    op.execute("UPDATE code_batches SET created_at = NOW() WHERE created_at IS NULL;")
    # 2) server default
    op.alter_column(
        "code_batches",
        "created_at",
        server_default=sa.text("NOW()"),
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

def downgrade():
    op.alter_column(
        "code_batches",
        "created_at",
        server_default=None,
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
