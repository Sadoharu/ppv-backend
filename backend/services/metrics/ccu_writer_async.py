#unused
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from backend import models
from backend.utils.dt import now_utc
from backend.services.session.online import ccu_estimate

async def write_ccu_minutely(db: AsyncSession) -> None:
    """
    Щохвилини читає CCU з Redis (глобальний online:z) і пише у таблицю CCUMinutely.
    """
    ccu = ccu_estimate()
    ts = now_utc().replace(second=0, microsecond=0)
    await db.merge(models.CCUMinutely(ts=ts, ccu=ccu))
    await db.commit()
