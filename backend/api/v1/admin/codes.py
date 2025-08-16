# backend/api/v1/codes.py
"""Адміністративне керування одноразовими access-кодами.

Шляхи (підключай у main.py з префіксом /api/admin/codes):

    POST  /bulk             – створити коди, віддати JSON
    POST  /bulk/csv         – створити коди, одразу віддати CSV-файл
    GET   /                 – перелік кодів (із / або без /)
    GET   /export           – експорт CSV
    POST  /import           – імпорт CSV
    PATCH /{id}             – змінити allowed_sessions / revoked / expires_at
    POST  /{id}/reissue     – згенерувати нове plaintext-значення
    POST  /{id}/force-logout – завершити всі активні сесії коду
    GET   /{id}             – деталі коду
    DELETE /{id}            – видалити код
"""

from __future__ import annotations

import io
import csv
from datetime import datetime, timezone
from typing import Optional

from fastapi import (
    APIRouter, Depends, Query, HTTPException, UploadFile, File, Form, Response
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DB, selectinload
from sqlalchemy import or_

from backend.api.deps import get_db, require_admin_token
from backend import models, schemas
from backend.services.authn.codes import hash_code
from backend.services.repo.access_codes import create_access_codes
from backend.services.ws_service import broadcast, publish_terminate
from backend.services.codegen import generate_unique_code
from backend.services.session_manager import logout as do_logout
from sqlalchemy.exc import IntegrityError


# Допоміжні
def _to_utc_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _batch_label_of(batch_obj) -> Optional[str]:
    if not batch_obj:
        return None
    for cand in ("label", "name", "title"):
        if hasattr(batch_obj, cand):
            return getattr(batch_obj, cand)
    return None


router = APIRouter(
    tags=["admin:codes"],
    dependencies=[Depends(require_admin_token)],  # глобальний guard
)

# ───────────────────────── EXPORT CSV ─────────────────────────
@router.get("/export", response_class=StreamingResponse)
def export_codes_csv(
    db: DB = Depends(get_db),
    q: str | None = Query(None),
    active: str | None = Query(None),
):
    def parse_active(val: str | None) -> bool | None:
        if not val:
            return None
        v = val.lower().strip()
        if v in ("1", "true", "yes", "y", "on"):
            return True
        if v in ("0", "false", "no", "n", "off"):
            return False
        return None

    active_bool = parse_active(active)

    BatchModel = getattr(models, "CodeBatch", None)
    has_batch = bool(BatchModel and hasattr(models.AccessCode, "batch_id"))

    title_col = None
    if has_batch:
        for cand in ("label", "name", "title"):
            if hasattr(BatchModel, cand):
                title_col = getattr(BatchModel, cand)
                break

    if has_batch and title_col is not None:
        qry = (
            db.query(models.AccessCode)
              .outerjoin(BatchModel, models.AccessCode.batch_id == BatchModel.id)
              .add_columns(title_col.label("event_title"))
        )
    else:
        qry = db.query(models.AccessCode)

    if active_bool is not None:
        if hasattr(models.AccessCode, "revoked"):
            qry = qry.filter(models.AccessCode.revoked == (not active_bool))
        elif hasattr(models.AccessCode, "active"):
            qry = qry.filter(models.AccessCode.active == active_bool)

    if q:
        like = f"%{q}%"
        conds = []
        if hasattr(models.AccessCode, "code_plain"):
            conds.append(models.AccessCode.code_plain.ilike(like))
        if has_batch and title_col is not None:
            conds.append(title_col.ilike(like))
        if conds:
            qry = qry.filter(or_(*conds))

    rows = qry.order_by(models.AccessCode.id.desc()).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "code", "event", "max_concurrent_sessions", "active", "created_at", "expires_at"])

    def as_active(c) -> bool:
        if hasattr(c, "revoked"):
            return not bool(getattr(c, "revoked", False))
        return bool(getattr(c, "active", True))

    def max_sess(c) -> int:
        return getattr(c, "max_concurrent_sessions", getattr(c, "allowed_sessions", 1))

    for row in rows:
        if isinstance(row, tuple):
            c, ev = row[0], (row[1] if len(row) > 1 else "")
        else:
            c, ev = row, ""
            try:
                if not hasattr(c, "id") and hasattr(row, "__getitem__"):
                    c = row[0]
                    ev = row[1] if len(row) > 1 else ""
            except Exception:
                pass

        w.writerow([
            c.id,
            getattr(c, "code_plain", "") or "",
            ev or "",
            max_sess(c),
            "1" if as_active(c) else "0",
            getattr(c, "created_at", "") or "",
            getattr(c, "expires_at", "") or "",
        ])

    buf.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="codes_export.csv"'}
    return StreamingResponse(buf, media_type="text/csv", headers=headers)

