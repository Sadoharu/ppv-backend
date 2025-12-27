# backend/api/v1/delete/client_ws.py
#v0.5
# backend/api/v1/client_ws.py
from __future__ import annotations
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.orm import Session as DB

from backend.api.deps import get_db
from backend.services.ws_service import register_client, unregister_client, broadcast
from backend.services.session.online import mark_offline  # ← правильний імпорт

router = APIRouter()

@router.websocket("/api/ws/client")
async def client_ws(
    ws: WebSocket,
    session_id: str | None = Query(None),
    db: DB = Depends(get_db),  # якщо не використовуєш тут — можна прибрати Depends
):
    await ws.accept()

    # sid із query або з кукі
    sid = session_id or ws.cookies.get("sid")
    if not sid:
        await ws.close(code=4401)  # Unauthorized
        return
    sid = str(sid)

    # реєструємо клієнта: це також стартує terminate-listener у ws_service
    register_client(sid, ws)
    broadcast({"type": "session_connected", "payload": {"id": sid}})

    try:
        # Проста «idle» петля: чекаємо дані або відʼєднання.
        # Коли прийде publish_terminate(), ws_service закриє сокет → тут вилетить WebSocketDisconnect.
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        unregister_client(sid, ws)
        try:
            # миттєво офлайн по закриттю вкладки
            mark_offline(sid)
        except Exception:
            pass
        broadcast({"type": "session_disconnected", "payload": {"id": sid}})
