"""events table + fields

Revision ID: 5492d340bd62
Revises: 7b7ea95b1bc6
Create Date: 2025-08-12 12:20:52.186835

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5492d340bd62'
down_revision: Union[str, Sequence[str], None] = '7b7ea95b1bc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Idempotent upgrade: add missing event fields and sessions linkage."""

    bind = op.get_bind()
    insp = sa.inspect(bind)

    def has_table(t: str) -> bool:
        return t in insp.get_table_names()

    def has_column(t: str, c: str) -> bool:
        try:
            return any(col["name"] == c for col in insp.get_columns(t))
        except Exception:
            return False

    def has_index(t: str, name: str) -> bool:
        try:
            return any(ix.get("name") == name for ix in insp.get_indexes(t))
        except Exception:
            return False

    def has_unique(t: str, name: str) -> bool:
        try:
            return any(uq.get("name") == name for uq in insp.get_unique_constraints(t))
        except Exception:
            return False

    def has_fk(t: str, name: str) -> bool:
        try:
            return any(fk.get("name") == name for fk in insp.get_foreign_keys(t))
        except Exception:
            return False

    # --- EVENTS: додаємо лише відсутні поля ---
    if has_table("events"):
        with op.batch_alter_table("events") as batch:
            if not has_column("events", "slug"):
                batch.add_column(sa.Column("slug", sa.String(length=128), nullable=False))
            if not has_column("events", "status"):
                batch.add_column(sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"))
            if not has_column("events", "starts_at"):
                batch.add_column(sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True))
            if not has_column("events", "ends_at"):
                batch.add_column(sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True))
            if not has_column("events", "thumbnail_url"):
                batch.add_column(sa.Column("thumbnail_url", sa.Text(), nullable=True))
            if not has_column("events", "short_description"):
                batch.add_column(sa.Column("short_description", sa.Text(), nullable=True))
            if not has_column("events", "player_manifest_url"):
                batch.add_column(sa.Column("player_manifest_url", sa.Text(), nullable=True))
            if not has_column("events", "custom_mode"):
                batch.add_column(sa.Column("custom_mode", sa.String(length=16), nullable=False, server_default="none"))
            if not has_column("events", "custom_html"):
                batch.add_column(sa.Column("custom_html", sa.Text(), nullable=True))
            if not has_column("events", "custom_css"):
                batch.add_column(sa.Column("custom_css", sa.Text(), nullable=True))
            if not has_column("events", "custom_js"):
                batch.add_column(sa.Column("custom_js", sa.Text(), nullable=True))
            if not has_column("events", "theme"):
                batch.add_column(sa.Column("theme", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

        # індекс/унікальність на slug (створюємо, лише якщо відсутні)
        if has_column("events", "slug"):
            if not has_index("events", "ix_events_slug"):
                op.create_index("ix_events_slug", "events", ["slug"], unique=True)
            # якщо у тебе індекс з іншим імʼям, але без unique — можеш додати й унікальний констрейнт:
            if not has_unique("events", "uq_events_slug"):
                # спробуємо створити унікальний констрейнт додатково; якщо вже є унікальний індекс, Postgres це відхилить — ок
                try:
                    op.create_unique_constraint("uq_events_slug", "events", ["slug"])
                except Exception:
                    pass

    # --- SESSIONS: звʼязок на події ---
    if has_table("sessions"):
        if not has_column("sessions", "event_id"):
            with op.batch_alter_table("sessions") as batch:
                batch.add_column(sa.Column("event_id", sa.Integer(), nullable=True))
        if not has_fk("sessions", "fk_sessions_event") and has_table("events"):
            try:
                op.create_foreign_key(
                    "fk_sessions_event",
                    source_table="sessions",
                    referent_table="events",
                    local_cols=["event_id"],
                    remote_cols=["id"],
                    ondelete="SET NULL",
                )
            except Exception:
                # якщо FK з іншим імʼям уже існує — ігноруємо
                pass


def downgrade() -> None:
    """Idempotent downgrade: remove linkage and event extra fields if present."""

    bind = op.get_bind()
    insp = sa.inspect(bind)

    def has_table(t: str) -> bool:
        return t in insp.get_table_names()

    def has_column(t: str, c: str) -> bool:
        try:
            return any(col["name"] == c for col in insp.get_columns(t))
        except Exception:
            return False

    def has_index(t: str, name: str) -> bool:
        try:
            return any(ix.get("name") == name for ix in insp.get_indexes(t))
        except Exception:
            return False

    def has_unique(t: str, name: str) -> bool:
        try:
            return any(uq.get("name") == name for uq in insp.get_unique_constraints(t))
        except Exception:
            return False

    def has_fk(t: str, name: str) -> bool:
        try:
            return any(fk.get("name") == name for fk in insp.get_foreign_keys(t))
        except Exception:
            return False

    # --- SESSIONS: прибираємо FK і колонку, якщо є ---
    if has_table("sessions"):
        if has_fk("sessions", "fk_sessions_event"):
            op.drop_constraint("fk_sessions_event", "sessions", type_="foreignkey")
        if has_column("sessions", "event_id"):
            with op.batch_alter_table("sessions") as batch:
                batch.drop_column("event_id")

    # --- EVENTS: дроп індексу/констрейнту, потім колонок (лише якщо існують) ---
    if has_table("events"):
        if has_index("events", "ix_events_slug"):
            op.drop_index("ix_events_slug", table_name="events")
        if has_unique("events", "uq_events_slug"):
            try:
                op.drop_constraint("uq_events_slug", "events", type_="unique")
            except Exception:
                pass

        with op.batch_alter_table("events") as batch:
            for col in ["theme", "custom_js", "custom_css", "custom_html", "custom_mode",
                        "player_manifest_url", "short_description", "thumbnail_url",
                        "ends_at", "starts_at", "status", "slug"]:
                if has_column("events", col):
                    batch.drop_column(col)
