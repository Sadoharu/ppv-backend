# backend/api/v1/client/ws.py
# v0.6
# backend/api/v1/client_ws.py
from __future__ import annotations
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState
import asyncio

from backend.services.ws_service import register_client, unregister_client, broadcast
from backend.services.session.online import mark_offline
from backend.core.redis import get_redis_async

router = APIRouter(tags=["client:ws"])

@router.websocket("/ws/client")  # фінальний шлях буде /api/ws/client (через префікс у main.py)
async def client_ws(ws: WebSocket, session_id: str | None = Query(None)):
    await ws.accept()

    # sid з query або з cookie
    sid = session_id or ws.cookies.get("sid")
    if not sid:
        await ws.close(code=4401)  # Unauthorized
        return
    sid = str(sid)

    register_client(sid, ws)
    broadcast({"type": "session_connected", "payload": {"id": sid}})

    # Redis pubsub для terminate-сигналів між воркерами
    r = get_redis_async()
    psub = r.pubsub()
    channel = f"session:terminate:{sid}"
    await psub.subscribe(channel)

    try:
        while True:
            # 1) Перевіряємо, чи прийшло terminate-повідомлення
            try:
                msg = await psub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except Exception:
                msg = None

            if msg and msg.get("type") == "message":
                reason = msg.get("data") or "revoked"
                try:
                    if ws.application_state == WebSocketState.CONNECTED:
                        await ws.send_json({"type": "terminate", "reason": reason})
                except Exception:
                    pass
                finally:
                    try:
                        await ws.close()
                    except Exception:
                        pass
                    break

            # 2) Намагаємося прочитати будь-який клієнтський пакет, щоб ловити відʼєднання
            try:
                _ = await asyncio.wait_for(ws.receive_text(), timeout=0.25)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        # коректно закриваємо pubsub, прибираємо клієнта і позначаємо офлайн
        try:
            await psub.unsubscribe(channel)
            await psub.close()
        except Exception:
            pass

        unregister_client(sid, ws)
        try:
            mark_offline(sid)
        except Exception:
            pass

        broadcast({"type": "session_disconnected", "payload": {"id": sid}})
