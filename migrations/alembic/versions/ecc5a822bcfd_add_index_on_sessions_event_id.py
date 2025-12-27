# migrations/alembic/versions/ecc5a822bcfd_add_index_on_sessions_event_id.py
"""add index on sessions.event_id

Revision ID: ecc5a822bcfd
Revises: f87c0d05da92
Create Date: 2025-08-12 10:17:36.407258

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ecc5a822bcfd'
down_revision: Union[str, Sequence[str], None] = 'f87c0d05da92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column("sessions", sa.Column("event_id", sa.Integer(), nullable=True))
    op.create_index("ix_sessions_event_id", "sessions", ["event_id"])
    op.create_foreign_key(
        "fk_sessions_event_id_events",
        "sessions", "events",
        ["event_id"], ["id"],
        ondelete=None
    )

def downgrade():
    op.drop_constraint("fk_sessions_event_id_events", "sessions", type_="foreignkey")
    op.drop_index("ix_sessions_event_id", table_name="sessions")
    op.drop_column("sessions", "event_id")
