# backend/services/security/bruteforce.py
#unused
from __future__ import annotations
from sqlalchemy.orm import Session as DB
from backend import models
from backend.core.config import settings
from backend.utils.dt import now_utc
from fastapi import HTTPException

def register_failed_code_try(db: DB, ip: str, code_try: str) -> None:
    rec = db.get(models.FailedLogin, ip)
    if rec:
        rec.attempts = min(rec.attempts + 1, int(settings.rate_attempts) + 20)
        rec.code_try = code_try
        rec.last_try = now_utc()
    else:
        rec = models.FailedLogin(ip=ip, code_try=code_try, attempts=1, last_try=now_utc())
    db.add(rec)
    db.commit()

def clear_failed_code_try(db: DB, ip: str) -> None:
    db.query(models.FailedLogin).filter_by(ip=ip).delete()
    db.commit()

def check_bruteforce(db: DB, ip: str) -> None:
    """
    Кидає 429, якщо ліміт вичерпано і ще не минув backoff.
    Backoff: rate_base * 2^(attempts - rate_attempts - 1)
    """
    rec = db.get(models.FailedLogin, ip)
    if not rec or rec.attempts <= settings.rate_attempts:
        return

    exp_idx = rec.attempts - settings.rate_attempts - 1
    wait = int(settings.rate_base) * (2 ** max(exp_idx, 0))
    delta = int((now_utc() - rec.last_try).total_seconds())

    if delta < wait:
        raise HTTPException(status_code=429, detail=f"Too many attempts, try in {wait - delta} s")
