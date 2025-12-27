# backend/api/v1/delete/codes.py
# backend\api\v1\codes.py
"""Адміністративне керування одноразовими access-кодами.

Шляхи (усі під префіксом **/admin/codes**):

    POST  /bulk            – створити коди, JSON-масив plaintext-значень
    POST  /bulk/csv        – створити коди, одразу віддати CSV-файл
    GET   /                – перелік усіх кодів (із / або без /)
    PATCH /{id}            – змінити allowed_sessions / revoked
    POST  /{id}/reissue    – згенерувати нове plaintext-значення
    POST  /{id}/force-logout – завершити всі активні сесії коду
"""

from __future__ import annotations

import io, csv, secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm import Session as DB
from sqlalchemy.exc import IntegrityError

from backend.api.deps import get_db, require_admin_token
from backend import models, schemas
from backend.services.authn.codes import hash_code
from backend.services.repo.access_codes import create_access_codes
from backend.services.ws_service import broadcast, get_client_ws
from backend.services.codegen import generate_unique_code

def _batch_title(b) -> str | None:
    # підхоплюємо можливі назви поля в CodeBatch
    return getattr(b, "label", None) or getattr(b, "name", None) or getattr(b, "title", None)

from sqlalchemy.orm import joinedload


def _to_utc_aware(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)



router = APIRouter(prefix="/api/admin/codes", tags=["codes"])

@router.get("/export", response_class=StreamingResponse)
def export_codes_csv(
    current=Depends(require_admin_token),
    db: DB = Depends(get_db),
    q: str | None = Query(None),
    active: str | None = Query(None),
):
    def parse_active(val: str | None) -> bool | None:
        if not val: return None
        v = val.lower().strip()
        if v in ("1","true","yes","y","on"):  return True
        if v in ("0","false","no","n","off"): return False
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
        # гарантовано повертаємо (AccessCode, event_title)
        qry = (
            db.query(models.AccessCode)
            .outerjoin(BatchModel, models.AccessCode.batch_id == BatchModel.id)
            .add_columns(title_col.label("event_title"))
        )
    else:
        # повертаємо сам AccessCode
        qry = db.query(models.AccessCode)

    # ── фільтри
    if active_bool is not None:
        if hasattr(models.AccessCode, "revoked"):
            qry = qry.filter(models.AccessCode.revoked == (not active_bool))
        elif hasattr(models.AccessCode, "active"):
            qry = qry.filter(models.AccessCode.active == active_bool)

    if q:
        from sqlalchemy import or_
        like = f"%{q}%"
        conds = []
        if hasattr(models.AccessCode, "code_plain"):
            conds.append(models.AccessCode.code_plain.ilike(like))
        if has_batch and title_col is not None:
            conds.append(title_col.ilike(like))
        if conds:
            qry = qry.filter(or_(*conds))

    rows = qry.order_by(models.AccessCode.id.desc()).all()

    # ── CSV
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
        # нормалізуємо до (AccessCode, event_title)
        if isinstance(row, tuple):
            c, ev = row[0], (row[1] if len(row) > 1 else "")
        else:
            # може бути або сам ORM-екземпляр, або Row з позиційним доступом
            c = row
            ev = ""
            # іноді це sqlalchemy.engine.Row -> маємо позиційний доступ
            try:
                # якщо це Row (має __getitem__)
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