# ───────────────────────── IMPORT CSV ─────────────────────────
@router.post("/import")
async def import_codes_csv(
    file: UploadFile = File(...),

    # дефолти
    default_sessions: int = Form(1),
    default_active: bool = Form(True),
    default_expires_at: str | None = Form(None),
    event: str | None = Form(None),

    # структура CSV
    has_header: bool = Form(True),
    code_column: str = Form("code"),
    sessions_column: str = Form("max_concurrent_sessions"),
    active_column: str = Form("active"),
    expires_column: str = Form("expires_at"),
    event_column: str = Form("event"),

    # прапорці перезапису
    force_sessions: bool = Form(False),
    force_active: bool = Form(False),
    force_expires: bool = Form(False),
    force_event: bool = Form(False),

    db: DB = Depends(get_db),
    current=Depends(require_admin_token),  # тут треба user.id для generated_by
):
    def parse_bool(val) -> bool | None:
        if val is None:
            return None
        v = str(val).strip().lower()
        if v in ("1", "true", "yes", "y", "on"):
            return True
        if v in ("0", "false", "no", "n", "off"):
            return False
        return None

    def parse_dt_to_utc(val: str | None):
        if not val:
            return None
        v = val.strip()
        try:
            v = v.replace("Z", "").replace("T", " ")
            dt = datetime.fromisoformat(v)
        except Exception:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="ignore")
    f = io.StringIO(text)

    BatchModel = getattr(models, "CodeBatch", None)
    has_batch = bool(BatchModel and hasattr(models.AccessCode, "batch_id"))

    # дістати колонку-лейбл батчу
    batch_label_col = None
    if has_batch:
        for cand in ("label", "name", "title"):
            if hasattr(BatchModel, cand):
                batch_label_col = getattr(BatchModel, cand)
                break

    # get_or_create batch (з попереднім пошуком, щоб не плодити дублікати)
    from functools import lru_cache

    @lru_cache(maxsize=512)
    def get_or_create_batch(lbl: str | None) -> int | None:
        if not (has_batch and lbl):
            return None
        label = lbl.strip()
        if not label:
            return None
        if batch_label_col is None:
            return None
        exists = (
            db.query(BatchModel)
              .filter(batch_label_col == label)
              .first()
        )
        if exists:
            return exists.id
        kwargs = {}
        if hasattr(BatchModel, "label"): kwargs["label"] = label
        elif hasattr(BatchModel, "name"): kwargs["name"] = label
        elif hasattr(BatchModel, "title"): kwargs["title"] = label
        if hasattr(BatchModel, "generated_by"):
            kwargs["generated_by"] = str(getattr(current, "id", "")) or ""
        batch = BatchModel(**kwargs)
        db.add(batch); db.flush()
        return batch.id

    default_exp = parse_dt_to_utc(default_expires_at)
    default_act = bool(default_active)

    rows: list[tuple[str, int, bool, datetime | None, str | None]] = []
    errors: list[dict] = []
    created = 0
    skipped = 0

    try:
        if has_header:
            reader = csv.DictReader(f)
            field_map = {(k or "").strip().lower(): k for k in (reader.fieldnames or [])}
            code_key = field_map.get(code_column.lower())
            sess_key = field_map.get(sessions_column.lower())
            act_key = field_map.get(active_column.lower())
            exp_key = field_map.get(expires_column.lower())
            ev_key = field_map.get(event_column.lower())
            if not code_key:
                return {"ok": False, "detail": f"Column '{code_column}' not found"}

            for i, r in enumerate(reader, start=2):
                code = (r.get(code_key) or "").strip()
                if not code:
                    skipped += 1
                    continue

                if force_sessions:
                    sessions = max(1, default_sessions)
                else:
                    s_raw = (r.get(sess_key) or "").strip() if sess_key else ""
                    try:
                        sessions = int(s_raw) if s_raw else default_sessions
                    except ValueError:
                        sessions = default_sessions
                    sessions = max(1, sessions)

                if force_active:
                    active = default_act
                else:
                    a_parsed = parse_bool((r.get(act_key) or "").strip() if act_key else None)
                    active = default_act if a_parsed is None else a_parsed

                if force_expires:
                    exp = default_exp
                else:
                    exp = parse_dt_to_utc((r.get(exp_key) or "").strip() if exp_key else None) or default_exp

                if force_event:
                    ev_label = (event or "").strip() or None
                else:
                    ev_label = (r.get(ev_key) or "").strip() if ev_key else ""
                    if not ev_label:
                        ev_label = (event or "").strip() or None

                rows.append((code, sessions, active, exp, ev_label))
        else:
            reader = csv.reader(f)
            for i, r in enumerate(reader, start=1):
                if not r:
                    skipped += 1
                    continue
                code = (r[0] or "").strip()
                if not code:
                    skipped += 1
                    continue
                rows.append((code, max(1, default_sessions), default_act, default_exp, (event or "").strip() or None))
    except Exception as e:
        return {"ok": False, "detail": f"CSV parse error: {e}"}

    for idx, (plain, sessions, active, exp, ev_label) in enumerate(rows, start=1):
        try:
            row = models.AccessCode(
                code_plain=plain,
                code_hash=hash_code(plain),
                allowed_sessions=sessions,
                revoked=not active,
                expires_at=exp,
            )
            if has_batch:
                b_id = get_or_create_batch(ev_label)
                if b_id is not None and hasattr(models.AccessCode, "batch_id"):
                    row.batch_id = b_id
            db.add(row); db.flush()
            created += 1
        except IntegrityError:
            db.rollback(); skipped += 1
            errors.append({"line": idx, "code": plain, "reason": "duplicate"})
        except Exception as e:
            db.rollback(); skipped += 1
            errors.append({"line": idx, "code": plain, "reason": str(e)})

    db.commit()
    return {"ok": True, "created": created, "skipped": skipped, "errors": errors}

