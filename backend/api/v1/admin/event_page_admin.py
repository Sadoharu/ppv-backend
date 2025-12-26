# backend/api/v1/admin/event_page_admin.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DB
from sqlalchemy import select
from datetime import datetime, timezone
import secrets

from backend.database import get_db
from backend import models
from backend.schemas.event_page import EventPageUpdate, EventPageOut
from backend.services.etag import calc_event_etag

router = APIRouter(tags=["admin:pages"])

# Підключаємо реальний guard, якщо є; інакше — no-op (щоб не ламати дев)
try:
    # приклад: з твого проекту може бути інший шлях
    from backend.api.v1.admin.deps import require_admin  # type: ignore
except Exception:  # pragma: no cover
    def require_admin():
        return True

@router.get("/{event_id}/page", response_model=EventPageOut, dependencies=[Depends(require_admin)])
def get_event_page(event_id: int, db: DB = Depends(get_db)):
    ev = db.execute(select(models.Event).where(models.Event.id == event_id)).scalar_one_or_none()
    if not ev:
        raise HTTPException(404, detail="event_not_found")
    return EventPageOut(
        html=ev.page_html or "",
        css=ev.page_css or "",
        js=ev.page_js or "",
        runtime_js_version=ev.runtime_js_version or "latest",
        etag=ev.etag,
        updated_at=(ev.updated_at.isoformat() if getattr(ev, "updated_at", None) else None),
    )

@router.put("/{event_id}/page", dependencies=[Depends(require_admin)])
def update_event_page(event_id: int, payload: EventPageUpdate, db: DB = Depends(get_db)):
    ev = db.execute(select(models.Event).where(models.Event.id == event_id)).scalar_one_or_none()
    if not ev:
        raise HTTPException(404, detail="event_not_found")

    # Оновлюємо лише передані поля
    if payload.page_html is not None: ev.page_html = payload.page_html
    if payload.page_css  is not None: ev.page_css  = payload.page_css
    if payload.page_js   is not None: ev.page_js   = payload.page_js
    if payload.runtime_js_version is not None: ev.runtime_js_version = payload.runtime_js_version
    if payload.assets_base_url is not None: ev.assets_base_url = payload.assets_base_url
    if payload.status is not None: ev.status = payload.status  # дозволяємо, якщо хочеш міняти тут

    db.add(ev); db.commit(); db.refresh(ev)

    # Після коміту перерахуємо etag
    ev.etag = calc_event_etag(
        ev.id, getattr(ev, "updated_at", None), ev.status or "",
        ev.page_html or "", ev.page_css or "", ev.page_js or ""
    )
    db.add(ev); db.commit(); db.refresh(ev)

    return {"ok": True, "etag": ev.etag}

@router.post("/{event_id}/publish", dependencies=[Depends(require_admin)])
def publish_event_page(event_id: int, db: DB = Depends(get_db)):
    ev = db.execute(select(models.Event).where(models.Event.id == event_id)).scalar_one_or_none()
    if not ev:
        raise HTTPException(404, detail="event_not_found")

    ev.status = "published"
    ev.published_at = datetime.now(timezone.utc)
    # оновити ETag
    ev.etag = calc_event_etag(
        ev.id, getattr(ev, "updated_at", None), ev.status or "",
        ev.page_html or "", ev.page_css or "", ev.page_js or ""
    )
    if not ev.preview_token:
        ev.preview_token = secrets.token_urlsafe(16)

    db.add(ev); db.commit(); db.refresh(ev)
    return {"ok": True, "etag": ev.etag, "preview_token": ev.preview_token}

@router.post("/{event_id}/unpublish", dependencies=[Depends(require_admin)])
def unpublish_event_page(event_id: int, db: DB = Depends(get_db)):
    ev = db.execute(select(models.Event).where(models.Event.id == event_id)).scalar_one_or_none()
    if not ev:
        raise HTTPException(404, detail="event_not_found")
    ev.status = "draft"
    db.add(ev); db.commit()
    return {"ok": True}

@router.post("/{event_id}/preview-token", dependencies=[Depends(require_admin)])
def regen_preview_token(event_id: int, db: DB = Depends(get_db)):
    ev = db.execute(select(models.Event).where(models.Event.id == event_id)).scalar_one_or_none()
    if not ev:
        raise HTTPException(404, detail="event_not_found")
    ev.preview_token = secrets.token_urlsafe(16)
    db.add(ev); db.commit(); db.refresh(ev)
    return {"ok": True, "preview_token": ev.preview_token}
