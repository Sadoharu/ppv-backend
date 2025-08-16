#unused
from __future__ import annotations
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from backend import models
from backend.utils.dt import now_utc

async def record_watch_stats(db: AsyncSession, session_id: UUID, seconds: int, bytes_out: int) -> None:
    """
    Викликається при disconnect() глядача. Атомарно додає лічильники.
    """
    stmt = (
        update(models.Session)
        .where(models.Session.id == session_id)
        .values(
            watch_seconds = (models.Session.watch_seconds + int(seconds)),
            bytes_out     = (models.Session.bytes_out + int(bytes_out)),
            last_seen     = now_utc(),
        )
    )
    await db.execute(stmt)
    await db.commit()
