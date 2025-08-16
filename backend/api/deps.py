#v0.5
from __future__ import annotations
from typing import Iterable, Optional

from fastapi import Depends, Cookie, Header, HTTPException, Request
from sqlalchemy.orm import Session

from backend.database import get_db as _get_db
from backend import models
from backend.core.config import settings

# Єдині утиліти
from backend.services.authn.admin_jwt import verify_admin_token as _verify_admin_jwt
from backend.services.authn.jwt import decode_token as _decode_viewer_jwt
from backend.utils.dt import now_utc


# ───────────────────────── DB session ───────────────────────────────
def get_db() -> Session:
    yield from _get_db()


# ─────────────────────── helpers ────────────────────────────────────
def _pick_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None

def _pick_token(cookie_val: str | None, authorization: str | None, request: Request, query_key: str | None = None) -> str | None:
    # Пріоритет: Cookie → Bearer → ?token=...
    if cookie_val:
        return cookie_val
    bearer = _pick_bearer(authorization)
    if bearer:
        return bearer
    if query_key:
        q = request.query_params.get(query_key)
        if q:
            return q
    return None


# ────────── ADMIN: залежність (зворотна сумісність) ──────────────────
def require_admin_token(
    request: Request,
    admin_token_cookie: str | None = Cookie(None, alias="admin_token"),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
    role_required: str | None = None,  # історично; краще користуватися фабрикою require_admin(...)
) -> models.AdminUser:
    """
    Перевіряє admin access token і повертає AdminUser.
    Приймає токен з cookie 'admin_token', або з Authorization: Bearer, або ?token=...
    Якщо передано role_required="admin|super" — звузить допустимі ролі.
    """
    token = _pick_token(admin_token_cookie, authorization, request, query_key="token")
    if not token:
        raise HTTPException(401, "missing_token")

    # Парсимо ролі (якщо параметр використовують)
    allowed_roles = None
    if role_required:
        allowed_roles = {r.strip() for r in role_required.split("|") if r.strip()}

    # Використовуємо єдиний валідаційний шлях (python-jose)
    try:
        payload = _verify_admin_jwt(token, allowed_roles=allowed_roles)
    except HTTPException as e:
        # зберігаємо текст detail, бо на фронті можуть чекати конкретні коди
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    user = db.get(models.AdminUser, payload.get("adm_id"))
    if not user:
        raise HTTPException(401, "unauthorized")

    # опційно: переконайся, що роль у БД не «перевищує» payload
    if allowed_roles and user.role not in allowed_roles:
        # захист від ситуації, коли роль у БД зменшили, а токен ще старий
        raise HTTPException(403, "forbidden")

    return user


# ────────── ADMIN: рекомендована фабрика залежності ──────────────────
def require_admin(*roles: str):
    """
    Використання:
        @router.get(..., dependencies=[Depends(require_admin("admin", "super"))])
    """
    allowed = set(roles) if roles else None

    def _dep(
        request: Request,
        admin_token_cookie: str | None = Cookie(None, alias="admin_token"),
        authorization: str | None = Header(None),
        db: Session = Depends(get_db),
    ) -> models.AdminUser:
        token = _pick_token(admin_token_cookie, authorization, request, query_key="token")
        if not token:
            raise HTTPException(401, "missing_token")
        try:
            payload = _verify_admin_jwt(token, allowed_roles=allowed)
        except HTTPException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)

        user = db.get(models.AdminUser, payload.get("adm_id"))
        if not user:
            raise HTTPException(401, "unauthorized")
        if allowed and user.role not in allowed:
            raise HTTPException(403, "forbidden")
        return user

    return _dep


# ────────── VIEWER: залежність (користувацький доступ) ───────────────
def require_auth(
    request: Request,
    viewer_token_cookie: str | None = Cookie(None, alias="viewer_token"),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
    strict_jti: bool = True,  # ✳️ перевіряти, що jti збігається з Session.token_jti
) -> models.Session:
    """
    Перевіряє access JWT глядача, повертає активну Session.
    - бере токен з cookie 'viewer_token' або Authorization: Bearer
    - валідний підпис і exp
    - Session існує й active=True
    - (опційно) jti збігається з Session.token_jti (захист від застарілих токенів)
    - код не відкликаний і не прострочений
    """
    access_token = _pick_token(viewer_token_cookie, authorization, request)
    if not access_token:
        raise HTTPException(401, "Unauthorized")

    data = _decode_viewer_jwt(access_token)
    if not data:
        raise HTTPException(401, "Invalid or expired token")

    sid = data.get("sid")
    if not sid:
        raise HTTPException(401, "Unauthorized")

    sess = db.get(models.Session, sid)
    if not sess or not getattr(sess, "active", False):
        raise HTTPException(401, "Unauthorized")

    # ✳️ сувора перевірка jti (корисно при rotate_refresh та для вигону «старих» токенів)
    if strict_jti:
        tok_jti = data.get("jti")
        if not tok_jti or tok_jti != getattr(sess, "token_jti", None):
            raise HTTPException(401, "Unauthorized")

    # Перевірка коду доступу
    code = db.get(models.AccessCode, getattr(sess, "code_id", None))
    if not code:
        raise HTTPException(401, "Unauthorized")

    now = now_utc()
    exp = getattr(code, "expires_at", None)
    if exp is not None:
        # нормалізуємо до aware UTC
        exp = exp if getattr(exp, "tzinfo", None) else exp.replace(tzinfo=now.tzinfo)

    if getattr(code, "revoked", False) or (exp is not None and exp <= now):
        raise HTTPException(403, "Code disabled or expired")

    return sess
