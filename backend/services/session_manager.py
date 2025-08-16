#v0.5
from __future__ import annotations
from sqlalchemy.orm import Session as DB
from sqlalchemy import select, func, literal
from fastapi import HTTPException

from backend.utils.dt import now_utc
from backend.models import Session, RefreshToken, SessionEvent, AccessCode
from backend.services.ws_service import broadcast, publish_terminate
from backend.services.authz.policy import code_allows_event 
from backend.services.session.constants import ONLINE_TTL_SEC
from backend.services.session.tokens import issue_access, issue_refresh, rotate_refresh as _rotate_refresh
from backend.services.session.online import mark_online, mark_offline

# (опційно) PG advisory lock для боротьби з гонками при логіні одним кодом
def _pg_advisory_lock(db: DB, key: int | str) -> None:
    try:
        # Безпечний спосіб: через чистий SQL
        db.execute("SELECT pg_advisory_xact_lock(%s)", [(hash(key) & 0x7fffffff)])
    except Exception:
        # Не PostgreSQL — ігноруємо
        pass

def login_with_code(db: DB, code_plain: str, ip: str | None = None, ua: str | None = None):
    code = db.execute(select(AccessCode).where(AccessCode.code_plain == code_plain)).scalar_one_or_none()
    if not code or getattr(code, "active", True) is False:
        raise ValueError("Invalid or inactive code")

    exp = getattr(code, "expires_at", None)
    if exp is not None and getattr(exp, "tzinfo", None) is None:
        from datetime import timezone
        exp = exp.replace(tzinfo=timezone.utc)
    if getattr(code, "revoked", False) or (exp is not None and exp <= now_utc()):
        raise HTTPException(status_code=403, detail="Code disabled or expired")

    _pg_advisory_lock(db, getattr(code, "id", code_plain))

    max_sessions = getattr(code, "max_concurrent_sessions", getattr(code, "allowed_sessions", 1))
    current = db.execute(
        select(func.count()).select_from(Session).where(Session.code_id == code.id, Session.active.is_(True))
    ).scalar_one()

    if current >= max_sessions:
        overflow = current - max_sessions + 1  # звільняємо місце для нової
        victims = db.execute(
            select(Session)
            .where(Session.code_id == code.id, Session.active.is_(True))
            .order_by(Session.created_at.asc())
            .limit(overflow)
            .with_for_update(skip_locked=True)
        ).scalars().all()

        for old in victims:
            if old.active:
                old.active = False
                old.connected = False
                db.add(SessionEvent(session_id=old.id, event="revoked"))
                try: mark_offline(old.id)
                except: pass
                try: publish_terminate(old.id, "limit_exceeded")
                except: pass
        db.flush()

    s = Session(code_id=code.id, ip=ip, user_agent=ua, active=True, connected=False)
    db.add(s); db.flush()

    access, jti = issue_access(s.id)
    s.token_jti = jti
    rjti = issue_refresh(db, s.id)

    db.add(SessionEvent(session_id=s.id, event="login"))
    db.commit()

    try:
        if current >= max_sessions:
            broadcast({"type": "session_revoked_bulk", "payload": {"code_id": code.id}})
    except: pass

    return {"access": access, "refresh": rjti, "session_id": s.id}

def rotate_refresh(db: DB, session_id: str, refresh_jti: str):
    return _rotate_refresh(db, session_id, refresh_jti)

def logout(db: DB, session_id: str):
    sess = db.get(Session, session_id)
    if not sess:
        return
    if sess.active:
        sess.active = False
    sess.connected = False
    db.query(RefreshToken).filter(
        RefreshToken.session_id == session_id, RefreshToken.revoked_at.is_(None)
    ).update({"revoked_at": now_utc()})
    db.add(SessionEvent(session_id=session_id, event="logout"))
    db.commit()
    try: mark_offline(session_id)
    except: pass
    try: publish_terminate(session_id, "admin_logout")
    except: pass
    try: broadcast({"type": "session_logout", "payload": {"id": session_id}})
    except: pass

