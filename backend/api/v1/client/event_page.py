# backend/api/v1/client/event_page.py
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from backend.database import get_db
from backend import models
from backend.services.csp import gen_nonce, build_csp_headers
from backend.services.sanitizer import strip_scripts_and_inline_handlers
from backend.services.etag import calc_event_etag, not_modified, set_etag_header
from backend.services.media_security import BunnySecurityService

router = APIRouter(prefix="/events", tags=["public:pages"])
pretty_router = APIRouter(prefix="/p", tags=["public:pages"])

def _runtime_url(version: str | None) -> str:
    return f"/runtime/ppv-runtime.{(version or 'latest')}.js"

def _user_js_url(event_id: int, etag: Optional[str]) -> str:
    q = f"?v={etag}" if etag else ""
    return f"/event-assets/{event_id}/user.js{q}"

def _json_for_script(obj: dict) -> str:
    # безпечно для інлайнового <script>
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

def _build_html_doc(
    *,
    html: str,
    css: str,
    runtime_url: str,
    user_js_url: str,
    nonce: str,
    assets_base_url: Optional[str],
    boot: dict,
    gated: bool,
) -> str:
    """
    Порядок:
      1) __PPV_BOOT__ (inline, nonce)
      2) runtime (nonce)
      3) <style> з правилом gated + page_css (nonce)
      4) sanitized body
      5) user.js (nonce)
    """
    safe_html = strip_scripts_and_inline_handlers(html or "")

    preconnect = f'<link rel="preconnect" href="{assets_base_url}">' if assets_base_url else ""

    gating_rule = "html.gated, body.gated { visibility: hidden; }" if gated else ""
    css_payload = (gating_rule + ("\n" if gating_rule and (css or "").strip() else "") + (css or "")).strip()
    style_tag = f'<style nonce="{nonce}">{css_payload}</style>' if css_payload else ""

    boot_json = _json_for_script(boot)
    boot_tag = (
        f'<script nonce="{nonce}">'
        f'window.__PPV_BOOT__={boot_json};'
        f'if(Object.freeze){{try{{Object.freeze(window.__PPV_BOOT__);}}catch(_ ){{}}}}'
        f'</script>'
    )

    html_cls = ' class="gated"' if gated else ""
    body_cls = ' class="gated"' if gated else ""

    return (
        "<!doctype html>"
        f"<html lang=\"uk\"{html_cls}>"
        "<head>"
        "<meta charset=\"utf-8\"/>"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"/>"
        f"{preconnect}"
        "<title>Подія</title>"
        f"{boot_tag}"
        f'<script nonce="{nonce}" src="{runtime_url}"></script>'
        f"{style_tag}"
        "</head>"
        f"<body{body_cls}>"
        f"{safe_html}"
        f'<script nonce="{nonce}" src="{user_js_url}"></script>'
        "</body>"
        "</html>"
    )

