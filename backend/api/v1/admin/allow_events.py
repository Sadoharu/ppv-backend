#v0.5
# backend/api/v1/admin_codes_events.py
from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, conlist
from sqlalchemy.orm import Session as DB

from backend.database import get_db
from backend import models
from backend.api.deps import require_admin  # фабрика: require_admin("admin","super")

router = APIRouter(
    tags=["admin:codes-events"],
    dependencies=[Depends(require_admin("admin", "super"))],
)

class SetAllowedEventsIn(BaseModel):
    allow_all: bool = False
    event_ids: list[int] = Field(default_factory=list) 

@router.post("/{code_id}/allow_events")
def set_allowed_events(
    code_id: int,
    payload: SetAllowedEventsIn,
    db: DB = Depends(get_db),
):
    # 0) Код існує?
    code = db.get(models.AccessCode, code_id)
    if not code:
        raise HTTPException(status_code=404, detail="code_not_found")

    # 1) Якщо allow_all → увімкнути прапорець і знести всі зв’язки
    if payload.allow_all:
        # якщо в моделі немає поля — кине AttributeError. Якщо таке можливо у твоїй схемі,
        # заміни на: if hasattr(code, "allow_all_events"): code.allow_all_events = True
        code.allow_all_events = True
        db.query(models.CodeAllowedEvent).filter(
            models.CodeAllowedEvent.code_id == code_id
        ).delete(synchronize_session=False)
        db.commit()
        return {"ok": True, "allow_all": True, "event_ids": []}

    # 2) deny-by-default: allow_all == False
    #    Може бути порожній список → код не має доступу ні до яких подій.
    #    У цьому випадку просто очистимо всі зв’язки і вимкнемо прапорець.
    ids = sorted(set(int(eid) for eid in payload.event_ids))  # дедуп + стабільний порядок
    code.allow_all_events = False

    # 2.1) якщо список порожній — просто очистити й зберегти
    if not ids:
        db.query(models.CodeAllowedEvent).filter(
            models.CodeAllowedEvent.code_id == code_id
        ).delete(synchronize_session=False)
        db.commit()
        return {"ok": True, "allow_all": False, "event_ids": []}

    # 3) Валідація: усі події існують?
    exist_ids = {
        x for (x,) in db.query(models.Event.id).filter(models.Event.id.in_(ids)).all()
    }
    missing = [eid for eid in ids if eid not in exist_ids]
    if missing:
        raise HTTPException(status_code=400, detail=f"events_not_found:{missing}")

    # 4) Переписуємо зв’язки (replace semantics)
    db.query(models.CodeAllowedEvent).filter(
        models.CodeAllowedEvent.code_id == code_id
    ).delete(synchronize_session=False)

    db.add_all([
        models.CodeAllowedEvent(code_id=code_id, event_id=eid)
        for eid in ids
    ])

    db.commit()
    return {"ok": True, "allow_all": False, "event_ids": ids}
