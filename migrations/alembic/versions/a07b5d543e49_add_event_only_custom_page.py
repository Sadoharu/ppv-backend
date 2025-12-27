# migrations/alembic/versions/a07b5d543e49_add_event_only_custom_page.py
"""add_event_only_custom_page

Revision ID: a07b5d543e49
Revises: d48e3a3ea20e
Create Date: 2025-08-31 15:42:36.429767

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import func


# revision identifiers, used by Alembic.
revision: str = 'a07b5d543e49'
down_revision: Union[str, Sequence[str], None] = 'd48e3a3ea20e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column("events", sa.Column("page_html", sa.Text(), nullable=False, server_default=""))
    op.add_column("events", sa.Column("page_css", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("page_js", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("runtime_js_version", sa.String(length=32), nullable=False, server_default="latest"))
    op.add_column("events", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("assets_base_url", sa.String(length=512), nullable=True))
    op.add_column("events", sa.Column("etag", sa.String(length=64), nullable=True))
    op.add_column("events", sa.Column("preview_token", sa.String(length=64), nullable=True))
    op.add_column("events", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=func.now(), nullable=False))

    op.create_index("ix_events_etag", "events", ["etag"], unique=False)
    op.create_index("ix_events_preview_token", "events", ["preview_token"], unique=False)


def downgrade():
    op.drop_index("ix_events_preview_token", table_name="events")
    op.drop_index("ix_events_etag", table_name="events")

    op.drop_column("events", "updated_at")
    op.drop_column("events", "preview_token")
    op.drop_column("events", "etag")
    op.drop_column("events", "assets_base_url")
    op.drop_column("events", "published_at")
    op.drop_column("events", "runtime_js_version")
    op.drop_column("events", "page_js")
    op.drop_column("events", "page_css")
    op.drop_column("events", "page_html")
