# backend/api/v1/delete/admin_events.py
# backend/api/v1/admin_events.py
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session as DB
from sqlalchemy import or_
from backend.api.deps import require_admin_token
from backend.database import get_db
from backend import models
from backend.core.redis import get_redis

router = APIRouter(prefix="/api/admin/events", tags=["admin:events"])


@router.post("")
def create_event(
    body: dict = Body(...),
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),
):
    title = (body.get("title") or "").strip()
    slug = (body.get("slug") or "").strip()
    if not title or not slug:
        raise HTTPException(400, "title_and_slug_required")

    if db.query(models.Event).filter_by(slug=slug).first():
        raise HTTPException(409, "slug_exists")

    # підтримка старого імені поля
    player_manifest_url = body.get("player_manifest_url") or body.get("hls_url")

    e = models.Event(
        title=title,
        slug=slug,
        status=(body.get("status") or "draft"),
        starts_at=body.get("starts_at"),
        ends_at=body.get("ends_at"),
        thumbnail_url=body.get("thumbnail_url"),
        short_description=body.get("short_description"),
        player_manifest_url=player_manifest_url,
        custom_mode=(body.get("custom_mode") or "none"),
        custom_html=body.get("custom_html"),
        custom_css=body.get("custom_css"),
        custom_js=body.get("custom_js"),
        theme=body.get("theme"),
    )
    db.add(e)
    db.flush()      # отримати e.id
    db.commit()     # зберегти
    db.refresh(e)

    return {
        "id": e.id,
        "title": e.title,
        "slug": e.slug,
        "status": e.status,
        "starts_at": e.starts_at,
        "ends_at": e.ends_at,
        "thumbnail_url": e.thumbnail_url,
        "short_description": e.short_description,
        "player_manifest_url": e.player_manifest_url,
        "custom_mode": e.custom_mode,
    }


@router.get("")
def list_events(
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),
):
    query = db.query(models.Event)

    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(models.Event.title.ilike(like),
                                 models.Event.slug.ilike(like)))

    total = query.count()
    rows = (
        query.order_by(models.Event.starts_at.asc().nulls_last(), models.Event.id.desc())
             .offset((page - 1) * page_size)
             .limit(page_size)
             .all()
    )

    items = [{
        "id": e.id,
        "title": e.title,
        "slug": e.slug,
        "status": e.status,
        "starts_at": e.starts_at,
        "ends_at": e.ends_at,
        "thumbnail_url": e.thumbnail_url,
        "short_description": e.short_description,
        "player_manifest_url": e.player_manifest_url,  # ← правильно
        "custom_mode": e.custom_mode,
    } for e in rows]

    return {"total": total, "items": items}


@router.patch("/{event_id}")
def patch_event(
    event_id: int,
    body: dict = Body(...),
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),
):
    e = db.get(models.Event, event_id)
    if not e:
        raise HTTPException(404, "event_not_found")

    if "title" in body:
        e.title = (body.get("title") or "").strip()

    if "slug" in body:
        new_slug = (body.get("slug") or "").strip()
        if new_slug and new_slug != e.slug:
            if db.query(models.Event).filter(models.Event.slug == new_slug, models.Event.id != e.id).first():
                raise HTTPException(409, "slug_exists")
            e.slug = new_slug

    if "status" in body:
        e.status = body.get("status") or e.status
    if "starts_at" in body:
        e.starts_at = body.get("starts_at")
    if "ends_at" in body:
        e.ends_at = body.get("ends_at")
    if "thumbnail_url" in body:
        e.thumbnail_url = body.get("thumbnail_url")
    if "short_description" in body:
        e.short_description = body.get("short_description")

    # підтримка старого поля hls_url
    if "player_manifest_url" in body or "hls_url" in body:
        e.player_manifest_url = body.get("player_manifest_url") or body.get("hls_url")

    if "custom_mode" in body:
        e.custom_mode = body.get("custom_mode") or e.custom_mode
    if "custom_html" in body:
        e.custom_html = body.get("custom_html")
    if "custom_css" in body:
        e.custom_css = body.get("custom_css")
    if "custom_js" in body:
        e.custom_js = body.get("custom_js")
    if "theme" in body:
        e.theme = body.get("theme")

    db.commit()
    db.refresh(e)
    return {
        "id": e.id,
        "title": e.title,
        "slug": e.slug,
        "status": e.status,
        "starts_at": e.starts_at,
        "ends_at": e.ends_at,
        "thumbnail_url": e.thumbnail_url,
        "short_description": e.short_description,
        "player_manifest_url": e.player_manifest_url,
        "custom_mode": e.custom_mode,
    }


@router.delete("/{event_id}")
def delete_event(event_id: int, db: DB = Depends(get_db), current=Depends(require_admin_token)):
    e = db.get(models.Event, event_id)
    if not e:
        raise HTTPException(404, "not_found")
    db.delete(e)
    db.commit()
    return {"ok": True}


@router.get("/{event_id}/stats")
def event_stats(event_id: int, db: DB = Depends(get_db), current=Depends(require_admin_token)):
    from time import time
    from backend.services.session_manager import _event_zset
    r = get_redis()
    key = _event_zset(event_id)
    now = int(time())
    p = r.pipeline()
    p.zremrangebyscore(key, "-inf", now)
    p.zcount(key, now, "+inf")
    _, ccu = p.execute()
    total_active = db.query(models.Session).filter_by(event_id=event_id, active=True).count()
    return {"event_id": event_id, "ccu": int(ccu or 0), "active_sessions": total_active}


@router.get("/{event_id}")
def get_event(
    event_id: int,
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),
):
    e = db.get(models.Event, event_id)
    if not e:
        raise HTTPException(404, "event_not_found")
    return {
        "id": e.id,
        "title": e.title,
        "slug": e.slug,
        "status": e.status,
        "starts_at": e.starts_at,
        "ends_at": e.ends_at,
        "thumbnail_url": e.thumbnail_url,
        "short_description": e.short_description,
        "player_manifest_url": e.player_manifest_url,
        "custom_mode": e.custom_mode,
        "custom_html": e.custom_html,
        "custom_css": e.custom_css,
        "custom_js": e.custom_js,
        "theme": e.theme,
    }
