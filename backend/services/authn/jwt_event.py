#v0.5
from __future__ import annotations
from typing import Any, Dict, Optional
from datetime import timedelta
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from fastapi import HTTPException

from backend.core.config import settings
from backend.utils.dt import now_utc

ALGO = "HS256"

def _secret() -> str:
    # окремий секрет для EAT, якщо заданий; інакше звичайний
    return getattr(settings, "event_jwt_secret", settings.jwt_secret)

def create_event_token(
    *,
    session_id: int | str,
    code_id: int | str,
    event_id: int | str,
    session_jti: str,
    ttl_seconds: int | None = None,
) -> str:
    ttl = int(ttl_seconds or getattr(settings, "event_token_ttl_seconds", 600))
    now_ts = int(now_utc().timestamp())
    aud = f"event:{int(event_id)}"

    payload: Dict[str, Any] = {
        "typ": "EAT",                  # Event Access Token
        "iss": getattr(settings, "jwt_issuer", "backend"),
        "aud": aud,
        "sid": str(session_id),
        "code_id": int(code_id),
        "event_id": int(event_id),
        "jti": str(session_jti),       # звіряємо з Session.token_jti
        "iat": now_ts,
        "nbf": now_ts,                 # можна додати невеликий skew через leeway
        "exp": now_ts + ttl,
    }

    headers = {}
    kid = getattr(settings, "jwt_kid", None)
    if kid:
        headers["kid"] = str(kid)

    return jwt.encode(payload, _secret(), algorithm=ALGO, headers=headers)

def verify_event_token(
    token: str,
    *,
    event_id: int | None = None,
    leeway: int = 10,
) -> dict:
    try:
        if event_id is None:
            # без перевірки aud + leeway через options
            data = jwt.decode(
                token,
                _secret(),
                algorithms=[ALGO],
                options={"verify_aud": False, "leeway": leeway},
            )
        else:
            # з перевіркою aud + leeway через options
            data = jwt.decode(
                token,
                _secret(),
                algorithms=[ALGO],
                audience=f"event:{int(event_id)}",
                options={"leeway": leeway},
            )
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="event_token_expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="event_token_invalid")

    if data.get("typ") != "EAT":
        raise HTTPException(status_code=401, detail="event_token_wrong_type")

    if event_id is not None and int(data.get("event_id", -1)) != int(event_id):
        raise HTTPException(status_code=401, detail="event_token_event_mismatch")

    for k in ("sid", "jti", "code_id"):
        if k not in data:
            raise HTTPException(status_code=401, detail=f"event_token_missing_{k}")

    return data
