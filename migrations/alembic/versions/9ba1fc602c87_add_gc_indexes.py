# migrations/alembic/versions/9ba1fc602c87_add_gc_indexes.py
"""Add GC indexes

Revision ID: 9ba1fc602c87
Revises: 5cf35b8715a6
Create Date: 2025-08-12 09:02:17.119848

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ba1fc602c87'
down_revision: Union[str, Sequence[str], None] = '5cf35b8715a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # sessions: комбінований по (active, last_seen) — для GC та списків
    op.create_index(
        "ix_sessions_active_last_seen",
        "sessions",
        ["active", "last_seen"],
        unique=False
    )
    # sessions: по created_at — fallback для дуже старих без last_seen
    op.create_index(
        "ix_sessions_created_at",
        "sessions",
        ["created_at"],
        unique=False
    )
    # (додатково) sessions: по (code_id, active) — пришвидшить логін і revoke
    op.create_index(
        "ix_sessions_code_active",
        "sessions",
        ["code_id", "active"],
        unique=False
    )
    # refresh_tokens: по revoked_at — GC старих токенів
    op.create_index(
        "ix_refresh_tokens_revoked_at",
        "refresh_tokens",
        ["revoked_at"],
        unique=False
    )
    # session_events: по at — GC старих подій
    op.create_index(
        "ix_session_events_at",
        "session_events",
        ["at"],
        unique=False
    )

def downgrade() -> None:
    op.drop_index("ix_session_events_at", table_name="session_events")
    op.drop_index("ix_refresh_tokens_revoked_at", table_name="refresh_tokens")
    op.drop_index("ix_sessions_code_active", table_name="sessions")
    op.drop_index("ix_sessions_created_at", table_name="sessions")
    op.drop_index("ix_sessions_active_last_seen", table_name="sessions")
