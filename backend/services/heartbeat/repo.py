#v0.5
# backend/services/heartbeat/repo.py
from __future__ import annotations
from sqlalchemy.orm import Session as DB
from backend.models import Session, AccessCode
from backend.utils.dt import now_utc
from backend.services.session.constants import ONLINE_TTL_SEC

def get_session(db: DB, sid: str) -> Session | None:
    return db.get(Session, sid)

def get_code_for_session(db: DB, sess: Session) -> AccessCode | None:
    return db.get(AccessCode, sess.code_id) if getattr(sess, "code_id", None) else None

def touch_session(db: DB, sess: Session, *, event_id: int) -> int:
    """
    Оновлює last_seen та watch_seconds (обмежує приріст ONLINE_TTL_SEC),
    проставляє 'липку' прив'язку event_id один раз.
    Повертає вікно (сек), яке було використано для інкременту.
    """
    before = getattr(sess, "last_seen", None) or now_utc()
    now = now_utc()
    delta = max(0, int((now - before).total_seconds()))
    incr = min(delta, ONLINE_TTL_SEC)

    sess.watch_seconds = int(getattr(sess, "watch_seconds", 0)) + incr
    sess.last_seen = now
    if getattr(sess, "event_id", None) is None:
        sess.event_id = event_id

    db.commit()
    return ONLINE_TTL_SEC  # вікно для онлайн-лічильника/CCU
