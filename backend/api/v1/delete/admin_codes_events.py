# backend/api/v1/admin_codes_events.py
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session as DB
from typing import List

from backend.api.deps import require_admin_token
from backend.database import get_db
from backend import models

router = APIRouter(prefix="/api/admin/codes", tags=["admin:codes-events"])

@router.post("/{code_id}/allow_events")
def set_allowed_events(
    code_id: int,
    payload: dict = Body(...),
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),
):
    allow_all = bool(payload.get("allow_all", False))
    event_ids: List[int] = payload.get("event_ids") or []

    code = db.get(models.AccessCode, code_id)
    if not code:
        raise HTTPException(404, "code_not_found")

    # оновлюємо прапорець
    code.allow_all_events = allow_all

    # чистимо існуючі прив'язки
    db.query(models.CodeAllowedEvent).filter(
        models.CodeAllowedEvent.code_id == code_id
    ).delete(synchronize_session=False)

    # якщо не безліміт — валідуємо і додаємо нові прив'язки
    if not allow_all:
        if not event_ids:
            # безліміт вимкнено, але список порожній — тоді доступ ні до чого
            # це допустимо; якщо хочеш — зроби 400
            pass
        else:
            # перевіримо, що всі події існують
            exist_ids = {
                r.id for r in db.query(models.Event.id).filter(
                    models.Event.id.in_(event_ids)
                )
            }
            missing = set(event_ids) - exist_ids
            if missing:
                raise HTTPException(400, f"events_not_found:{sorted(missing)}")

            # створюємо зв'язки
            db.add_all([
                models.CodeAllowedEvent(code_id=code_id, event_id=eid)
                for eid in sorted(exist_ids)
            ])

    db.commit()
    return {"ok": True, "allow_all": code.allow_all_events, "event_ids": event_ids}