def _render_event(ev: models.Event, request: Request, *, is_preview: bool) -> Response:
    etag = getattr(ev, "etag", None) or calc_event_etag(
        ev.id,
        getattr(ev, "updated_at", None),
        getattr(ev, "status", "") or "",
        getattr(ev, "page_html", "") or "",
        getattr(ev, "page_css", "") or "",
        getattr(ev, "page_js", "") or "",
    )
    if not is_preview and not_modified(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=set_etag_header({}, etag))

    nonce = gen_nonce()
    csp_headers = build_csp_headers(mode="sandbox", nonce=nonce)

    # --- BUNNY & MUX LOGIC START ---
    # Отримуємо шлях до відео. Пріоритет: bunny_video_path (signed), fallback: player_manifest_url (public)
    bunny_path = getattr(ev, "bunny_video_path", None)
    public_url = getattr(ev, "player_manifest_url", None)
    
    playback_url = public_url
    mux_data = None

    # Якщо є шлях для Bunny, генеруємо підписане посилання
    if bunny_path:
        playback_url = BunnySecurityService.generate_signed_url(
            video_path=bunny_path, 
            expire_seconds=10800 # 3 години
        )
        
        # Визначаємо ключ Mux (спочатку з івенту, потім глобальний)
        event_mux_key = getattr(ev, "mux_env_key", None)
        
        mux_data = BunnySecurityService.get_mux_metadata(
            event_title=ev.title,
            video_id=str(ev.id),
            env_key=event_mux_key, # Передаємо конкретний ключ
            user_id=None 
        )
    # --- BUNNY & MUX LOGIC END ---

    boot = {
        "eventId": ev.id,
        "slug": ev.slug,
        "loginPath": "/login",
        "autoGate": (not is_preview),  # прев'ю без авто-редіректів
        "env": {
            "title": ev.title,
            "description": getattr(ev, "short_description", None),
            # Передаємо фінальний URL (підписаний або публічний)
            "hls": playback_url, 
            # Передаємо конфігурацію Mux (з правильним env_key)
            "mux": mux_data,
            "cdn": getattr(ev, "assets_base_url", None),
            "preview": bool(is_preview),
        },
    }

    html_doc = _build_html_doc(
        html=getattr(ev, "page_html", "") or "",
        css=getattr(ev, "page_css", "") or "",
        runtime_url=_runtime_url(getattr(ev, "runtime_js_version", None)),
        user_js_url=_user_js_url(ev.id, etag),
        nonce=nonce,
        assets_base_url=getattr(ev, "assets_base_url", None),
        boot=boot,
        gated=(not is_preview),
    )

    headers = {**csp_headers}
    set_etag_header(headers, etag)
    headers["Cache-Control"] = "no-store" if is_preview else "public, max-age=60"
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

    return Response(content=html_doc, media_type="text/html; charset=utf-8", headers=headers)

@router.get("/{event_id}/page")
def render_event_page(event_id: int, request: Request, db: DB = Depends(get_db)):
    ev = db.execute(select(models.Event).where(models.Event.id == event_id)).scalar_one_or_none()
    if not ev:
        raise HTTPException(404, detail="event_not_found")
    if (getattr(ev, "status", None) or "draft") != "published":
        raise HTTPException(404, detail="event_not_published")
    return _render_event(ev, request, is_preview=False)

@router.get("/{event_id}/preview")
def preview_event_page(event_id: int, token: str, request: Request, db: DB = Depends(get_db)):
    ev = db.execute(select(models.Event).where(models.Event.id == event_id)).scalar_one_or_none()
    if not ev:
        raise HTTPException(404, detail="event_not_found")
    if not getattr(ev, "preview_token", None) or token != ev.preview_token:
        raise HTTPException(403, detail="invalid_preview_token")
    return _render_event(ev, request, is_preview=True)

@router.get("/slug/{slug}/page")
def render_event_page_by_slug(slug: str, request: Request, db: DB = Depends(get_db)):
    ev = db.execute(select(models.Event).where(models.Event.slug == slug)).scalar_one_or_none()
    if not ev:
        raise HTTPException(404, detail="event_not_found")
    if (getattr(ev, "status", None) or "draft") != "published":
        raise HTTPException(404, detail="event_not_published")
    return _render_event(ev, request, is_preview=False)

@router.get("/slug/{slug}/preview")
def preview_event_page_by_slug(slug: str, token: str, request: Request, db: DB = Depends(get_db)):
    ev = db.execute(select(models.Event).where(models.Event.slug == slug)).scalar_one_or_none()
    if not ev:
        raise HTTPException(404, detail="event_not_found")
    if not getattr(ev, "preview_token", None) or token != ev.preview_token:
        raise HTTPException(403, detail="invalid_preview_token")
    return _render_event(ev, request, is_preview=True)

@pretty_router.get("/{slug}")
def pretty_by_slug(slug: str, request: Request, db: DB = Depends(get_db)):
    ev = db.execute(select(models.Event).where(models.Event.slug == slug)).scalar_one_or_none()
    if not ev:
        raise HTTPException(404, detail="event_not_found")
    if (getattr(ev, "status", None) or "draft") != "published":
        raise HTTPException(404, detail="event_not_published")
    return _render_event(ev, request, is_preview=False)