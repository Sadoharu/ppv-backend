# backend/api/v1/admin/auth.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Body, Request, Response, Cookie
from sqlalchemy.orm import Session as DB

from backend.database import get_db
from backend.models import AdminUser
from backend.core.config import settings
# Додаємо імпорти для /me
from backend import schemas
from backend.api.deps import require_admin

from backend.services.authn.passwords import verify_password
from backend.services.authn.admin_jwt import (
    create_admin_access,
    create_admin_refresh,
)
from backend.services.security.bruteforce import (
    check_bruteforce,
    register_failed_code_try,
    clear_failed_code_try,
)
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError

router = APIRouter(tags=["admin:auth"])

def _cookie_flags():
    secure   = False if getattr(settings, "debug", False) else True
    samesite = "Lax" if getattr(settings, "debug", False) else "None"
    path     = "/api/admin"
    max_age  = int(getattr(settings, "admin_refresh_ttl_days", 7)) * 24 * 3600
    return secure, samesite, path, max_age

@router.post("/login")
def admin_login(
    request: Request,
    response: Response,
    email: str = Body(...),
    password: str = Body(...),
    db: DB = Depends(get_db),
):
    # 1) rate-limit по IP
    ip = request.client.host if request.client else "0.0.0.0"
    check_bruteforce(db, ip)

    # 2) пошук користувача
    user = db.query(AdminUser).filter(AdminUser.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        register_failed_code_try(db, ip, "admin-login")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 3) success → reset лічильник
    clear_failed_code_try(db, ip)

    # 4) видаємо токени
    access  = create_admin_access(user_id=user.id, role=user.role)
    refresh = create_admin_refresh(user_id=user.id)

    secure, samesite, path, max_age = _cookie_flags()
    response.set_cookie(
        key="admin_refresh",
        value=refresh,
        httponly=True,
        samesite=samesite,
        secure=secure,
        max_age=max_age,
        path=path,
    )
    return {"access_token": access, "token_type": "bearer", "role": user.role}
    

@router.post("/refresh")
def admin_refresh(
    admin_refresh: str | None = Cookie(None, alias="admin_refresh"),
    db: DB = Depends(get_db),
):
    if not admin_refresh:
        raise HTTPException(401, "missing_refresh")

    # Валідуємо refresh (typ='admin_refresh')
    try:
        payload = jwt.decode(
            admin_refresh,
            getattr(settings, "admin_jwt_secret"),
            algorithms=["HS256"],
            options={"verify_aud": False, "leeway": 10},
        )
    except ExpiredSignatureError:
        raise HTTPException(401, "refresh_expired")
    except JWTError:
        raise HTTPException(401, "invalid_refresh")

    if payload.get("typ") != "admin_refresh":
        raise HTTPException(401, "invalid_refresh")

    user = db.get(AdminUser, payload.get("adm_id"))
    if not user:
        raise HTTPException(401, "unauthorized")

    access = create_admin_access(user_id=user.id, role=user.role)
    return {"access_token": access, "token_type": "bearer"}

@router.post("/logout")
def admin_logout(response: Response):
    """
    Логаут адміністратора: видаляємо admin_refresh cookie.
    Access-токен у фронта просто перестане оновлюватись і протухне сам.
    """
    secure, samesite, path, _ = _cookie_flags()
    domain = getattr(settings, "cookie_domain", None) or None

    # Надійний спосіб: перетираємо cookie порожнім значенням і max_age=0
    response.set_cookie(
        key="admin_refresh",
        value="",
        max_age=0,
        expires=0,
        httponly=True,
        samesite=samesite,
        secure=secure,
        path=path,
        domain=domain,
    )

    # (опційно) дубль на кореневий шлях, якщо колись міняли path:
    response.set_cookie(
        key="admin_refresh",
        value="",
        max_age=0,
        expires=0,
        httponly=True,
        samesite=samesite,
        secure=secure,
        path="/",
        domain=domain,
    )

    return {"ok": True}

@router.get("/me", response_model=schemas.AdminUserResponse)
def get_current_admin(
    # Використовуємо require_admin() без аргументів = дозволено будь-якому авторизованому адміну
    current_admin: AdminUser = Depends(require_admin())
):
    """
    Отримати профіль поточного авторизованого адміністратора.
    Використовується фронтендом для відображення інфо в сайдбарі та перевірки прав.
    """
    return current_admin