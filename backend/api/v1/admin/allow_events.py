# backend/api/v1/admin/allow_events.py
from __future__ import annotations
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DB
from sqlalchemy import select

from backend.database import get_db
from backend import models
from backend.api.deps import require_admin  # фабрика: require_admin("admin","super")

router = APIRouter(
    tags=["admin:codes-events"],
    dependencies=[Depends(require_admin("admin", "super"))],
)

class SetAllowedEventsIn(BaseModel):
    allow_all: bool = False
    event_ids: List[int] = Field(default_factory=list)
    event_slugs: Optional[List[str]] = Field(default=None, description="Опційно: перелік slug подій")

class AllowedEventsOut(BaseModel):
    code_id: int
    allow_all: bool
    event_ids: List[int] = Field(default_factory=list)

@router.get("/{code_id}/allow_events", response_model=AllowedEventsOut)
def get_allowed_events(code_id: int, db: DB = Depends(get_db)):
    code = db.get(models.AccessCode, code_id)
    if not code:
        raise HTTPException(status_code=404, detail="code_not_found")

    # якщо allow_all=true — зв’язки мають бути порожні
    if getattr(code, "allow_all_events", False):
        return AllowedEventsOut(code_id=code_id, allow_all=True, event_ids=[])

    # інакше — збираємо список з таблиці зв’язків
    rows = db.execute(
        select(models.CodeAllowedEvent.event_id).where(models.CodeAllowedEvent.code_id == code_id)
    ).all()
    ids = [eid for (eid,) in rows]
    return AllowedEventsOut(code_id=code_id, allow_all=False, event_ids=ids)

@router.post("/{code_id}/allow_events", response_model=AllowedEventsOut)
def set_allowed_events(code_id: int, payload: SetAllowedEventsIn, db: DB = Depends(get_db)):
    code = db.get(models.AccessCode, code_id)
    if not code:
        raise HTTPException(status_code=404, detail="code_not_found")

    # 1) allow_all → прапорець + очистити зв’язки
    if payload.allow_all:
        code.allow_all_events = True
        db.query(models.CodeAllowedEvent).filter(
            models.CodeAllowedEvent.code_id == code_id
        ).delete(synchronize_session=False)
        db.commit()
        return AllowedEventsOut(code_id=code_id, allow_all=True, event_ids=[])

    # 2) deny-by-default: allow_all=false
    code.allow_all_events = False

    # 2.1) зібрати повний набір event_ids (з урахуванням event_slugs)
    ids = set(int(eid) for eid in payload.event_ids or [])
    if payload.event_slugs:
        slugs = [s.strip() for s in payload.event_slugs if s and s.strip()]
        if slugs:
            rows = db.execute(
                select(models.Event.id).where(models.Event.slug.in_(slugs))
            ).all()
            ids.update(eid for (eid,) in rows)
            # перевірити, що всі slugs знайдені
            found = {eid for (eid,) in rows}
            # зворотне відображення slug->id для чіткого репорту про помилку
            all_slug_rows = db.execute(
                select(models.Event.slug, models.Event.id).where(models.Event.slug.in_(slugs))
            ).all()
            slug2id = {s: i for (s, i) in all_slug_rows}
            missing_slugs = [s for s in slugs if s not in slug2id]
            if missing_slugs:
                raise HTTPException(status_code=400, detail=f"event_slugs_not_found:{missing_slugs}")

    ids = sorted(ids)

    # 2.2) якщо список порожній — просто очистити зв’язки
    if not ids:
        db.query(models.CodeAllowedEvent).filter(
            models.CodeAllowedEvent.code_id == code_id
        ).delete(synchronize_session=False)
        db.commit()
        return AllowedEventsOut(code_id=code_id, allow_all=False, event_ids=[])

    # 3) валідація: усі event_ids існують?
    exist_ids = {x for (x,) in db.execute(
        select(models.Event.id).where(models.Event.id.in_(ids))
    ).all()}
    missing = [eid for eid in ids if eid not in exist_ids]
    if missing:
        raise HTTPException(status_code=400, detail=f"events_not_found:{missing}")

    # 4) replace semantics — перезапис зв’язків
    db.query(models.CodeAllowedEvent).filter(
        models.CodeAllowedEvent.code_id == code_id
    ).delete(synchronize_session=False)

    db.add_all([models.CodeAllowedEvent(code_id=code_id, event_id=eid) for eid in ids])
    db.commit()

    return AllowedEventsOut(code_id=code_id, allow_all=False, event_ids=ids)
