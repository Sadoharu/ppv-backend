#v0.5
#backend\routers\events.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from sqlalchemy.orm import Session as DB

from backend.database import get_db
from backend.models import Session, AccessCode, Event
from backend.core.config import settings
from backend.services.authz.policy import code_allows_event
from backend.services.authn.jwt_event import create_event_token, verify_event_token
from backend.services.heartbeat.service import handle_event_heartbeat

router = APIRouter(tags=["client:EventAccess"])

EAT_COOKIE = "eat"

def _set_eat_cookie(response: Response, eat: str, event_id: int) -> None:
    cookie_path = f"/api/events/{event_id}/"
    secure = False if settings.debug else True
    samesite = "Lax" if settings.debug else "None"
    max_age = int(getattr(settings, "event_token_ttl_seconds", 600))
    response.set_cookie(
        key=EAT_COOKIE,
        value=eat,
        httponly=True,
        secure=secure,
        samesite=samesite,
        max_age=max_age,
        path=cookie_path,
    )

@router.post("/{event_id}/enter")
def event_enter(event_id: int, request: Request, response: Response, db: DB = Depends(get_db)):
    sid = request.cookies.get("sid")
    if not sid:
        raise HTTPException(status_code=401, detail="sid_cookie_required")

    sess = db.get(Session, sid)
    if not sess or not getattr(sess, "active", False) or not getattr(sess, "code_id", None):
        raise HTTPException(status_code=401, detail="session_invalid")

    code = db.get(AccessCode, sess.code_id)
    if not code:
        raise HTTPException(status_code=401, detail="code_invalid")

    if not code_allows_event(db, code, event_id):
        raise HTTPException(status_code=403, detail="not_allowed")

    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="event_not_found")

    eat = create_event_token(session_id=sess.id, code_id=code.id, event_id=event_id, session_jti=sess.token_jti)
    _set_eat_cookie(response, eat, event_id)
    return {"ok": True, "path": f"/api/events/{event_id}/"}

@router.post("/{event_id}/heartbeat")
def event_heartbeat(event_id: int, request: Request, response: Response, db: DB = Depends(get_db)):
    eat = request.cookies.get(EAT_COOKIE)
    if not eat:
        return {"ok": False, "reason": "event_token_missing", "event_id": event_id, "event_online": None}

    # 1) Валідація EAT з перевіркою aud + leeway
    try:
        data = verify_event_token(eat, event_id=event_id)  # ми вже патчили verify_event_token під options["leeway"]
    except HTTPException as e:
        return {"ok": False, "reason": e.detail, "event_id": event_id, "event_online": None}

    sid = data.get("sid")
    if not sid:
        return {"ok": False, "reason": "session_invalid", "event_id": event_id, "event_online": None}

    # 2) Якщо jti змінився (після rotate_refresh) — перевипустити EAT
    sess = db.get(Session, str(sid))
    if not sess or not getattr(sess, "active", False):
        return {"ok": False, "reason": "session_invalid", "event_id": event_id, "event_online": None}

    expect_jti = data.get("jti")
    if expect_jti != getattr(sess, "token_jti", None):
        # jti оновився → перевипускаємо EAT з актуальним jti
        new_eat = create_event_token(session_id=sess.id, code_id=sess.code_id, event_id=event_id, session_jti=sess.token_jti)
        _set_eat_cookie(response, new_eat, event_id)
        expect_jti = sess.token_jti

    # (Опційно) якщо EAT скоро протухне — перевипустити превентивно
    try:
        ttl_sec = int(getattr(settings, "event_token_ttl_seconds", 600))
        from backend.services.auth_utils import access_expires_soon
        if access_expires_soon(eat, seconds=90):  # межа в 90с
            new_eat = create_event_token(session_id=sess.id, code_id=sess.code_id, event_id=event_id, session_jti=sess.token_jti)
            _set_eat_cookie(response, new_eat, event_id)
    except Exception:
        pass

    # 3) Делегуємо heartbeat-логіку
    out = handle_event_heartbeat(
        db=db, request=request, response=response,
        event_id=event_id, sid=str(sid), expect_jti=expect_jti,
    )
    if not out.get("ok"):
        return {"ok": False, "reason": out.get("reason"), "event_id": event_id, "event_online": None}

    return {
        "ok": True,
        "event_id": event_id,
        "event_online": out["event_online"],
        "window_sec": out["window_sec"],
    }