# ───────────────────────── LIST ─────────────────────────
@router.get("")
@router.get("/")
def list_codes(
    db: DB = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    active: bool | None = None,
):
    BatchModel = getattr(models, "CodeBatch", None)
    has_batch = BatchModel is not None and hasattr(models.AccessCode, "batch_id")

    base = (
        db.query(models.AccessCode)
          .options(
              selectinload(models.AccessCode.allowed_events),
              selectinload(models.AccessCode.batch),
          )
    )

    if active is not None:
        base = base.filter(models.AccessCode.revoked.is_(not active))

    if q:
        like = f"%{q}%"
        if has_batch:
            # фільтр по коду або по batch label|name|title
            conds = [models.AccessCode.code_plain.ilike(like)]
            for cand in ("label", "name", "title"):
                if hasattr(BatchModel, cand):
                    conds.append(getattr(BatchModel, cand).ilike(like))
                    break
            base = base.join(BatchModel, models.AccessCode.batch_id == BatchModel.id, isouter=True).filter(or_(*conds))
        else:
            base = base.filter(models.AccessCode.code_plain.ilike(like))

    total = base.count()
    rows = base.order_by(models.AccessCode.id.desc()).limit(limit).offset(offset).all()

    items = []
    for c in rows:
        items.append({
            "id": c.id,
            "code": c.code_plain,
            "event": _batch_label_of(getattr(c, "batch", None)),  # для сумісності зі старим фронтом
            "batch_label": _batch_label_of(getattr(c, "batch", None)),
            "allow_all_events": bool(getattr(c, "allow_all_events", False)),
            "allowed_event_ids": [ae.event_id for ae in (c.allowed_events or [])],
            "active": not bool(c.revoked),
            "max_concurrent_sessions": getattr(c, "max_concurrent_sessions", c.allowed_sessions),
            "cooldown_seconds": getattr(c, "cooldown_seconds", 0),
            "created_at": c.created_at,
            "updated_at": getattr(c, "updated_at", None),
            "expires_at": getattr(c, "expires_at", None),
        })

    return {"total": total, "items": items}

