# done
# backend/services/auth_utils.py
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from backend.services.authn.jwt import decode_token

def access_expires_soon(access_token: Optional[str], seconds: int = 120) -> bool:
    """
    True, якщо токена немає або до його exp ≤ seconds.
    """
    if not access_token:
        return True
    data = decode_token(access_token)  # payload | None
    if not data or "exp" not in data:
        return True
    now = int(datetime.now(timezone.utc).timestamp())
    return (int(data["exp"]) - now) <= int(seconds)