@router.post("/import")
async def import_codes_csv(
    file: UploadFile = File(...),

    # дефолти (коли в рядку/колонці немає значення)
    default_sessions: int = Form(1),
    default_active: bool = Form(True),
    default_expires_at: str | None = Form(None),   # ISO або "YYYY-MM-DD HH:MM"
    event: str | None = Form(None),                # глобальний fallback-івент (batch label)

    # структура CSV (імена колонок — як в експорті)
    has_header: bool = Form(True),
    code_column: str = Form("code"),
    sessions_column: str = Form("max_concurrent_sessions"),
    active_column: str = Form("active"),
    expires_column: str = Form("expires_at"),
    event_column: str = Form("event"),

    # ПРАПОРЦІ ПЕРЕЗАПИСУ (форма має пріоритет над CSV)
    force_sessions: bool = Form(False),
    force_active: bool = Form(False),
    force_expires: bool = Form(False),
    force_event: bool = Form(False),

    current=Depends(require_admin_token),
    db: Session = Depends(get_db),
):
    """Імпорт CSV, сумісний з експортом.
       Колонки: id, code, event, max_concurrent_sessions, active, created_at, expires_at
       Поля id/created_at ігноруємо. Поля з форми можуть перезаписувати значення з CSV (force_*).
    """
    import csv, io
    from sqlalchemy.exc import IntegrityError
    from datetime import datetime, timezone

    def parse_bool(val) -> bool | None:
        if val is None:
            return None
        v = str(val).strip().lower()
        if v in ("1","true","yes","y","on"):  return True
        if v in ("0","false","no","n","off"): return False
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
    batch_cache: dict[str, int] = {}

    def get_or_create_batch(label: str | None) -> int | None:
        if not (has_batch and label):
            return None
        lbl = label.strip()
        if not lbl:
            return None
        if lbl in batch_cache:
            return batch_cache[lbl]
        kwargs = {}
        if hasattr(BatchModel, "label"): kwargs["label"] = lbl
        elif hasattr(BatchModel, "name"): kwargs["name"] = lbl
        elif hasattr(BatchModel, "title"): kwargs["title"] = lbl
        if hasattr(BatchModel, "generated_by"):
            kwargs["generated_by"] = str(getattr(current, "id", "")) or ""
        batch = BatchModel(**kwargs)
        db.add(batch); db.flush()
        batch_cache[lbl] = batch.id
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
            field_map = { (k or "").strip().lower(): k for k in (reader.fieldnames or []) }
            code_key = field_map.get(code_column.lower())
            sess_key = field_map.get(sessions_column.lower())
            act_key  = field_map.get(active_column.lower())
            exp_key  = field_map.get(expires_column.lower())
            ev_key   = field_map.get(event_column.lower())
            if not code_key:
                return {"ok": False, "detail": f"Column '{code_column}' not found"}

            for i, r in enumerate(reader, start=2):
                code = (r.get(code_key) or "").strip()
                if not code:
                    skipped += 1
                    continue

                # sessions
                if force_sessions:
                    sessions = max(1, default_sessions)
                else:
                    s_raw = (r.get(sess_key) or "").strip() if sess_key else ""
                    try:
                        sessions = int(s_raw) if s_raw else default_sessions
                    except ValueError:
                        sessions = default_sessions
                    sessions = max(1, sessions)

                # active
                if force_active:
                    active = default_act
                else:
                    a_parsed = parse_bool((r.get(act_key) or "").strip() if act_key else None)
                    active = default_act if a_parsed is None else a_parsed

                # expires_at
                if force_expires:
                    exp = default_exp
                else:
                    exp = parse_dt_to_utc((r.get(exp_key) or "").strip() if exp_key else None)
                    if exp is None:
                        exp = default_exp

                # event
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
                rows.append((
                    code,
                    max(1, default_sessions),
                    default_act,
                    default_exp,
                    (event or "").strip() or None
                ))
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

