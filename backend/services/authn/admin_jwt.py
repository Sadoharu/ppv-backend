from __future__ import annotations
from datetime import timedelta
from typing import Iterable, Optional, Set, Dict, Any

from fastapi import HTTPException
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError

from backend.core.config import settings
from backend.utils.dt import now_utc

ALGO = "HS256"

def _secret() -> str:
    return getattr(settings, "admin_jwt_secret")

def _issuer() -> str:
    return getattr(settings, "jwt_issuer", "backend")

def _now_ts() -> int:
    return int(now_utc().timestamp())

# TTLи з конфіга (години для access, дні для refresh)
ACCESS_TTL = timedelta(hours=int(getattr(settings, "admin_token_ttl_h", 12)))
REFRESH_TTL = timedelta(days=int(getattr(settings, "admin_refresh_ttl_days", 7)))

# Ролі за замовчуванням
DEFAULT_ALLOWED_ROLES: Set[str] = {"admin", "super", "manager", "support", "analyst"}

def create_admin_access(user_id: int | str, role: str, *, ttl: timedelta | None = None,
                        extra: Optional[Dict[str, Any]] = None) -> str:
    now = _now_ts()
    exp = now + int((ttl or ACCESS_TTL).total_seconds())
    payload: Dict[str, Any] = {
        "typ": "admin_access",
        "iss": _issuer(),
        "adm_id": int(user_id),
        "role": str(role),
        "iat": now,
        "nbf": now,
        "exp": exp,
        # "aud": "admin",  # якщо захочеш жорсткіший scoping
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _secret(), algorithm=ALGO)

def create_admin_refresh(user_id: int | str, *, ttl: timedelta | None = None) -> str:
    now = _now_ts()
    exp = now + int((ttl or REFRESH_TTL).total_seconds())
    payload = {
        "typ": "admin_refresh",
        "iss": _issuer(),
        "adm_id": int(user_id),
        "iat": now,
        "nbf": now,
        "exp": exp,
    }
    return jwt.encode(payload, _secret(), algorithm=ALGO)

def decode_admin_token(token: str) -> dict | None:
    """Мʼяке декодування без підняття помилок (зручно для перевірок у фільтрах)."""
    try:
        # без перевірки aud; leeway трохи прощає дрібний розсинхрон часу
        return jwt.decode(token, _secret(), algorithms=[ALGO],
                          options={"verify_aud": False, "leeway": 10})
    except JWTError:
        return None

def verify_admin_token(token: str, *,
                       allowed_roles: Optional[Iterable[str]] = None,
                       leeway: int = 10) -> dict:
    """
    Жорстка перевірка admin access token:
      - валідний підпис, не протух
      - typ == 'admin_access'
      - роль у дозволеному білому списку
    """
    try:
        data = jwt.decode(token, _secret(), algorithms=[ALGO],
                          options={"verify_aud": False, "leeway": leeway})
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if data.get("typ") != "admin_access":
        raise HTTPException(status_code=401, detail="Wrong token type")

    roles = set(allowed_roles or DEFAULT_ALLOWED_ROLES)
    if data.get("role") not in roles:
        raise HTTPException(status_code=403, detail="Insufficient role")
    return data