# ───────────────────────── PATCH ─────────────────────────
@router.patch("/{code_id}")
def patch_code(
    code_id: int,
    data: schemas.AccessCodePatch,
    db: DB = Depends(get_db),
):
    row = db.get(models.AccessCode, code_id)
    if not row:
        raise HTTPException(404, "Code not found")

    if data.allowed_sessions is not None:
        row.allowed_sessions = data.allowed_sessions

    if data.revoked is not None:
        row.revoked = data.revoked
        # відразу гасять активні сесії коду
        db.query(models.Session).filter_by(code_id=code_id, active=True)\
          .update({"active": False, "connected": False}, synchronize_session=False)

    if "expires_at" in data.model_fields_set:
        row.expires_at = _to_utc_aware(data.expires_at) if data.expires_at is not None else None

    db.commit()
    return {"detail": "Updated"}

# ─────────────────────── REISSUE ───────────────────────
@router.post("/{code_id}/reissue")
def reissue_code(
    code_id: int,
    db: DB = Depends(get_db),
):
    row = db.get(models.AccessCode, code_id)
    if not row:
        raise HTTPException(404, "Code not found")

    new_plain = generate_unique_code(db, models.AccessCode, field_name="code_plain")
    row.code_plain = new_plain
    row.code_hash = hash_code(new_plain)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        new_plain = generate_unique_code(db, models.AccessCode, field_name="code_plain")
        row.code_plain = new_plain
        row.code_hash = hash_code(new_plain)
        db.commit()

    return {"code": new_plain}

# ─────────────── Force-logout all sessions for code ───────────────
@router.post("/{code_id}/force-logout")
def force_logout_all(
    code_id: int,
    db: DB = Depends(get_db),
):
    sessions = (
        db.query(models.Session)
          .filter_by(code_id=code_id, active=True)
          .all()
    )
    if not sessions:
        return {"ok": False, "detail": "No active sessions"}

    terminated = 0
    for s in sessions:
        try:
            do_logout(db, s.id)  # централізовано: revoke refresh + event + commit
            publish_terminate(s.id, reason="admin_force_logout")
            terminated += 1
        except Exception:
            pass

    try:
        broadcast({"type": "force_logout_all", "code_id": code_id, "count": terminated})
    except Exception:
        pass

    return {"ok": True, "detail": f"Terminated {terminated} session(s)"}

# ─────────────────────── GET ONE ───────────────────────
@router.get("/{code_id}")
def get_code(
    code_id: int,
    db: DB = Depends(get_db),
):
    c = (
        db.query(models.AccessCode)
          .options(
              selectinload(models.AccessCode.allowed_events),
              selectinload(models.AccessCode.batch),
          )
          .filter(models.AccessCode.id == code_id)
          .first()
    )
    if not c:
        raise HTTPException(404, "not_found")

    return {
        "id": c.id,
        "code": c.code_plain,
        "batch_label": _batch_label_of(getattr(c, "batch", None)),
        "allow_all_events": bool(getattr(c, "allow_all_events", False)),
        "allowed_event_ids": [ae.event_id for ae in (c.allowed_events or [])],
        "active": not bool(c.revoked),
        "max_concurrent_sessions": getattr(c, "max_concurrent_sessions", getattr(c, "allowed_sessions", 1)),
        "cooldown_seconds": getattr(c, "cooldown_seconds", 0),
        "created_at": getattr(c, "created_at", None),
        "updated_at": getattr(c, "updated_at", None),
        "expires_at": getattr(c, "expires_at", None),
    }

# ─────────────────────── DELETE ───────────────────────
@router.delete("/{code_id}", status_code=204)
def delete_code(
    code_id: int,
    db: DB = Depends(get_db),
):
    c = db.get(models.AccessCode, code_id)
    if not c:
        raise HTTPException(404, "not_found")
    db.delete(c)
    db.commit()
    return Response(status_code=204)

