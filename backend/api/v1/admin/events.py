from fastapi import APIRouter, Depends, HTTPException, Body, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DB

from backend.api.deps import require_admin_token, require_admin
from backend.database import get_db
from backend.core.redis import get_redis
from backend import models

from backend.schemas import (
    EventCreate, EventUpdate, EventOut, EventOutShort
)
from backend.repositories.events_repo import (
    create_event as repo_create,
    update_event as repo_update,
    delete_event as repo_delete,
    list_events as repo_list,
    get_event as repo_get,
    is_slug_taken,
)

router = APIRouter(
    tags=["admin:events"],
    dependencies=[Depends(require_admin("admin", "super"))],
)

def _event_to_out(e: models.Event) -> EventOut:
    # Pydantic з model_config=from_attributes сам зконвертує
    return EventOut.model_validate(e)

def _event_to_short(e: models.Event) -> EventOutShort:
    return EventOutShort.model_validate(e)

@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    body: EventCreate = Body(...),
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),
):
    # підтримка старого імені поля: hls_url -> player_manifest_url
    payload = body.model_dump()
    if not payload.get("player_manifest_url"):
        # якщо старі клієнти шлють hls_url — воно не долетить сюди (бо схеми),
        # тому підтримка вже в EventUpdate. Тут лишаємо як є.
        pass

    # додаткова перевірка наявності slug (case-insensitive)
    if is_slug_taken(db, payload["slug"]):
        raise HTTPException(status_code=409, detail="slug_exists")

    try:
        e = repo_create(db, **payload)
    except IntegrityError:
        # якщо є унікальний індекс у БД — ловимо ще тут
        raise HTTPException(status_code=409, detail="slug_exists")
    return _event_to_out(e)

@router.get("", response_model=dict)
def list_events(
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),
):
    total, rows = repo_list(db, q, page, page_size)
    return {"total": total, "items": [_event_to_short(e) for e in rows]}

@router.patch("/{event_id}", response_model=EventOut)
def patch_event(
    event_id: int,
    body: EventUpdate = Body(...),
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),
):
    e = repo_get(db, event_id)
    if not e:
        raise HTTPException(status_code=404, detail="event_not_found")

    data = body.model_dump(exclude_unset=True)

    # підтримка старого поля hls_url
    if "player_manifest_url" not in data and "hls_url" in data:
        data["player_manifest_url"] = data.pop("hls_url")

    # slug-конфлікт
    new_slug = data.get("slug")
    if new_slug and is_slug_taken(db, new_slug, exclude_id=e.id):
        raise HTTPException(status_code=409, detail="slug_exists")

    try:
        e = repo_update(db, e, **data)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="slug_exists")

    return _event_to_out(e)

@router.delete("/{event_id}", response_model=dict)
def delete_event(
    event_id: int,
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),
):
    ok = repo_delete(db, event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True}

@router.get("/{event_id}/stats", response_model=dict)
def event_stats(
    event_id: int,
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),
):
    # CCU за Redis + кількість активних сесій за БД
    from time import time
    from backend.services.session_manager import _event_zset

    r = get_redis()
    key = _event_zset(event_id)
    now = int(time())

    # чистимо прострочені записи і рахуємо теперішні/майбутні
    p = r.pipeline()
    p.zremrangebyscore(key, "-inf", now - 1)
    p.zcount(key, now, "+inf")
    _, ccu = p.execute()

    total_active = db.query(models.Session).filter_by(event_id=event_id, active=True).count()
    return {"event_id": event_id, "ccu": int(ccu or 0), "active_sessions": total_active}

@router.get("/{event_id}", response_model=EventOut)
def get_event(
    event_id: int,
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),
):
    e = repo_get(db, event_id)
    if not e:
        raise HTTPException(status_code=404, detail="event_not_found")
    return _event_to_out(e)
