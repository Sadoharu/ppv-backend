# backend/api/v1/public/custom_blocks.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session as DB
from datetime import datetime, timezone
import hashlib

from backend.database import get_db
from backend import models
from backend.core.config import settings

# використовуємо централізовану перевірку EAT
from backend.services.authn.jwt_event import verify_event_token as verify_eat
from jose import jwt, JWTError, ExpiredSignatureError  # для viewer_token/admin_token

router = APIRouter(prefix="/events", tags=["public:custom-blocks"])  # фінально -> /api/events/...

PUBLIC_STATUSES = {"scheduled", "published", "live", "ended"}

def _calc_etag(e: models.Event) -> str:
    base = f"{getattr(e,'updated_at',None) or getattr(e,'created_at',None)}|{e.custom_mode}|{e.custom_html}|{e.custom_css}|{e.custom_js}"
    return 'W/"' + hashlib.sha256(base.encode("utf-8")).hexdigest() + '"'

def _ensure_code_valid(db: DB, sess: models.Session) -> None:
    code = db.get(models.AccessCode, sess.code_id)
    if not code or getattr(code, "revoked", False):
        raise HTTPException(401, "code_invalid")
    exp = getattr(code, "expires_at", None)
    if exp:
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= datetime.now(timezone.utc):
            raise HTTPException(401, "code_invalid")

def _auth_viewer_or_admin(request: Request, db: DB, event_id: int, preview: bool) -> None:
    """
    preview=1  -> дозволяємо тільки за admin_token.
    preview=0  -> спочатку пробуємо EAT (cookie 'eat'), якщо ні — viewer_token.
    Кидає HTTPException 401/403 при невдачі.
    """
    if preview:
        # адмін-токен з cookie або Authorization: Bearer
        token = request.cookies.get("admin_token")
        if not token:
            auth = request.headers.get("authorization")
            if auth and auth.lower().startswith("bearer "):
                token = auth.split()[1]
        if not token:
            raise HTTPException(401, "admin_preview_auth_required")
        try:
            jwt.decode(token, settings.admin_jwt_secret, algorithms=["HS256"], options={"verify_aud": False})
        except (ExpiredSignatureError, JWTError):
            raise HTTPException(401, "admin_preview_auth_required")
        return

    # 1) EAT (cookie 'eat') — пріоритетно
    eat = request.cookies.get("eat")
    if eat:
        try:
            data = verify_eat(eat, event_id=event_id)  # перевіряє підпис, тип/ауд/ліві
            sid = str(data.get("sid") or "")
            if not sid:
                raise HTTPException(401, "session_invalid")
            sess = db.get(models.Session, sid)
            if not sess or not getattr(sess, "active", False):
                raise HTTPException(401, "session_invalid")
            _ensure_code_valid(db, sess)
            return
        except HTTPException:
            raise
        except Exception:
            # впадемо у fallback через viewer_token
            pass

    # 2) Fallback: viewer_token (cookie або Bearer)
    access = request.cookies.get("viewer_token")
    if not access:
        auth = request.headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            access = auth.split()[1]
    if not access:
        raise HTTPException(401, "Unauthorized")

    try:
        payload = jwt.decode(access, settings.jwt_secret, algorithms=["HS256"], options={"verify_aud": False})
    except (ExpiredSignatureError, JWTError):
        raise HTTPException(401, "Unauthorized")

    sid = payload.get("sid")
    if not sid:
        raise HTTPException(401, "Unauthorized")

    sess = db.get(models.Session, sid)
    if not sess or not getattr(sess, "active", False):
        raise HTTPException(401, "Unauthorized")

    _ensure_code_valid(db, sess)
    # (за потреби можна перевірити, що sess.event_id == event_id, якщо хочеш жорсткішу прив’язку)

@router.get("/{event_id}/custom/blocks")
def custom_blocks(
    event_id: int,
    request: Request,
    response: Response,
    preview: int = Query(0, description="1 = admin preview"),
    db: DB = Depends(get_db),
):
    e = db.get(models.Event, event_id)
    if not e:
        raise HTTPException(404, "event_not_found")

    if not preview and e.status not in PUBLIC_STATUSES:
        # непублічні події не віддаємо глядачеві
        raise HTTPException(404, "event_not_public")

    # auth: EAT / viewer_token / admin preview
    _auth_viewer_or_admin(request, db, event_id, bool(preview))

    # ETag/304
    etag = _calc_etag(e)
    inm = request.headers.get("if-none-match")
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=30, must-revalidate",
        "Vary": "Origin",  # для CORS + кешів
    }
    if inm and inm == etag:
        return Response(status_code=304, headers=headers)

    body = {
        "event_id": e.id,
        "mode": (e.custom_mode or "none"),
        "html": e.custom_html or "",
        "css": e.custom_css or "",
        "js": e.custom_js or "",
        "updated_at": (getattr(e, "updated_at", None) or getattr(e, "created_at", None)),
        "status": e.status,
    }
    return JSONResponse(content=jsonable_encoder(body), headers=headers)