@router.get("")
@router.get("/")
def list_codes(
    current=Depends(require_admin_token),
    db: DB = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    active: bool | None = None,
):
    BatchModel = getattr(models, "CodeBatch", None)
    has_batch = BatchModel is not None and hasattr(models.AccessCode, "batch_id")

    # колонка з назвою батчу
    batch_label_col = None
    if has_batch:
        for cand in ("label", "name", "title"):
            if hasattr(BatchModel, cand):
                batch_label_col = getattr(BatchModel, cand)
                break

    # підвантажуємо allowed_events одним запитом
    base_q = db.query(models.AccessCode).options(
        joinedload(models.AccessCode.allowed_events)
    )

    if has_batch and batch_label_col is not None:
        qry = (
            base_q
            .outerjoin(BatchModel, models.AccessCode.batch_id == BatchModel.id)
            .add_columns(batch_label_col.label("batch_label"))
        )
    else:
        qry = base_q

    if active is not None:
        qry = qry.filter(models.AccessCode.revoked.is_(not active))

    if q:
        from sqlalchemy import or_
        like = f"%{q}%"
        conds = [models.AccessCode.code_plain.ilike(like)]
        if has_batch and batch_label_col is not None:
            conds.append(batch_label_col.ilike(like))
        qry = qry.filter(or_(*conds))

    total = qry.count()
    rows = (
        qry.order_by(models.AccessCode.id.desc())
           .limit(limit).offset(offset).all()
    )

    items = []
    if has_batch and batch_label_col is not None:
        for c, batch_label in rows:
            items.append({
                "id": c.id,
                "code": c.code_plain,
                "event": batch_label or None,      # для сумісності зі старим фронтом
                "batch_label": batch_label or None,
                "allow_all_events": bool(getattr(c, "allow_all_events", False)),
                "allowed_event_ids": [ae.event_id for ae in (c.allowed_events or [])],
                "active": not bool(c.revoked),
                "max_concurrent_sessions": getattr(c, "max_concurrent_sessions", c.allowed_sessions),
                "cooldown_seconds": getattr(c, "cooldown_seconds", 0),
                "created_at": c.created_at,
                "updated_at": getattr(c, "updated_at", None),
                "expires_at": getattr(c, "expires_at", None),
            })
    else:
        for c in rows:
            items.append({
                "id": c.id,
                "code": c.code_plain,
                "event": None,
                "batch_label": None,
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



@router.patch("/{code_id}")
def patch_code(code_id: int, data: schemas.AccessCodePatch, db: Session = Depends(get_db)):
    row = db.query(models.AccessCode).get(code_id)
    if not row:
        raise HTTPException(404, "Code not found")

    if data.allowed_sessions is not None:
        row.allowed_sessions = data.allowed_sessions

    if data.revoked is not None:
        row.revoked = data.revoked
        db.query(models.Session).filter_by(code_id=code_id, active=True)\
            .update({"active": False, "connected": False}, synchronize_session=False)

    if "expires_at" in data.model_fields_set:
        row.expires_at = _to_utc_aware(data.expires_at) if data.expires_at is not None else None

    db.commit()
    return {"detail": "Updated"}


@router.post("/{code_id}/reissue")
def reissue_code(code_id: int, db: Session = Depends(get_db), current=Depends(require_admin_token)):
    row = db.query(models.AccessCode).get(code_id)
    if not row:
        raise HTTPException(404, "Code not found")

    # генеруємо уніфіковано і унікально
    new_plain = generate_unique_code(db, models.AccessCode, field_name="code_plain")
    row.code_plain = new_plain
    row.code_hash  = hash_code(new_plain)

    # на випадок дуже рідкісної колізії — перегенерувати і повторити
    from sqlalchemy.exc import IntegrityError
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        new_plain = generate_unique_code(db, models.AccessCode, field_name="code_plain")
        row.code_plain = new_plain
        row.code_hash  = hash_code(new_plain)
        db.commit()

    return {"code": new_plain}

# ───────────────────────── Force-logout all sessions ────────────────
@router.post("/{code_id}/force-logout")
async def force_logout_all(code_id: int, db: Session = Depends(get_db)):
    ids = [
        s.id for s in db.query(models.Session)
                     .filter_by(code_id=code_id, active=True)
                     .all()
    ]
    if not ids:
        return {"ok": False, "detail": "No active sessions"}
    
    db.query(models.Session)\
      .filter(models.Session.id.in_(ids))\
      .update({"active": False, "connected": False}, synchronize_session=False)
    db.commit()

    closed = 0
    for sid in ids:
        if (ws := get_client_ws(sid)):
            await ws.close(code=4000, reason="terminated")
            closed += 1

    broadcast({"type": "force_logout_all", "code_id": code_id})
    return {"ok": True, "detail": f"Terminated {len(ids)} session(s), closed {closed} WS"}

@router.get("/{code_id}")
def get_code(code_id: int,
             current=Depends(require_admin_token),
             db: DB = Depends(get_db)):
    # підвантажуємо allowed_events і batch
    q = db.query(models.AccessCode).options(
        joinedload(models.AccessCode.allowed_events)
    )
    BatchModel = getattr(models, "CodeBatch", None)
    has_batch = BatchModel is not None and hasattr(models.AccessCode, "batch_id")
    batch_label = None
    if has_batch:
        # забираємо батч окремо, щоб витягти його label|name|title
        c = q.get(code_id)
        if not c:
            raise HTTPException(404, "not_found")
        b = getattr(c, "batch", None)
        if b is not None:
            for cand in ("label", "name", "title"):
                if hasattr(b, cand):
                    batch_label = getattr(b, cand)
                    break
    else:
        c = q.get(code_id)
        if not c:
            raise HTTPException(404, "not_found")

    return {
        "id": c.id,
        "code": c.code_plain,
        "batch_label": batch_label,
        "allow_all_events": bool(getattr(c, "allow_all_events", False)),
        "allowed_event_ids": [ae.event_id for ae in (c.allowed_events or [])],
        "active": not bool(c.revoked),
        "max_concurrent_sessions": getattr(c, "max_concurrent_sessions", getattr(c, "allowed_sessions", 1)),
        "cooldown_seconds": getattr(c, "cooldown_seconds", 0),
        "created_at": getattr(c, "created_at", None),
        "updated_at": getattr(c, "updated_at", None),
        "expires_at": getattr(c, "expires_at", None),
    }


@router.delete("/{code_id}", status_code=204)
def delete_code(code_id: int,
                current=Depends(require_admin_token),
                db: DB = Depends(get_db)):
    c = db.get(models.AccessCode, code_id)
    if not c:
        raise HTTPException(404, "not_found")
    db.delete(c)
    db.commit()
    return {"ok": True}

# ───────────────────────── Bulk JSON ────────────────────────────────
@router.post("/bulk")
@router.post("/bulk")
def create_codes_json(
    data: schemas.AccessCodeCreate,
    db: Session = Depends(get_db),
    current=Depends(require_admin_token),
):
    amount = data.amount
    allowed = data.max_concurrent_sessions or data.allowed_sessions or 1

    codes = create_access_codes(db, amount, allowed)

    # --- expires_at: оновлюємо ОДИН раз, у UTC-aware ---
    exp = _to_utc_aware(getattr(data, "expires_at", None))
    if exp is not None or getattr(data, "expires_at", None) is None:
        # Якщо явно прийшов null — теж застосовуємо (ставимо NULL)
        db.query(models.AccessCode)\
          .filter(models.AccessCode.code_plain.in_(codes))\
          .update({"expires_at": exp}, synchronize_session=False)
        db.flush()

    # --- batch (опційно) ---
    batch_id = None  # <— ВАЖЛИВО: ініціалізуємо
    BatchModel = getattr(models, "CodeBatch", None)
    if data.event and BatchModel and hasattr(models.AccessCode, "batch_id"):
        batch_kwargs = {}

        # назва / лейбл
        if hasattr(BatchModel, "label"):
            batch_kwargs["label"] = data.event
        elif hasattr(BatchModel, "name"):
            batch_kwargs["name"] = data.event
        elif hasattr(BatchModel, "title"):
            batch_kwargs["title"] = data.event

        # хто згенерував
        if hasattr(BatchModel, "generated_by"):
            batch_kwargs["generated_by"] = str(getattr(current, "id", "")) or ""

        batch = BatchModel(**batch_kwargs)
        db.add(batch)
        db.flush()                    # щоб мати batch.id до коміту
        batch_id = batch.id

        db.query(models.AccessCode)\
          .filter(models.AccessCode.code_plain.in_(codes))\
          .update({"batch_id": batch_id}, synchronize_session=False)
        db.flush()

    # --- cooldown (опційно) ---
    if getattr(data, "cooldown_seconds", 0) and hasattr(models.AccessCode, "cooldown_seconds"):
        db.query(models.AccessCode)\
          .filter(models.AccessCode.code_plain.in_(codes))\
          .update({"cooldown_seconds": data.cooldown_seconds}, synchronize_session=False)
        db.flush()

    # --- знайти IDs новостворених кодів ---
    rows = db.query(models.AccessCode.id)\
             .filter(models.AccessCode.code_plain.in_(codes))\
             .all()
    ids = [r[0] if isinstance(r, tuple) else r.id for r in rows]

    # --- allow_all / event_ids (опційно) ---
    allow_all = getattr(data, "allow_all", None)
    event_ids = getattr(data, "event_ids", None) or []

    if allow_all is not None and hasattr(models.AccessCode, "allow_all_events"):
        db.query(models.AccessCode)\
          .filter(models.AccessCode.id.in_(ids))\
          .update({"allow_all_events": bool(allow_all)}, synchronize_session=False)
        db.flush()

    if (not allow_all) and event_ids and hasattr(models, "CodeAllowedEvent"):
        # Стерти старі й додати нові дозволи
        db.query(models.CodeAllowedEvent)\
          .filter(models.CodeAllowedEvent.code_id.in_(ids))\
          .delete(synchronize_session=False)
        db.bulk_save_objects([
            models.CodeAllowedEvent(code_id=cid, event_id=eid)
            for cid in ids for eid in event_ids
        ])
        db.flush()

    db.commit()

    # Повертаємо batch_id ТІЛЬКИ якщо він є (None також ок, якщо контракт дозволяє)
    return {"codes": codes, "ids": ids, "batch_id": batch_id}



@router.post("/bulk/csv", response_class=StreamingResponse)
def create_codes_csv(
    data: schemas.AccessCodeCreate,
    db: Session = Depends(get_db),
    current=Depends(require_admin_token),  # ← додаємо
):
    amount = data.amount
    allowed = data.max_concurrent_sessions or data.allowed_sessions or 1

    codes = create_access_codes(db, amount, allowed)

    exp = _to_utc_aware(getattr(data, "expires_at", None))
    if exp is not None:
        db.query(models.AccessCode)\
          .filter(models.AccessCode.code_plain.in_(codes))\
          .update({"expires_at": exp}, synchronize_session=False)
        db.commit()

    if getattr(data, "expires_at", None):
        db.query(models.AccessCode)\
          .filter(models.AccessCode.code_plain.in_(codes))\
          .update({"expires_at": data.expires_at}, synchronize_session=False)
        db.commit()

    BatchModel = getattr(models, "CodeBatch", None)
    if data.event and BatchModel and hasattr(models.AccessCode, "batch_id"):
        batch_kwargs = {}
        if hasattr(BatchModel, "label"):
            batch_kwargs["label"] = data.event
        elif hasattr(BatchModel, "name"):
            batch_kwargs["name"] = data.event
        elif hasattr(BatchModel, "title"):
            batch_kwargs["title"] = data.event

        if hasattr(BatchModel, "generated_by"):
            batch_kwargs["generated_by"] = getattr(current, "id", None) or 0

        batch = BatchModel(**batch_kwargs)
        db.add(batch)
        db.flush()

        db.query(models.AccessCode)\
          .filter(models.AccessCode.code_plain.in_(codes))\
          .update({"batch_id": batch.id}, synchronize_session=False)
        db.commit()

    # CSV
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["code"])
    w.writerows([[c] for c in codes])
    buf.seek(0)

    fn = f"codes_{datetime.now():%Y%m%d_%H%M%S}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{fn}"'}
    return StreamingResponse(buf, media_type="text/csv", headers=headers)






