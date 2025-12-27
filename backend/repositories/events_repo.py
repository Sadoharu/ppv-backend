# backend/repositories/events_repo.py
from typing import Iterable, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DB

from backend import models

def is_slug_taken(db: DB, slug: str, exclude_id: Optional[int] = None) -> bool:
    q = select(models.Event.id).where(func.lower(models.Event.slug) == func.lower(slug))
    if exclude_id:
        q = q.where(models.Event.id != exclude_id)
    return db.execute(q).scalar_one_or_none() is not None

def create_event(db: DB, **fields) -> models.Event:
    e = models.Event(**fields)
    db.add(e)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    db.refresh(e)
    return e

def get_event(db: DB, event_id: int) -> Optional[models.Event]:
    return db.get(models.Event, event_id)

def delete_event(db: DB, event_id: int) -> bool:
    e = db.get(models.Event, event_id)
    if not e:
        return False
    db.delete(e)
    db.commit()
    return True

def update_event(db: DB, e: models.Event, **fields) -> models.Event:
    for k, v in fields.items():
        setattr(e, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    db.refresh(e)
    return e

def list_events(
    db: DB,
    q: Optional[str],
    page: int,
    page_size: int,
) -> Tuple[int, Iterable[models.Event]]:
    stmt = select(models.Event)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            (models.Event.title.ilike(like)) | (models.Event.slug.ilike(like))
        )
    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    stmt = (
        stmt.order_by(models.Event.starts_at.asc().nulls_last(), models.Event.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = db.execute(stmt).scalars().all()
    return total, rows
