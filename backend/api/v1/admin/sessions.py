# backend/api/v1/admin/sessions.py
from __future__ import annotations
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, cast, String
from sqlalchemy.orm import Session as DB, selectinload

from backend.api.deps import require_admin   # фабрика з deps.py
from backend.database import get_db
from backend import models
from backend.services.session.online import ccu_estimate, is_online
from backend.services.session_manager import logout as do_logout
from backend.services.ws_service import broadcast, publish_terminate

# Доступ: Super, Admin, Support (Support повинен бачити сесії клієнтів)
router = APIRouter(
    tags=["admin:sessions"],
    dependencies=[Depends(require_admin("admin", "super", "support"))],
)

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

@router.get("/ccu")
def admin_ccu():
    return {"ccu": ccu_estimate()}

@router.get("/sessions")
def list_sessions(
    db: DB = Depends(get_db),
    q: str | None = Query(None, description="search by session id / ip / ua / code"),
    active: int | None = Query(None, description="1/0"),
    connected: int | None = Query(None, description="1/0 (legacy)"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    Повертає список сесій з реальним online з Redis.
    Уникаємо N+1: тягнемо code + (batch|event) selectinload'ом.
    """
    qry = (
        db.query(models.Session)
          .options(
              selectinload(models.Session.code)
                  .selectinload(models.AccessCode.batch),
              selectinload(models.Session.code)
                  .selectinload(models.AccessCode.event),
          )
          .join(models.AccessCode, models.Session.code_id == models.AccessCode.id, isouter=True)
    )

    if q:
        like = f"%{q}%"
        qry = qry.filter(or_(
            cast(models.Session.id, String).ilike(like),   # id може бути UUID/str
            models.Session.ip.ilike(like),
            models.Session.user_agent.ilike(like),
            models.AccessCode.code_plain.ilike(like),
        ))

    if active is not None:
        qry = qry.filter(models.Session.active == (active == 1))
    if connected is not None:
        # legacy: залишили фільтр, але справжній online вираховуємо нижче
        qry = qry.filter(models.Session.connected == (connected == 1))

    total = qry.count()
    rows = (
        qry.order_by(models.Session.created_at.desc())
           .limit(limit).offset(offset).all()
    )

    items = []
    for s in rows:
        code = s.code  # вже підвантажено selectinload'ом
        # людська назва події/батча (якщо є)
        event_title = None
        if getattr(code, "batch", None) and getattr(code.batch, "label", None):
            event_title = code.batch.label
        elif getattr(code, "event", None) and getattr(code.event, "title", None):
            event_title = code.event.title

        items.append({
            "id": s.id,
            "code_id": s.code_id,
            "code": getattr(code, "code_plain", None),
            "event": event_title,

            "active": bool(s.active),
            "connected": bool(getattr(s, "connected", False)),  # legacy прапорець
            "online": is_online(s.id),                          # реальний онлайн

            "ip": s.ip,
            "user_agent": s.user_agent,

            "created_at": s.created_at,
            "last_seen": getattr(s, "last_seen", None),
            "expires_at": getattr(code, "expires_at", None),

            "watch_seconds": int(getattr(s, "watch_seconds", 0) or 0),
            "bytes_out": int(getattr(s, "bytes_out", 0) or 0),
        })

    return {"total": total, "items": items}

@router.post("/sessions/{session_id}/terminate")
def terminate_session(
    session_id: str,
    db: DB = Depends(get_db),
):
    s = db.get(models.Session, session_id)
    if not s:
        raise HTTPException(404, "not_found")

    # Централізований логаут: active=False, refresh-и закриті, івент доданий
    do_logout(db, session_id=session_id)

    # Сигнал WS-клієнту та адмінкам
    try: publish_terminate(session_id, reason="admin_revoke")
    except Exception: pass
    try: broadcast({"type": "session_revoked", "payload": {"id": session_id}})
    except Exception: pass

    return {"ok": True}

@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    db: DB = Depends(get_db),
):
    s = db.get(models.Session, session_id)
    if not s:
        raise HTTPException(404, "not_found")

    # Спочатку коректний логаут (закриє refresh-и), потім видалення
    try:
        publish_terminate(session_id, reason="admin_delete")
    except Exception:
        pass

    do_logout(db, session_id=session_id)  # безпечно, навіть якщо вже inactive
    db.delete(s)
    db.commit()

    try: broadcast({"type": "session_deleted", "payload": {"id": session_id}})
    except Exception: pass

    return {"ok": True}

@router.post("/gc")
def run_gc_now(db: DB = Depends(get_db)):
    from backend.workers.session_gc import gc_once
    stats = gc_once(db)
    return {"ok": True, "stats": stats}