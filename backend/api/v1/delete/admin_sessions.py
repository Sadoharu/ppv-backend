#backend\api\v1\admin_sessions.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session as DB
from sqlalchemy import or_
from datetime import datetime, timezone

from backend.api.deps import require_admin_token
from backend.database import get_db
from backend import models
from backend.services.session.online import ccu_estimate, is_online
from backend.services.session_manager import logout as do_logout 
from backend.services.ws_service import broadcast, publish_terminate

router = APIRouter(prefix="/api/admin", tags=["admin:sessions"])

def now_utc():
    return datetime.now(timezone.utc)

@router.get("/ccu")
def admin_ccu(current=Depends(require_admin_token)):
    return {"ccu": ccu_estimate()}

@router.get("/sessions")
def list_sessions(
    current=Depends(require_admin_token),
    db: DB = Depends(get_db),
    q: str | None = Query(None, description="search by session id / ip / ua / code"),
    active: int | None = Query(None, description="1/0"),
    connected: int | None = Query(None, description="1/0 (legacy)"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    qry = (
        db.query(models.Session)
        .join(models.AccessCode, models.Session.code_id == models.AccessCode.id)
    )

    if q:
        like = f"%{q}%"
        qry = qry.filter(or_(
            models.Session.id.ilike(like),
            models.Session.ip.ilike(like),
            models.Session.user_agent.ilike(like),
            models.AccessCode.code_plain.ilike(like),
        ))

    if active is not None:
        qry = qry.filter(models.Session.active == (active == 1))
    if connected is not None:
        # legacy: лишаємо, але справжній online беремо з Redis
        qry = qry.filter(models.Session.connected == (connected == 1))

    total = qry.count()
    rows = (
        qry.order_by(models.Session.created_at.desc())
           .limit(limit).offset(offset).all()
    )

    items = []
    for s in rows:
        code = db.get(models.AccessCode, s.code_id)
        event_title = None
        if code is not None:
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
            "connected": bool(getattr(s, "connected", False)),  # legacy
            "online": is_online(s.id),                          # ← реальний онлайн

            "ip": s.ip,
            "user_agent": s.user_agent,

            "created_at": s.created_at,
            "last_seen": getattr(s, "last_seen", None),
            "expires_at": getattr(code, "expires_at", None),

            "watch_seconds": getattr(s, "watch_seconds", 0),
            "bytes_out": getattr(s, "bytes_out", 0),
        })

    return {"total": total, "items": items}

@router.post("/sessions/{session_id}/terminate")
def terminate_session(
    session_id: str,
    current=Depends(require_admin_token),
    db: DB = Depends(get_db),
):
    s = db.get(models.Session, session_id)
    if not s:
        raise HTTPException(404, "not_found")

    do_logout(db, session_id=session_id)  # централізовано: active=False, refresh-и закриті, подія

    try:
        publish_terminate(session_id, reason="admin_revoke")
    except Exception:
        pass

    try:
        broadcast({"type": "session_revoked", "payload": {"id": session_id}})
    except Exception:
        pass
    return {"ok": True}

@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    current=Depends(require_admin_token),
    db: DB = Depends(get_db),
):
    s = db.get(models.Session, session_id)
    if not s:
        raise HTTPException(404, "not_found")

    try:
        publish_terminate(session_id, reason="admin_delete")
    except Exception:
        pass

    db.delete(s)
    db.commit()
    try:
        broadcast({"type": "session_deleted", "payload": {"id": session_id}})
    except Exception:
        pass
    return {"ok": True}

@router.post("/gc")
def run_gc_now(current=Depends(require_admin_token), db: DB = Depends(get_db)):
    from backend.workers.session_gc import gc_once
    stats = gc_once(db)
    return {"ok": True, "stats": stats}