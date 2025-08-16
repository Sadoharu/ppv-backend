# backend/api/v1/client/auth.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Body, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DB
from sqlalchemy import select

from backend.database import get_db
from backend.api.deps import require_auth
from backend.core.config import settings
from backend.services.session_manager import login_with_code, rotate_refresh, logout as do_logout
from backend.services.authz.policy import code_allows_event
from backend import models

router = APIRouter(tags=["client:auth"])

# ───────────────────────── helpers ─────────────────────────
def _cookie_flags():
    secure   = False if getattr(settings, "debug", False) else True
    samesite = "Lax"  if getattr(settings, "debug", False) else "None"
    path     = "/"
    domain   = getattr(settings, "cookie_domain", None) or None
    return secure, samesite, path, domain

def _set_session_cookies(response: Response, access: str, refresh: str, sid: str):
    secure, samesite, path, domain = _cookie_flags()
    response.set_cookie(
        key="viewer_token", value=access,
        httponly=True, samesite=samesite, secure=secure, path=path,
        max_age=int(settings.access_ttl_minutes) * 60,
        domain=domain,
    )
    response.set_cookie(
        key="viewer_refresh", value=refresh,
        httponly=True, samesite=samesite, secure=secure, path=path,
        domain=domain,
    )
    # sid не секрет — може бути доступним з JS
    response.set_cookie(
        key="sid", value=sid,
        httponly=False, samesite="Lax", secure=(False if settings.debug else True),
        path=path, domain=domain,
    )

def _clear_session_cookies(response: Response):
    secure, samesite, path, domain = _cookie_flags()
    for k in ("viewer_token", "viewer_refresh", "sid"):
        response.delete_cookie(key=k, path=path, samesite=samesite, secure=secure, domain=domain)

# ───────────────────────── schemas ────────────────────────
class LoginByCodeIn(BaseModel):
    code: str
    event_id: int | None = None

class RefreshIn(BaseModel):
    session_id: str | None = None
    refresh: str | None = None

# ───────────────────────── endpoints ──────────────────────
@router.get("/verify", status_code=204)
def auth_verify(_: models.Session = Depends(require_auth)):
    # 204, якщо viewer-token валідний
    return Response(status_code=204)

@router.post("/login_by_code")
def login_by_code_endpoint(
    payload: LoginByCodeIn,
    request: Request,
    response: Response,
    db: DB = Depends(get_db),
):
    code = (payload.code or "").strip()
    if not code:
        raise HTTPException(400, "code_required")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    data = login_with_code(db, code_plain=code, ip=ip, ua=ua)
    access, refresh, sid = data["access"], data["refresh"], data["session_id"]

    # Опційна прив'язка до події з перевіркою прав
    if payload.event_id is not None:
        code_obj = db.execute(
            select(models.AccessCode).where(models.AccessCode.code_plain == code)
        ).scalar_one_or_none()
        if not code_obj or not code_allows_event(db, code_obj, int(payload.event_id)):
            raise HTTPException(403, "event_not_allowed")

        sess = db.get(models.Session, sid)
        if sess and sess.event_id is None:
            sess.event_id = int(payload.event_id)
            db.commit()

    _set_session_cookies(response, access, refresh, sid)
    return {"ok": True, "session_id": sid}

@router.post("/refresh")
def refresh(
    request: Request,
    response: Response,
    data: RefreshIn | None = Body(default=None),
    db: DB = Depends(get_db),
):
    # беремо з body або з cookie (fallback)
    sid  = (data.session_id if data else None) or request.cookies.get("sid")
    rjti = (data.refresh if data else None) or (
        request.cookies.get("viewer_refresh")
        or request.cookies.get("rjti")
        or request.cookies.get("refresh_jti")
    )
    if not sid or not rjti:
        raise HTTPException(400, "missing_refresh")

    out = rotate_refresh(db, session_id=str(sid), refresh_jti=str(rjti))
    _set_session_cookies(response, out["access"], out["refresh"], str(sid))
    return out

@router.post("/logout", status_code=204)
def logout(
    response: Response,
    sess: models.Session = Depends(require_auth),
    db: DB = Depends(get_db),
):
    do_logout(db, session_id=sess.id)
    _clear_session_cookies(response)
    # дублюємо явний 204
    return Response(status_code=204)
