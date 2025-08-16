"""add index on allow_all_events

Revision ID: 1b7bd2219bee
Revises: 5492d340bd62
Create Date: 2025-08-12 15:14:45.693980

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b7bd2219bee'
down_revision: Union[str, Sequence[str], None] = '5492d340bd62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add access_codes.allow_all_events (idempotent)."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    def has_table(t: str) -> bool:
        try:
            return t in insp.get_table_names()
        except Exception:
            return False

    def has_column(t: str, c: str) -> bool:
        try:
            return any(col["name"] == c for col in insp.get_columns(t))
        except Exception:
            return False

    if has_table("access_codes") and not has_column("access_codes", "allow_all_events"):
        # додаємо NOT NULL з server_default=false, щоб не впасти на існуючих рядках
        op.add_column(
            "access_codes",
            sa.Column("allow_all_events", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
        # за бажанням можна прибрати server_default, щоб далі значення виставляв застосунок
        try:
            with op.batch_alter_table("access_codes") as batch:
                batch.alter_column("allow_all_events", server_default=None)
        except Exception:
            # необов'язково; якщо не вийшло — залишимо server_default=false
            pass


def downgrade() -> None:
    """Remove access_codes.allow_all_events if present (idempotent)."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    def has_table(t: str) -> bool:
        try:
            return t in insp.get_table_names()
        except Exception:
            return False

    def has_column(t: str, c: str) -> bool:
        try:
            return any(col["name"] == c for col in insp.get_columns(t))
        except Exception:
            return False

    if has_table("access_codes") and has_column("access_codes", "allow_all_events"):
        with op.batch_alter_table("access_codes") as batch:
            batch.drop_column("allow_all_events")
