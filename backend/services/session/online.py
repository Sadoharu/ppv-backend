# backend/services/session/online.py
#v0.5
# backend/services/session/online.py
from __future__ import annotations
from backend.core.redis import get_redis
from backend.utils.dt import utc_ts

ONLINE_ZSET = "online:z"

def _event_zset(event_id: int) -> str:
    return f"online:z:event:{event_id}"

def mark_online(session_id: str, ttl: int) -> None:
    r = get_redis()
    now = utc_ts()
    p = r.pipeline()
    p.zadd(ONLINE_ZSET, {str(session_id): now + ttl})
    p.zremrangebyscore(ONLINE_ZSET, "-inf", now)
    p.execute()

def mark_offline(session_id: str) -> None:
    r = get_redis()
    r.zrem(ONLINE_ZSET, str(session_id))

def is_online(session_id: str) -> bool:
    r = get_redis()
    score = r.zscore(ONLINE_ZSET, str(session_id))
    return bool(score and score > utc_ts())

def ccu_estimate() -> int:
    r = get_redis()
    now = utc_ts()
    p = r.pipeline()
    p.zremrangebyscore(ONLINE_ZSET, "-inf", now)
    p.zcount(ONLINE_ZSET, now, "+inf")
    _, count = p.execute()
    return int(count)

def mark_event_online(session_id: str, event_id: int, ttl: int) -> int:
    r = get_redis()
    key = _event_zset(event_id)
    now = utc_ts()
    p = r.pipeline()
    p.zadd(key, {str(session_id): now + ttl})
    p.zremrangebyscore(key, "-inf", now)
    p.expire(key, max(ttl * 2, 300))
    p.zcount(key, now, "+inf")
    _, _, _, online_count = p.execute()
    return int(online_count)

def event_ccu(event_id: int) -> int:
    r = get_redis()
    key = _event_zset(event_id)
    now = utc_ts()
    p = r.pipeline()
    p.zremrangebyscore(key, "-inf", now)
    p.zcount(key, now, "+inf")
    _, count = p.execute()
    return int(count)
