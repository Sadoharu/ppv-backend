#v0.5
# backend/services/heartbeat/cookies.py
from __future__ import annotations
from fastapi import Request, Response
from backend.core.config import settings
from backend.services.auth_utils import access_expires_soon
from backend.services.session.tokens import rotate_refresh

def preemptive_refresh_if_needed(
    *, request: Request, response: Response, db, session_id: str, threshold_sec: int = 120
) -> None:
    access  = request.cookies.get("viewer_token")
    refresh = (request.cookies.get("viewer_refresh")
               or request.cookies.get("rjti")
               or request.cookies.get("refresh_jti"))

    if not access or not refresh:
        return

    if not access_expires_soon(access, seconds=threshold_sec):
        return

    out = rotate_refresh(db, session_id=session_id, refresh_jti=refresh)

    secure_flag = False if settings.debug else True
    same_site   = "Lax"  if settings.debug else "None"

    response.set_cookie(
        "viewer_token", out["access"],
        httponly=True, samesite=same_site, secure=secure_flag, path="/",
        max_age=settings.access_ttl_minutes * 60,
    )
    response.set_cookie(
        "viewer_refresh", out["refresh"],
        httponly=True, samesite=same_site, secure=secure_flag, path="/",
    )
