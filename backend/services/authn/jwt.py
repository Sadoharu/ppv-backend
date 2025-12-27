# backend/services/authn/jwt.py
#v0.5
from __future__ import annotations
from datetime import timedelta
from uuid import uuid4
from jose import jwt, JWTError

from backend.core.config import settings
from backend.utils.dt import now_utc

ALGORITHM = "HS256"

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> tuple[str, str]:
    """
    Повертає (token, jti). exp виставляємо як epoch seconds (int), щоб
    уніфіковано працювати з декодером і порівнянням у auth_utils.
    """
    to_encode = dict(data)
    jti = str(uuid4())
    to_encode["jti"] = jti

    minutes = expires_delta or timedelta(minutes=settings.access_ttl_minutes)
    exp_ts = int((now_utc() + minutes).timestamp())
    to_encode["exp"] = exp_ts

    token = jwt.encode(to_encode, settings.jwt_secret, algorithm=ALGORITHM)
    return token, jti

def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        return None
