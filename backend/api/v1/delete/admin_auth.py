# backend/api/v1/admin_auth.py - valid
from fastapi import APIRouter, Depends, HTTPException, Body, Request, Response, Cookie
from sqlalchemy.orm import Session as DB
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from datetime import timedelta, datetime, timezone
from jwt import InvalidTokenError, ExpiredSignatureError
import jwt as _jwt  # щоб уникнути колізій з вашим імпортом jwt

from backend.database import get_db
from backend.models import AdminUser, FailedLogin
from backend.services.authn.admin_jwt import create_admin_access, create_admin_refresh

from backend.core.config import settings
from datetime import datetime

router = APIRouter(prefix="/api/admin", tags=["admin:auth"])
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def _check_rate_limit(db: DB, ip: str):
    rec = db.query(FailedLogin).get(ip)
    if not rec:
        return
    # простий ліміт: якщо спроб більше rate_attempts і остання спроба була занадто недавно — блокуємо
    if rec.attempts > settings.rate_attempts:
        # експоненційний бек-офф
        exp_idx = rec.attempts - settings.rate_attempts - 1
        wait = settings.rate_base * (2 ** exp_idx)
        delta = (datetime.utcnow() - rec.last_try).total_seconds()
        if delta < wait:
            raise HTTPException(status_code=429, detail=f"Too many attempts. Wait {int(wait - delta)}s")

def _inc_failed(db: Session, ip: str, code_try: str | None = None):
    # для адмін-логіну code_try часто None -> підставляємо плейсхолдер
    code_try = code_try or "admin-login"
    row = db.query(FailedLogin).filter_by(ip=ip, code_try=code_try).first()
    if row:
        row.attempts += 1
        row.last_try = datetime.utcnow()
    else:
        row = FailedLogin(ip=ip, code_try=code_try, attempts=1, last_try=datetime.utcnow())
        db.add(row)
    db.commit()

def _reset_failed(db: DB, ip: str):
    rec = db.query(FailedLogin).get(ip)
    if rec:
        db.delete(rec)
        db.commit()

@router.post("/login")
def admin_login(
    request: Request,
    response: Response,
    email: str = Body(...),
    password: str = Body(...),
    db: DB = Depends(get_db),
    
):
    ip = request.client.host if request.client else "0.0.0.0"
    _check_rate_limit(db, ip)

    user = db.query(AdminUser).filter(AdminUser.email == email).first()
    if not user or not pwd_ctx.verify(password, user.hashed_password):
        _inc_failed(db, ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _reset_failed(db, ip)
    access = create_admin_access(user_id=user.id, role=user.role)
    refresh = create_admin_refresh(user_id=user.id)
    response.set_cookie(
        key="admin_refresh",
        value=refresh,
        httponly=True,
        samesite="lax",
        secure=getattr(settings, "cookie_secure", False),
        max_age=7*24*3600,
        path="/api/admin",  # обмежений шлях — безпечніше
    )
    return {"access_token": access, "token_type": "bearer", "role": user.role}

@router.post("/refresh")
def admin_refresh(
    admin_refresh: str | None = Cookie(None, alias="admin_refresh"),
    db: DB = Depends(get_db),
):
    if not admin_refresh:
        raise HTTPException(401, "missing_refresh")
    try:
        payload = _jwt.decode(admin_refresh, settings.admin_jwt_secret, algorithms=["HS256"])
        if payload.get("typ") != "admin_refresh":
            raise HTTPException(401, "invalid_refresh")
    except ExpiredSignatureError:
        raise HTTPException(401, "refresh_expired")
    except InvalidTokenError:
        raise HTTPException(401, "invalid_refresh")

    user = db.query(AdminUser).get(payload.get("adm_id"))
    if not user:
        raise HTTPException(401, "unauthorized")

    access = create_admin_access(user_id=user.id, role=user.role)
    return {"access_token": access, "token_type": "bearer"}
