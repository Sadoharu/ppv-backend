# backend/api/v1/admin_ws.py - valid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from backend.services.authn.admin_jwt import verify_admin_token

import asyncio

router = APIRouter()

@router.websocket("/api/ws/admin")
async def admin_ws(websocket: WebSocket, token: str = Query(None)):
    await websocket.accept()  # <- приймаємо одразу, щоб коректно закрити далі
    if not token:
        await websocket.close(code=4401)
        return

    try:
        claims = verify_admin_token(token)
    except Exception:
        # прострочений/недійсний токен
        await websocket.close(code=4401)
        return

    # вітання
    try:
        await websocket.send_json({"type": "welcome", "user": claims.get("adm_id"), "role": claims.get("role")})
    except Exception:
        await websocket.close(code=1011); return

    # TODO: підписка на Redis-канал(и) з адмін-подіями і пересилка їх у ws
    try:
        while True:
            # keep-alive: читаємо клієнтські повідомлення без таймаутів (або раз на N сек послати ping)
            try:
                _ = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # опційно: ping
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
