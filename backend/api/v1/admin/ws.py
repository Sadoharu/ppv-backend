# backend/api/v1/admin_ws.py
from __future__ import annotations
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Header, Cookie
from backend.services.authn.admin_jwt import verify_admin_token
from backend.services.ws_service import register_admin_ws, unregister_admin_ws
import asyncio

# ВАРІАНТ 1: якщо ти підключаєш префікс у main.py — лиши без префікса
router = APIRouter(tags=["admin:ws"])
# ВАРІАНТ 2 (самодостатній): router = APIRouter(prefix="/api/ws")

def _extract_bearer(auth: str | None) -> str | None:
    if not auth:
        return None
    parts = auth.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None

@router.websocket("/admin")  # ← якщо prefab у main.py — заміни на "/admin" і додай prefix="/api/ws"
async def admin_ws(
    websocket: WebSocket,
    token: str | None = Query(None),
    authorization: str | None = Header(None),
    admin_token_cookie: str | None = Cookie(None, alias="admin_token"),
):
    # 1) приймаємо одразу (щоб мати можливість коректно повернути код закриття)
    await websocket.accept()

    # 2) джерела токена: Authorization: Bearer → cookie → query
    tok = _extract_bearer(authorization) or admin_token_cookie or token
    if not tok:
        await websocket.close(code=4401)  # Unauthorized
        return

    # 3) валідація токена
    try:
        claims = verify_admin_token(tok)
    except Exception:
        await websocket.close(code=4401)
        return

    # 4) реєструємо WS у глобальному списку, щоб broadcast() бачив його
    register_admin_ws(websocket)

    # 5) привітання + keep-alive цикл
    try:
        await websocket.send_json({"type": "welcome", "user": claims.get("adm_id"), "role": claims.get("role")})
        while True:
            # Чекаємо повідомлення від клієнта; раз на 30с шлемо ping
            try:
                _ = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break  # клієнт відвалився
    except WebSocketDisconnect:
        pass
    finally:
        # 6) акуратно прибираємо клієнта
        unregister_admin_ws(websocket)
        try:
            await websocket.close()
        except Exception:
            pass
