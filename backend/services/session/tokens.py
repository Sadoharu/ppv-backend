#v0.5
# backend/services/session/tokens.py
from __future__ import annotations
from datetime import timedelta
from uuid import uuid4
from sqlalchemy.orm import Session as DB
from backend.core.config import settings

from backend.models import RefreshToken
from backend.services.session.policy import policy_value
from backend.services.authn.jwt import create_access_token

def issue_access(session_id: str) -> tuple[str, str]:
    minutes = policy_value("access_ttl_minutes", settings.access_ttl_minutes)
    token, jti = create_access_token({"sid": session_id}, expires_delta=timedelta(minutes=minutes))
    return token, jti

def issue_refresh(db: DB, session_id: str) -> str:
    jti = str(uuid4())
    db.add(RefreshToken(jti=jti, session_id=session_id))
    db.flush()
    return jti

def rotate_refresh(db: DB, session_id: str, refresh_jti: str) -> dict:
    from backend.utils.dt import now_utc
    rt = db.get(RefreshToken, refresh_jti)
    if not rt or rt.session_id != session_id or rt.revoked_at is not None:
        raise ValueError("Invalid refresh")
    new_jti = str(uuid4())
    rt.revoked_at = now_utc()
    rt.replaced_by = new_jti
    db.add(RefreshToken(jti=new_jti, session_id=session_id))
    access, jti = issue_access(session_id)
    sess = db.get(backend.models.Session, session_id)
    if not sess or not sess.active:
        raise ValueError("Session inactive")
    sess.token_jti = jti
    db.add(backend.models.SessionEvent(session_id=session_id, event="refresh"))
    db.commit()
    return {"access": access, "refresh": new_jti}
