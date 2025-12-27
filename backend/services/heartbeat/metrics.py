# backend/services/heartbeat/metrics.py
#v0.5
# backend/services/heartbeat/metrics.py
from __future__ import annotations
from backend.services.session.online import mark_online, mark_event_online

def bump_online(sid: str, ttl: int) -> None:
    mark_online(sid, ttl=ttl)

def bump_event_online(sid: str, event_id: int, ttl: int) -> int:
    return mark_event_online(sid, event_id, ttl=ttl)
