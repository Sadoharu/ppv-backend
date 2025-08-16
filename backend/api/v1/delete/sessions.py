# backend/api/v1/sessions.py
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from backend.api.deps import require_admin_token, get_db
from backend import models
from backend.services.ws_service import get_client_ws, broadcast
from backend.services.session_manager import now_utc

router = APIRouter(prefix="/api/admin/sessions", tags=["sessions"])

@router.get("")
def list_sessions(
    current=Depends(require_admin_token),
    db: Session = Depends(get_db),
    active: bool | None = Query(None),
    connected: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    q = db.query(models.Session).join(models.AccessCode, models.Session.code_id == models.AccessCode.id)
    if active is not None:
        q = q.filter(models.Session.active.is_(active))
    if connected is not None:
        q = q.filter(models.Session.connected.is_(connected))
    total = q.count()
    rows = (q.order_by(models.Session.created_at.desc())
              .limit(limit).offset(offset).all())
    items = []
    for s in rows:
        items.append({
            "id": s.id,
            "code_id": s.code_id,
            "active": s.active,
            "connected": s.connected,
            "ip": s.ip,
            "user_agent": s.user_agent,
            "created_at": s.created_at,
            "last_seen": s.last_seen,
            "watch_seconds": getattr(s, "watch_seconds", 0),
            "bytes_out": getattr(s, "bytes_out", 0),
        })
    return {"total": total, "items": items}

@router.post("/{sid}/terminate")
async def terminate_session(sid: str,
                            current=Depends(require_admin_token),
                            db: Session = Depends(get_db)):
    s = db.get(models.Session, sid)
    if not s:
        raise HTTPException(404, "not_found")
    s.active = False
    s.connected = False
    # відкликаємо refresh токени
    db.query(models.RefreshToken).filter_by(session_id=sid, revoked_at=None) \
      .update({"revoked_at": now_utc()})
    db.commit()
    # закриваємо WS, якщо відкритий
    ws = get_client_ws(sid)
    if ws:
        try:
            await ws.send_json({"type": "terminate"})
            await ws.close(code=4000, reason="terminated")
        except:
            pass
    await broadcast({"type": "session_terminated", "payload": {"id": sid}})
    return {"ok": True}

@router.delete("/{sid}", status_code=204)
async def delete_session(sid: str,
                         current=Depends(require_admin_token),
                         db: Session = Depends(get_db)):
    s = db.get(models.Session, sid)
    if not s:
        return
    db.delete(s); db.commit()
    await broadcast({"type": "session_deleted", "payload": {"id": sid}})
