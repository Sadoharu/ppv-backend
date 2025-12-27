# backend/workers/session_gc.py
#v0.5
# backend/workers/session_gc.py
from __future__ import annotations
import asyncio
import logging
from datetime import timedelta

import anyio
from sqlalchemy.orm import Session as DB
from sqlalchemy import and_, or_

from backend.database import SessionLocal
from backend.core.config import settings
from backend import models
from backend.utils.dt import now_utc

log = logging.getLogger(__name__)

def _gc_once(db: DB, batch: int) -> dict:
    """
    Видаляє старі записи батчами:
      - RefreshToken: revoked_at < rt_cut
      - SessionEvent: at < ev_cut
      - Session: inactive AND (last_seen < sess_cut OR (last_seen IS NULL AND created_at < sess_cut))
    """
    stats = {"sessions": 0, "refresh": 0, "events": 0}

    n = now_utc()
    sess_cut = n - timedelta(days=settings.session_retention_days)
    rt_cut   = n - timedelta(days=settings.refresh_tokens_retention_days)
    ev_cut   = n - timedelta(days=settings.session_events_retention_days)

    # 1) RefreshToken
    rts = (
        db.query(models.RefreshToken.jti)
          .filter(models.RefreshToken.revoked_at.isnot(None))
          .filter(models.RefreshToken.revoked_at < rt_cut)
          .limit(batch)
          .all()
    )
    r_ids = [row[0] for row in rts]
    if r_ids:
        db.query(models.RefreshToken).filter(models.RefreshToken.jti.in_(r_ids))\
          .delete(synchronize_session=False)
        db.commit()
        stats["refresh"] += len(r_ids)

    # 2) SessionEvent
    evs = (
        db.query(models.SessionEvent.id)
          .filter(models.SessionEvent.at < ev_cut)
          .limit(batch)
          .all()
    )
    e_ids = [row[0] for row in evs]
    if e_ids:
        db.query(models.SessionEvent).filter(models.SessionEvent.id.in_(e_ids))\
          .delete(synchronize_session=False)
        db.commit()
        stats["events"] += len(e_ids)

    # 3) Session (лише неактивні)
    sess = (
        db.query(models.Session.id)
          .filter(models.Session.active.is_(False))
          .filter(
              or_(
                  and_(models.Session.last_seen.isnot(None),
                       models.Session.last_seen < sess_cut),
                  and_(models.Session.last_seen.is_(None),
                       models.Session.created_at < sess_cut),
              )
          )
          .limit(batch)
          .all()
    )
    s_ids = [row[0] for row in sess]
    if s_ids:
        db.query(models.Session).filter(models.Session.id.in_(s_ids))\
          .delete(synchronize_session=False)
        db.commit()
        stats["sessions"] += len(s_ids)

    return stats

def _run_gc_batches() -> dict:
    """
    Один синхронний цикл GC: крутить батчі, поки є що чистити.
    Повертає сумарну статистику.
    """
    total = {"sessions": 0, "refresh": 0, "events": 0}
    batch = int(getattr(settings, "gc_batch_size", 500)) or 500

    # (опціонально) PG advisory lock, щоб не ганяли кілька GC одночасно
    def _try_advisory_lock(db: DB) -> None:
        try:
            db.execute("SELECT pg_try_advisory_lock(%s)", [(hash("session_gc") & 0x7fffffff)])
        except Exception:
            pass

    with SessionLocal() as db:
        _try_advisory_lock(db)
        while True:
            stats = _gc_once(db, batch)
            for k, v in stats.items():
                total[k] += int(v)
            if all(v == 0 for v in stats.values()):
                break
    return total

async def run_session_gc(poll_minutes: int | None = None):
    """
    Фоновий цикл: раз на N хвилин запускає GC у threadpool,
    щоб не блокувати event loop.
    """
    interval = int(poll_minutes or getattr(settings, "gc_interval_minutes", 10)) * 60
    while True:
        try:
            total = await anyio.to_thread.run_sync(_run_gc_batches)
            if any(total.values()):
                log.info("session_gc", extra={"stats": total})
        except Exception:
            log.exception("session_gc_failed")
        await asyncio.sleep(interval)
