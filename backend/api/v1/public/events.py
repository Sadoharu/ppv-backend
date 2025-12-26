# backend/api/v1/public/events.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session as DB
from sqlalchemy import select, or_, func

from backend.database import get_db
from backend import models
from backend.services.etag import calc_payload_etag, not_modified, set_etag_header

router = APIRouter(prefix="/events", tags=["public:events"])

# статуси, які показуємо публічно
PUBLIC_STATUSES = {"scheduled", "published", "live", "ended"}

def _base_filter(db: DB, status: str | None, q: str | None):
    stmt = select(models.Event)
    # статус
    if status:
        s = status.strip().lower()
        if s not in PUBLIC_STATUSES:
            raise HTTPException(400, detail="invalid_status")
        stmt = stmt.where(models.Event.status == s)
    else:
        stmt = stmt.where(models.Event.status.in_(PUBLIC_STATUSES))
    # пошук
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(models.Event.title.ilike(like), models.Event.slug.ilike(like)))
    return stmt

def _catalog_item(e: models.Event) -> dict:
    return {
        "id": e.id,
        "slug": e.slug,
        "title": e.title,
        "starts_at": e.starts_at,
        "ends_at": e.ends_at,
        "thumbnail_url": e.thumbnail_url,
        "short_description": e.short_description,
        # зручно одразу віддати URL сторінки
        "page_url": f"/p/{e.slug}",
    }

@router.get("")
def list_events(
    request: Request,
    status: str | None = Query(None, description="one of: scheduled|published|live|ended"),
    q: str | None = Query(None, description="search by title/slug"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: DB = Depends(get_db),
):
    # основний запит
    stmt = _base_filter(db, status, q).order_by(models.Event.starts_at.asc().nulls_last())
    rows = db.execute(stmt.limit(limit).offset(offset)).scalars().all()

    # легкий агрегат для ETag (залежний від фільтрів/вікна)
    count_stmt = _base_filter(db, status, q).with_only_columns(func.count(models.Event.id))
    updated_stmt = _base_filter(db, status, q).with_only_columns(func.max(models.Event.updated_at))
    total = db.execute(count_stmt).scalar_one() or 0
    last_updated = db.execute(updated_stmt).scalar_one()

    etag = calc_payload_etag("catalog", status or "", q or "", limit, offset, total, last_updated or "")
    if not_modified(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=set_etag_header({}, etag))

    data = [_catalog_item(e) for e in rows]
    headers = {"Cache-Control": "public, max-age=30, stale-while-revalidate=60"}
    set_etag_header(headers, etag)
    # варто варіювати кеш по query
    headers["Vary"] = "Accept, Accept-Encoding"
    return JSONResponse(content=jsonable_encoder(data), headers=headers)

@router.get("/{slug}")
def event_public(slug: str, request: Request, db: DB = Depends(get_db)):
    e = db.execute(select(models.Event).where(models.Event.slug == slug)).scalar_one_or_none()
    if not e:
        raise HTTPException(404, "event_not_found")
    if e.status not in PUBLIC_STATUSES:
        # ховаємо draft/archived
        raise HTTPException(404, "event_not_found")

    # ETag на детальну картку
    etag = calc_payload_etag("event_public", e.id, e.updated_at or "", e.status)
    if not_modified(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=set_etag_header({}, etag))

    payload = {
        "id": e.id,
        "slug": e.slug,
        "title": e.title,
        "status": e.status,
        "starts_at": e.starts_at,
        "ends_at": e.ends_at,
        "thumbnail_url": e.thumbnail_url,
        "short_description": e.short_description,
        "player_manifest_url": e.player_manifest_url,  # може бути None — сторінка може бути без плеєра
        "page_url": f"/p/{e.slug}",
        # опціонально: базовий префікс для асетів сторінки
        "assets_base_url": e.assets_base_url,
    }
    headers = {"Cache-Control": "public, max-age=60"}
    set_etag_header(headers, etag)
    return JSONResponse(content=jsonable_encoder(payload), headers=headers)
