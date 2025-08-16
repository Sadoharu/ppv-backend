#v0.5
# backend/workers/idle_reaper.py
from __future__ import annotations
import asyncio
import logging
from typing import Iterable, List, Sequence

import anyio
from datetime import timedelta
from sqlalchemy import or_

from backend.core.redis import get_redis
from backend.database import SessionLocal
from backend import models
from backend.services.ws_service import broadcast, publish_terminate
from backend.services.session.policy import policy_value
from backend.services.session.constants import ONLINE_TTL_SEC
from backend.services.session.online import ONLINE_ZSET  # використовуємо ZSET
from backend.utils.dt import now_utc, utc_ts

log = logging.getLogger(__name__)

BATCH_LIMIT = 500

async def run_idle_reaper(poll_seconds: int = 30) -> None:
    """
    Периодично деактивує сесії, які:
      - active == True
      - last_seen відсутній або старший за N хвилин (політика)
      - НЕ вважаються онлайн за нашим ZSET (score <= now)
    """
    while True:
        try:
            idle_minutes = int(policy_value("auto_release_idle_minutes", 0))
            if idle_minutes > 0:
                threshold = now_utc() - timedelta(minutes=idle_minutes)

                # 1) беремо кандидатів (sync БД → в threadpool)
                sids = await anyio.to_thread.run_sync(_fetch_idle_session_ids, threshold, BATCH_LIMIT)

                if sids:
                    # 2) фільтруємо тих, хто реально офлайн по ZSET (sync Redis → в threadpool)
                    offline_sids = await anyio.to_thread.run_sync(_filter_offline_by_zset, sids)

                    if offline_sids:
                        # 3) деактивуємо в БД (sync БД → в threadpool)
                        await anyio.to_thread.run_sync(_deactivate_sessions, offline_sids)

                        # 4) сповіщаємо після commit (terminate + broadcast)
                        for sid in offline_sids:
                            try: publish_terminate(sid, reason="idle_timeout")
                            except Exception: pass
                            try: broadcast({"type": "session_revoked", "payload": {"id": sid}})
                            except Exception: pass
        except Exception:
            log.exception("idle_reaper_pass_failed")
        await asyncio.sleep(poll_seconds)

# ───────────────────────── helpers (sync) ─────────────────────────

def _fetch_idle_session_ids(threshold, limit: int) -> List[str]:
    """
    Витягує до limit активних сесій, у яких last_seen <= threshold або NULL.
    Повертає список рядкових sid.
    """
    with SessionLocal() as db:
        rows: Sequence[models.Session] = (
            db.query(models.Session.id)
              .filter(models.Session.active.is_(True))
              .filter(or_(models.Session.last_seen.is_(None), models.Session.last_seen < threshold))
              .limit(int(limit))
              .all()
        )
        # rows можуть бути кортежами або об’єктами залежно від ORM; нормалізуємо
        out: List[str] = []
        for r in rows:
            sid = getattr(r, "id", None) if hasattr(r, "id") else (r[0] if isinstance(r, (tuple, list)) else r)
            if sid is not None:
                out.append(str(sid))
        return out

def _filter_offline_by_zset(sids: Iterable[str]) -> List[str]:
    """
    Для переданих sid повертає ті, що НЕ онлайн за ZSET:
    score <= now_ts або відсутній.
    """
    r = get_redis()
    now = utc_ts()
    pipe = r.pipeline()
    # Redis 6.2+ має ZMSCORE; якщо немає — робимо батч ZSCORE
    try:
        # спроба ZMSCORE
        res = r.execute_command("ZMSCORE", ONLINE_ZSET, *[str(s) for s in sids])
        scores = list(res)
    except Exception:
        # fallback: окремими ZSCORE у pipeline
        for sid in sids:
            pipe.zscore(ONLINE_ZSET, str(sid))
        scores = pipe.execute()

    offline: List[str] = []
    for sid, score in zip(sids, scores):
        try:
            # score може бути None або float
            if (score is None) or (float(score) <= float(now)):
                offline.append(str(sid))
        except Exception:
            offline.append(str(sid))
    return offline

def _deactivate_sessions(offline_sids: Iterable[str]) -> None:
    """
    Вимикає сесії в БД, пише подію. Також відкликає активні refresh-токени.
    """
    sids = list(offline_sids)
    if not sids:
        return
    with SessionLocal() as db:
        # вимикаємо сесії
        sess_rows = db.query(models.Session).filter(models.Session.id.in_(sids)).all()
        for s in sess_rows:
            if getattr(s, "active", False):
                s.active = False
                s.connected = False
                db.add(models.SessionEvent(session_id=s.id, event="auto_idle_kill"))

        # відкликаємо всі незакриті refresh токени цих сесій (запобігаємо «оживленню»)
        db.query(models.RefreshToken).filter(
            models.RefreshToken.session_id.in_(sids),
            models.RefreshToken.revoked_at.is_(None),
        ).update({"revoked_at": now_utc()}, synchronize_session=False)

        db.commit()
