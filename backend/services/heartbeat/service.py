# backend/services/heartbeat/service.py
#v0.5
# backend/services/heartbeat/service.py
from __future__ import annotations
from fastapi import Request, Response
from sqlalchemy.orm import Session as DB

from backend.services.heartbeat.repo import get_session, get_code_for_session, touch_session
from backend.services.heartbeat.policies import code_expired_or_revoked
from backend.services.heartbeat.cookies import preemptive_refresh_if_needed
from backend.services.heartbeat.metrics import bump_online, bump_event_online
from backend.services.session.constants import ONLINE_TTL_SEC

def handle_event_heartbeat(
    *, db: DB, request: Request, response: Response, event_id: int, sid: str, expect_jti: str | None
) -> dict:
    # 1) валідність сесії
    sess = get_session(db, sid)
    if not sess or not getattr(sess, "active", False):
        return {"ok": False, "reason": "session_invalid"}

    # 2) звірка jti
    if expect_jti is not None and expect_jti != getattr(sess, "token_jti", None):
        return {"ok": False, "reason": "session_invalid"}

    # 3) валідність коду
    code = get_code_for_session(db, sess)
    if not code:
        return {"ok": False, "reason": "code_invalid"}
    if code_expired_or_revoked(code):
        return {"ok": False, "reason": "not_allowed"}

    # 4) preemptive refresh кукі (не критично, без винятків)
    try:
        preemptive_refresh_if_needed(request=request, response=response, db=db, session_id=str(sid))
    except Exception:
        pass

    # 5) last_seen/watch_seconds + липка привʼязка до події
    window_sec = touch_session(db, sess, event_id=event_id)

    # 6) онлайн-метрики
    bump_online(str(sid), ttl=ONLINE_TTL_SEC)
    event_online = bump_event_online(str(sid), event_id=event_id, ttl=ONLINE_TTL_SEC)

    return {"ok": True, "event_online": event_online, "window_sec": window_sec}
