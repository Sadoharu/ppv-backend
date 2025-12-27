# backend/services/heartbeat/policies.py
#v0.5
# backend/services/heartbeat/policies.py
from __future__ import annotations
from backend.models import AccessCode
from backend.utils.dt import now_utc

def code_expired_or_revoked(code: AccessCode) -> bool:
    exp = getattr(code, "expires_at", None)
    if exp is not None and getattr(exp, "tzinfo", None) is None:
        from datetime import timezone
        exp = exp.replace(tzinfo=timezone.utc)
    return bool(getattr(code, "revoked", False)) or (exp is not None and exp <= now_utc())
