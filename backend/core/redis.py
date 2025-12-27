# backend/core/redis.py
from __future__ import annotations
from functools import lru_cache
from typing import Optional

from redis import Redis as SyncRedis, from_url as sync_from_url
from redis.asyncio import Redis as AsyncRedis
from redis.asyncio import from_url as async_from_url

from backend.core.config import settings

def _get_url() -> Optional[str]:
    # головне джерело — повний URL. Підтримує і rediss://
    return getattr(settings, "redis_url", None)

def _common_kwargs():
    return dict(
        decode_responses=True,                                # текстові значення (зручно для hgetall/publish)
        socket_timeout=float(getattr(settings, "redis_socket_timeout", 2.0)),
        socket_connect_timeout=float(getattr(settings, "redis_connect_timeout", 2.0)),
        health_check_interval=int(getattr(settings, "redis_health_interval", 30)),
        retry_on_timeout=True,
        max_connections=int(getattr(settings, "redis_max_connections", 100)),
    )

@lru_cache(maxsize=1)
def get_redis() -> SyncRedis:
    """Singleton на процес (uvicorn worker). Не треба закешовувати самостійно — вже @lru_cache."""
    url = _get_url()
    kw = _common_kwargs()
    if url:
        return sync_from_url(url, **kw)
    host = getattr(settings, "redis_host", "redis")
    port = int(getattr(settings, "redis_port", 6379) or 6379)
    db   = int(getattr(settings, "redis_db", 0) or 0)
    return SyncRedis(host=host, port=port, db=db, **kw)

@lru_cache(maxsize=1)
def get_redis_async() -> AsyncRedis:
    """Singleton async-клієнта. УВАГА: виклик **без await** — повертає готовий клієнт."""
    url = _get_url()
    kw = _common_kwargs()
    if url:
        return async_from_url(url, **kw)
    host = getattr(settings, "redis_host", "redis")
    port = int(getattr(settings, "redis_port", 6379) or 6379)
    db   = int(getattr(settings, "redis_db", 0) or 0)
    return AsyncRedis(host=host, port=port, db=db, **kw)

# ── утиліти для старт/завершення застосунку ────────────────────────────
def close_redis() -> None:
    try:
        get_redis().close()
    except Exception:
        pass

async def close_redis_async() -> None:
    try:
        await get_redis_async().close()
    except Exception:
        pass

def ping_ok() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        return False

async def aping_ok() -> bool:
    try:
        return bool(await get_redis_async().ping())
    except Exception:
        return False
