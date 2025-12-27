# backend/services/session/policy.py
#v0.5
# backend/services/session/policy.py
from __future__ import annotations
from typing import Any, Dict
from time import monotonic
from backend.core.redis import get_redis

POLICY_HASH = "policy"
POLICY_CACHE_TTL = 30.0  # seconds

_cache: Dict[str, Any] = {}
_cache_expire_at: float = 0.0

def _as_bool(v: str | None) -> bool | None:
    if v is None or v == "":
        return None
    return str(v).lower() in ("1", "true", "yes", "on")

def _refresh_cache() -> None:
    global _cache, _cache_expire_at
    r = get_redis()
    raw = r.hgetall(POLICY_HASH) or {}
    # bytes -> str
    parsed = {}
    for k, v in raw.items():
        ks = k.decode() if isinstance(k, (bytes, bytearray)) else str(k)
        vs = v.decode() if isinstance(v, (bytes, bytearray)) else v
        parsed[ks] = vs
    _cache = parsed
    _cache_expire_at = monotonic() + POLICY_CACHE_TTL

def _get_policy() -> Dict[str, Any]:
    if monotonic() >= _cache_expire_at:
        _refresh_cache()
    return _cache

def policy_value(name: str, default: Any) -> Any:
    pol = _get_policy()
    v = pol.get(name)
    if v is None or v == "":
        return default
    # Явне приведення типів
    if isinstance(default, bool):
        b = _as_bool(v)
        return default if b is None else b
    if isinstance(default, int):
        try: return int(v)
        except: return default
    if isinstance(default, float):
        try: return float(v)
        except: return default
    return str(v)