# ───────────────────────── Bulk JSON ─────────────────────────
@router.post("/bulk")
def create_codes_json(
    data: schemas.AccessCodeCreate,
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),  # потрібен для batch.generated_by
):
    amount = data.amount
    allowed = data.max_concurrent_sessions or data.allowed_sessions or 1

    codes = create_access_codes(db, amount, allowed)

    # expires_at (UTC-aware або NULL, якщо прийшов явний null)
    exp = _to_utc_aware(getattr(data, "expires_at", None))
    if exp is not None or getattr(data, "expires_at", None) is None:
        db.query(models.AccessCode)\
          .filter(models.AccessCode.code_plain.in_(codes))\
          .update({"expires_at": exp}, synchronize_session=False)
        db.flush()

    # batch (опційно)
    batch_id = None
    BatchModel = getattr(models, "CodeBatch", None)
    if data.event and BatchModel and hasattr(models.AccessCode, "batch_id"):
        batch_kwargs = {}
        if hasattr(BatchModel, "label"): batch_kwargs["label"] = data.event
        elif hasattr(BatchModel, "name"): batch_kwargs["name"] = data.event
        elif hasattr(BatchModel, "title"): batch_kwargs["title"] = data.event
        if hasattr(BatchModel, "generated_by"):
            batch_kwargs["generated_by"] = str(getattr(current, "id", "")) or ""

        batch = BatchModel(**batch_kwargs)
        db.add(batch); db.flush()
        batch_id = batch.id
        db.query(models.AccessCode)\
          .filter(models.AccessCode.code_plain.in_(codes))\
          .update({"batch_id": batch_id}, synchronize_session=False)
        db.flush()

    # cooldown (опційно)
    if getattr(data, "cooldown_seconds", 0) and hasattr(models.AccessCode, "cooldown_seconds"):
        db.query(models.AccessCode)\
          .filter(models.AccessCode.code_plain.in_(codes))\
          .update({"cooldown_seconds": data.cooldown_seconds}, synchronize_session=False)
        db.flush()

    # знайти IDs
    rows = db.query(models.AccessCode.id)\
             .filter(models.AccessCode.code_plain.in_(codes)).all()
    ids = [r[0] if isinstance(r, tuple) else r.id for r in rows]

    # allow_all / event_ids
    allow_all = getattr(data, "allow_all", None)
    event_ids = getattr(data, "event_ids", None) or []

    if allow_all is not None and hasattr(models.AccessCode, "allow_all_events"):
        db.query(models.AccessCode)\
          .filter(models.AccessCode.id.in_(ids))\
          .update({"allow_all_events": bool(allow_all)}, synchronize_session=False)
        db.flush()

    if (not allow_all) and event_ids and hasattr(models, "CodeAllowedEvent"):
        db.query(models.CodeAllowedEvent)\
          .filter(models.CodeAllowedEvent.code_id.in_(ids))\
          .delete(synchronize_session=False)
        db.bulk_save_objects([
            models.CodeAllowedEvent(code_id=cid, event_id=eid)
            for cid in ids for eid in event_ids
        ])
        db.flush()

    db.commit()
    return {"codes": codes, "ids": ids, "batch_id": batch_id}

# ───────────────────────── Bulk CSV ─────────────────────────
@router.post("/bulk/csv", response_class=StreamingResponse)
def create_codes_csv(
    data: schemas.AccessCodeCreate,
    db: DB = Depends(get_db),
    current=Depends(require_admin_token),
):
    amount = data.amount
    allowed = data.max_concurrent_sessions or data.allowed_sessions or 1
    codes = create_access_codes(db, amount, allowed)

    exp = _to_utc_aware(getattr(data, "expires_at", None))
    db.query(models.AccessCode)\
      .filter(models.AccessCode.code_plain.in_(codes))\
      .update({"expires_at": exp}, synchronize_session=False)
    db.commit()

    BatchModel = getattr(models, "CodeBatch", None)
    if data.event and BatchModel and hasattr(models.AccessCode, "batch_id"):
        batch_kwargs = {}
        if hasattr(BatchModel, "label"): batch_kwargs["label"] = data.event
        elif hasattr(BatchModel, "name"): batch_kwargs["name"] = data.event
        elif hasattr(BatchModel, "title"): batch_kwargs["title"] = data.event
        if hasattr(BatchModel, "generated_by"):
            batch_kwargs["generated_by"] = getattr(current, "id", None) or 0

        batch = BatchModel(**batch_kwargs)
        db.add(batch); db.flush()
        db.query(models.AccessCode)\
          .filter(models.AccessCode.code_plain.in_(codes))\
          .update({"batch_id": batch.id}, synchronize_session=False)
        db.commit()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["code"])
    w.writerows([[c] for c in codes])
    buf.seek(0)

    fn = f"codes_{datetime.now():%Y%m%d_%H%M%S}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{fn}"'}
    return StreamingResponse(buf, media_type="text/csv", headers=headers)
