# backend/api/v1/admin/events.py
from fastapi import APIRouter, Depends, HTTPException, Body, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DB

# Використовуємо нову фабрику require_admin замість require_admin_token
from backend.api.deps import require_admin
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

router = APIRouter(tags=["admin:events"])

def _event_to_out(e: models.Event) -> EventOut:
    return EventOut.model_validate(e)

def _event_to_short(e: models.Event) -> EventOutShort:
    return EventOutShort.model_validate(e)

# --- CREATE: Super, Admin, Manager ---
@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    body: EventCreate = Body(...),
    db: DB = Depends(get_db),
    # Менеджери можуть створювати події
    current_admin: models.AdminUser = Depends(require_admin("super", "admin", "manager")),
):
    # підтримка старого імені поля: hls_url -> player_manifest_url
    payload = body.model_dump()
    if not payload.get("player_manifest_url"):
        pass

    if is_slug_taken(db, payload["slug"]):
        raise HTTPException(status_code=409, detail="slug_exists")

    try:
        e = repo_create(db, **payload)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="slug_exists")
    return _event_to_out(e)

# --- LIST: Всі ролі (Support і Analyst теж мають бачити події) ---
@router.get("", response_model=dict)
def list_events(
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: DB = Depends(get_db),
    # Пустий require_admin() = будь-який авторизований адмін
    current_admin: models.AdminUser = Depends(require_admin()),
):
    total, rows = repo_list(db, q, page, page_size)
    return {"total": total, "items": [_event_to_short(e) for e in rows]}

# --- UPDATE: Super, Admin, Manager ---
@router.patch("/{event_id}", response_model=EventOut)
def patch_event(
    event_id: int,
    body: EventUpdate = Body(...),
    db: DB = Depends(get_db),
    current_admin: models.AdminUser = Depends(require_admin("super", "admin", "manager")),
):
    e = repo_get(db, event_id)
    if not e:
        raise HTTPException(status_code=404, detail="event_not_found")

    data = body.model_dump(exclude_unset=True)

    # підтримка старого поля hls_url
    if "player_manifest_url" not in data and "hls_url" in data:
        data["player_manifest_url"] = data.pop("hls_url")

    new_slug = data.get("slug")
    if new_slug and is_slug_taken(db, new_slug, exclude_id=e.id):
        raise HTTPException(status_code=409, detail="slug_exists")

    try:
        e = repo_update(db, e, **data)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="slug_exists")

    return _event_to_out(e)

# --- DELETE: Тільки Super та Admin (Manager не може видаляти) ---
@router.delete("/{event_id}", response_model=dict)
def delete_event(
    event_id: int,
    db: DB = Depends(get_db),
    current_admin: models.AdminUser = Depends(require_admin("super", "admin")),
):
    ok = repo_delete(db, event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True}

# --- STATS: Всі (або можна обмежити без support) ---
@router.get("/{event_id}/stats", response_model=dict)
def event_stats(
    event_id: int,
    db: DB = Depends(get_db),
    current_admin: models.AdminUser = Depends(require_admin()),
):
    from time import time
    from backend.services.session_manager import _event_zset

    r = get_redis()
    key = _event_zset(event_id)
    now = int(time())

    p = r.pipeline()
    p.zremrangebyscore(key, "-inf", now - 1)
    p.zcount(key, now, "+inf")
    _, ccu = p.execute()

    total_active = db.query(models.Session).filter_by(event_id=event_id, active=True).count()
    return {"event_id": event_id, "ccu": int(ccu or 0), "active_sessions": total_active}

# --- GET ONE: Всі ролі ---
@router.get("/{event_id}", response_model=EventOut)
def get_event(
    event_id: int,
    db: DB = Depends(get_db),
    current_admin: models.AdminUser = Depends(require_admin()),
):
    e = repo_get(db, event_id)
    if not e:
        raise HTTPException(status_code=404, detail="event_not_found")
    return _event_to_out(e)