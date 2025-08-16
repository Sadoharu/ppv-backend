# backend\api\v1\client\public_events.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DB
from sqlalchemy import select, or_
from backend.database import get_db
from backend import models

router = APIRouter(prefix="/events", tags=["public:events"])  # фінально стане /api/events

# які статуси вважаємо «публічними»
PUBLIC_STATUSES = {"scheduled", "published", "live", "ended"}

@router.get("")
def list_events(
    status: str | None = Query(None, description="one of: scheduled|published|live|ended"),
    q: str | None = Query(None, description="search by title/slug"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: DB = Depends(get_db),
):
    qry = db.query(models.Event)

    # фільтр статусів: за замовчуванням тільки публічні
    if status:
        s = status.strip().lower()
        if s not in PUBLIC_STATUSES:
            raise HTTPException(400, detail="invalid_status")
        qry = qry.filter(models.Event.status == s)
    else:
        qry = qry.filter(models.Event.status.in_(PUBLIC_STATUSES))

    # простий пошук
    if q:
        like = f"%{q}%"
        qry = qry.filter(or_(models.Event.title.ilike(like), models.Event.slug.ilike(like)))

    qry = qry.order_by(models.Event.starts_at.asc().nulls_last())

    rows = qry.limit(limit).offset(offset).all()
    return [
        {
            "id": e.id,
            "slug": e.slug,
            "title": e.title,
            "starts_at": e.starts_at,
            "ends_at": e.ends_at,
            "thumbnail_url": e.thumbnail_url,
            "short_description": e.short_description,
        }
        for e in rows
    ]


@router.get("/{slug}/public")
def event_public(slug: str, db: DB = Depends(get_db)):
    e = db.execute(select(models.Event).where(models.Event.slug == slug)).scalar_one_or_none()
    if not e:
        raise HTTPException(404, "event_not_found")

    # ховаємо чорнові/архівні
    if e.status not in PUBLIC_STATUSES:
        raise HTTPException(404, "event_not_found")

    return {
        "id": e.id,
        "slug": e.slug,
        "title": e.title,
        "player_manifest_url": e.player_manifest_url,
        "custom_mode": e.custom_mode,
        "theme": e.theme or {},
        "status": e.status,
        "starts_at": e.starts_at,
        "ends_at": e.ends_at,
        "thumbnail_url": e.thumbnail_url,
        "short_description": e.short_description,
    }
