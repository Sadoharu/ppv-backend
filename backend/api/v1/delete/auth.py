# backend/api/v1/delete/auth.py
# backend/api/v1/auth.py
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request, Response
from sqlalchemy.orm import Session as DB
from sqlalchemy import select

from backend.database import get_db
from backend.api.deps import require_admin_token, require_auth
from backend.core.config import settings
from backend.services.session_manager import login_with_code, rotate_refresh, logout as do_logout
from backend.services.authz.policy import code_allows_event 
from backend import models

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.get("/verify", status_code=204)
def auth_verify(current_session=Depends(require_admin_token)):
    # просто 204, якщо адмінський токен валідний
    return Response(status_code=204)

@router.post("/login_by_code")
def login_by_code_endpoint(payload: dict, request: Request, response: Response, db: DB = Depends(get_db)):
    code = (payload.get("code") or "").strip()
    event_id = payload.get("event_id")
    if not code:
        raise HTTPException(400, "code_required")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    data = login_with_code(db, code_plain=code, ip=ip, ua=ua)
    access = data["access"]
    refresh = data["refresh"]
    sid = data["session_id"]

    # опційна прив'язка до події (перевіряємо право коду на event_id)
    if event_id is not None:
        code_obj = db.execute(
            select(models.AccessCode).where(models.AccessCode.code_plain == code)
        ).scalar_one_or_none()
        if not code_obj or not code_allows_event(db, code_obj, int(event_id)):
            raise HTTPException(403, "event_not_allowed")

        sess = db.get(models.Session, sid)
        if sess and sess.event_id is None:
            sess.event_id = int(event_id)
            db.commit()

    # Заувага: у проді -> secure=True та samesite="None"
    secure_flag = False if settings.debug else True
    same_site = "Lax" if settings.debug else "None"

    # куки з токенами
    response.set_cookie(
        key="viewer_token",
        value=access,
        httponly=True,
        samesite=same_site,
        secure=secure_flag,
        max_age=settings.access_ttl_minutes * 60,
        path="/",
    )
    response.set_cookie(
        key="viewer_refresh",
        value=refresh,
        httponly=True,
        samesite=same_site,
        secure=secure_flag,
        path="/",
    )
    # sid для WS/heartbeat
    response.set_cookie(
        key="sid",
        value=sid,
        httponly=False,   # не секрет; використовуєш у фронті
        samesite="Lax",
        secure=False if settings.debug else True,
        path="/",
    )

    return {"ok": True, "session_id": sid}

@router.post("/refresh")
def refresh(
    session_id: str = Body(...),
    refresh: str = Body(...),
    response: Response = None,
    db: DB = Depends(get_db)
):
    data = rotate_refresh(db, session_id=session_id, refresh_jti=refresh)

    # опційно оновлюємо куки з бекенду
    if response is not None:
        secure_flag = False if settings.debug else True
        same_site = "Lax" if settings.debug else "None"
        response.set_cookie(
            key="viewer_token",
            value=data["access"],
            httponly=True,
            samesite=same_site,
            secure=secure_flag,
            max_age=settings.access_ttl_minutes * 60,
            path="/",
        )
        response.set_cookie(
            key="viewer_refresh",
            value=data["refresh"],
            httponly=True,
            samesite=same_site,
            secure=secure_flag,
            path="/",
        )

    return data

@router.post("/logout", status_code=204)
def logout(
    response: Response,
    sess = Depends(require_auth),   # беремо поточну сесію з guard
    db: DB = Depends(get_db)
):
    do_logout(db, session_id=sess.id)

    # чистимо куки
    secure_flag = False if settings.debug else True
    same_site = "Lax" if settings.debug else "None"
    for k in ("viewer_token", "viewer_refresh", "sid"):
        response.delete_cookie(key=k, path="/", samesite=same_site, secure=secure_flag)

    return Response(status_code=204)
