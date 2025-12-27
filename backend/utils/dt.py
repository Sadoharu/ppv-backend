# backend/utils/dt.py

from __future__ import annotations
from datetime import datetime, timezone
from time import time

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def ensure_aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

def utc_ts() -> int:
    return int(time())
