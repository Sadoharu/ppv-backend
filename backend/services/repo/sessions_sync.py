#v0.5
from __future__ import annotations
from sqlalchemy.orm import Session as DB
from sqlalchemy import select, func
from backend import models

def get_active_sessions_count(db: DB, code_id: int) -> int:
    q = select(func.count()).select_from(models.Session).where(
        models.Session.code_id == code_id,
        models.Session.active.is_(True),
    )
    return int(db.execute(q).scalar_one())
