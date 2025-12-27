# backend/services/authn/lookup.py
#unused
from __future__ import annotations
from sqlalchemy.orm import Session as DB
from sqlalchemy import select
from backend import models
from backend.services.authn.jwt import decode_token

def get_session_by_token(db: DB, token: str) -> models.Session | None:
    """
    Вертає активну Session за JWT або None.
    """
    payload = decode_token(token)
    if not payload:
        return None
    jti = payload.get("jti")
    if not jti:
        return None
    q = select(models.Session).where(
        models.Session.token_jti == jti,
        models.Session.active.is_(True),
    )
    return db.execute(q).scalars().first()
