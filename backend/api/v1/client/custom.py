# backend/api/v1/client/custom.py
#backend\api\v1\client\custom.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Response, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session as DB
from urllib.parse import urlencode

from backend.database import get_db
from backend.api.deps import require_auth
from backend.core.config import settings
from backend import models
from backend.services.authz.policy import code_allows_event
import secrets

router = APIRouter(prefix="/events", tags=["client:custom"])

PUBLIC_STATUSES = {"scheduled", "published", "live", "ended", "archived"}

def _frame_ancestors_sources() -> list[str]:
    ca = getattr(settings, "custom_frame_ancestors", "") or ""
    srcs = [s.strip() for s in ca.split(",") if s.strip()]
    if not srcs:
        try:
            srcs = list(getattr(settings, "allowed_origins_list", []))
        except Exception:
            srcs = []
    if getattr(settings, "debug", False) and "http://localhost:5173" not in srcs:
        srcs.append("http://localhost:5173")
    if "'self'" not in srcs:
        srcs.append("'self'")
    seen, uniq = set(), []
    for s in srcs:
        if s and s not in seen:
            uniq.append(s); seen.add(s)
    return uniq

def _headers_sanitize(headers: dict) -> dict[str, str]:
    return {
        k: (v if isinstance(v, str) else "; ".join(v) if isinstance(v, (list, tuple)) else str(v))
        for k, v in headers.items()
    }

def _login_redirect(request: Request) -> RedirectResponse:
    base = (getattr(settings, "viewer_login_url", "") or "").strip()
    if not base:
        # fallback: перший дозволений origin + /login, або dev
        origins = getattr(settings, "allowed_origins_list", []) or []
        base = (origins[0].rstrip("/") + "/login") if origins else "http://localhost:5173/login"
    url = str(request.url)
    return RedirectResponse(f"{base}?{urlencode({'returnTo': url})}", status_code=302)

@router.get("/{event_id}/custom", response_class=Response)
def custom_event(
    event_id: int,
    request: Request,
    db: DB = Depends(get_db),
):
    # --- auth перевірка з редіректом замість 401 ---
    try:
        sess = require_auth(
            request=request,
            viewer_token_cookie=request.cookies.get("viewer_token"),
            authorization=request.headers.get("Authorization"),
            db=db,
        )
    except HTTPException as e:
        if e.status_code == 401:
            return _login_redirect(request)
        raise

    e = db.get(models.Event, event_id)
    if not e:
        raise HTTPException(404, "not_found")

    if e.status not in PUBLIC_STATUSES:
        raise HTTPException(404, "not_found")

    code = db.get(models.AccessCode, getattr(sess, "code_id", None)) if getattr(sess, "code_id", None) else None
    if not code or not code_allows_event(db, code, event_id):
        # це вже не про логін → залишимо 403
        raise HTTPException(403, "not_allowed")

    mode = (e.custom_mode or "none").lower()
    if mode not in {"html", "sandbox"}:
        raise HTTPException(404, "not_found")

    nonce = secrets.token_urlsafe(16)
    fa = _frame_ancestors_sources()

    if mode == "sandbox":
        csp = (
            "default-src 'none'; "
            "base-uri 'none'; "
            "form-action 'none'; "
            f"style-src 'nonce-{nonce}'; "
            f"script-src 'nonce-{nonce}'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "media-src 'self'; "
            "connect-src 'self'; "
            "worker-src 'none'; "
            f"frame-ancestors {' '.join(fa)}; "
            "upgrade-insecure-requests"
        )
    else:
        csp = (
            "default-src * blob:; "
            "base-uri 'none'; "
            "form-action 'none'; "
            "style-src * 'unsafe-inline'; "
            "script-src * 'unsafe-inline' 'unsafe-eval' blob:; "
            "img-src * data: blob:; "
            "font-src * data:; "
            "media-src * blob:; "
            "connect-src *; "
            "worker-src 'self' blob:; "
            "frame-src *; "
            f"frame-ancestors {' '.join(fa)}; "
            "upgrade-insecure-requests"
        )

    headers = _headers_sanitize({
        "Content-Security-Policy": csp,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    })

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {"<style nonce='%s'>%s</style>" % (nonce, e.custom_css or "") if (e.custom_css or "").strip() else ""}
</head>
<body>
{e.custom_html or ""}
{"<script nonce='%s'>%s</script>" % (nonce, e.custom_js or "") if (e.custom_js or "").strip() else ""}
</body>
</html>"""

    return Response(content=html, media_type="text/html; charset=utf-8", headers=headers)
