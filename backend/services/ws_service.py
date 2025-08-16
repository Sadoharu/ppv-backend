# backend/services/ws_service.py
from __future__ import annotations

import asyncio
import logging
from typing import Set, Dict, Optional

import anyio
from starlette.websockets import WebSocket, WebSocketState
from backend.core.redis import get_redis, get_redis_async

logger = logging.getLogger(__name__)

_admin_clients: Set[WebSocket] = set()
_clients: Dict[str, WebSocket] = {}                 # session_id -> ws
_terminate_tasks: Dict[str, asyncio.Task] = {}      # session_id -> listener task

TERMINATE_CH_PREFIX = "session:terminate:"

# ─────────────── клієнтські WS ─────────────────────
def register_client(session_id: str, ws: WebSocket) -> None:
    # якщо вже був клієнт із цим sid — приберемо і зупинимо старий слухач
    _cancel_terminate_listener(session_id)
    _clients[session_id] = ws
    _start_terminate_listener(session_id)

def unregister_client(session_id: str, ws: WebSocket | None = None) -> None:
    # видалити саме цей ws (або будь-який, якщо None)
    if ws is None or _clients.get(session_id) is ws:
        _clients.pop(session_id, None)
    _cancel_terminate_listener(session_id)

def get_client_ws(session_id: str) -> Optional[WebSocket]:
    return _clients.get(session_id)

async def _terminate_async(session_id: str, reason: str = "revoked") -> None:
    ws = _clients.get(session_id)
    if not ws:
        return
    try:
        if ws.application_state == WebSocketState.CONNECTED:
            await ws.send_json({"type": "terminate", "reason": reason or "revoked"})
    except Exception:
        logger.debug("ws_terminate_send_failed", exc_info=True)
    finally:
        try:
            await ws.close()
        except Exception:
            logger.debug("ws_close_failed", exc_info=True)
        _clients.pop(session_id, None)

# ─────────────── terminate pub/sub ─────────────────
def publish_terminate(session_id: str, reason: str = "revoked") -> None:
    try:
        r = get_redis()
        r.publish(f"{TERMINATE_CH_PREFIX}{session_id}", reason or "revoked")
    except Exception:
        logger.debug("redis_publish_terminate_failed", exc_info=True)

def _start_terminate_listener(session_id: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_terminate_listener_task(session_id))
    _terminate_tasks[session_id] = task

def _cancel_terminate_listener(session_id: str) -> None:
    task = _terminate_tasks.pop(session_id, None)
    if task and not task.done():
        task.cancel()
        # не await-имо тут; cleanup відбудеться всередині finally таска

async def _terminate_listener_task(session_id: str) -> None:
    ch_name = f"{TERMINATE_CH_PREFIX}{session_id}"
    pubsub = None
    try:
        r = get_redis_async()
        pubsub = r.pubsub()
        await pubsub.subscribe(ch_name)

        while True:
            try:
                # ✔️ безпечний полінговий варіант замість async generator
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except asyncio.CancelledError:
                # отримаємо скасування, коли клієнт відʼєднався → прямуємо до finally
                break
            except Exception:
                # не валимося — продовжуємо слухати
                await asyncio.sleep(0.1)
                continue

            if not msg:
                continue
            if msg.get("type") != "message":
                continue

            data = msg.get("data")
            if isinstance(data, (bytes, bytearray)):
                data = data.decode("utf-8", errors="ignore")

            await _terminate_async(session_id, reason=str(data or "revoked"))
            break  # одноразовий terminate

    except Exception:
        logger.debug("terminate_listener_error", exc_info=True)
    finally:
        # акуратний cleanup pubsub — навіть якщо нас скасували
        try:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(ch_name)
                finally:
                    await pubsub.close()
        except Exception:
            pass

# ─────────────── адмінський broadcast ─────────────
def register_admin_ws(ws: WebSocket) -> None:
    _admin_clients.add(ws)

def unregister_admin_ws(ws: WebSocket) -> None:
    _admin_clients.discard(ws)

def broadcast(event: dict) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        anyio.from_thread.run(_broadcast_async, event)
    else:
        loop.create_task(_broadcast_async(event))

async def _broadcast_async(event: dict) -> None:
    async with anyio.create_task_group() as tg:
        for ws in list(_admin_clients):
            tg.start_soon(_safe_send, ws, event)

async def _safe_send(ws: WebSocket, event: dict) -> None:
    try:
        await ws.send_json(event)
    except Exception:
        unregister_admin_ws(ws)
