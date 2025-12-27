# migrations/alembic/versions/7b7ea95b1bc6_add_index_on_code_allowed_events.py
"""add index on code_allowed_events

Revision ID: 7b7ea95b1bc6
Revises: ecc5a822bcfd
Create Date: 2025-08-12 10:19:00.693941

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b7ea95b1bc6'
down_revision: Union[str, Sequence[str], None] = 'ecc5a822bcfd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "code_allowed_events",
        sa.Column("code_id", sa.Integer(), sa.ForeignKey("access_codes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id",   ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_code_allowed_events_code",  "code_allowed_events", ["code_id"])
    op.create_index("ix_code_allowed_events_event", "code_allowed_events", ["event_id"])

def downgrade():
    op.drop_index("ix_code_allowed_events_event", table_name="code_allowed_events")
    op.drop_index("ix_code_allowed_events_code",  table_name="code_allowed_events")
    op.drop_table("code_allowed_events")
