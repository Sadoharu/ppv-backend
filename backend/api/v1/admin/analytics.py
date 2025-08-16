# backend/api/v1/analytics.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from typing import Literal, Optional

from backend.api.deps import get_db, require_admin_token, require_admin
from backend import models, schemas

router = APIRouter(
    tags=["admin:analytics"],
    dependencies=[Depends(require_admin("admin", "super"))],
)

@router.get("/ccu", response_model=list[schemas.CcuPoint])
def get_ccu(
    db: Session = Depends(get_db),
    _current = Depends(require_admin_token),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    limit: int = Query(500, ge=1, le=10000),
    order: Literal["asc","desc"] = Query("asc"),
):
    q = db.query(models.CCUMinutely)
    if since:
        q = q.filter(models.CCUMinutely.ts >= since)
    if until:
        q = q.filter(models.CCUMinutely.ts <= until)

    q = q.order_by(models.CCUMinutely.ts.asc() if order == "asc" else models.CCUMinutely.ts.desc())
    rows = q.limit(limit).all()
    return rows  # працює завдяки from_attributes=True у CcuPoint

@router.get("/codes/{code_id}", response_model=schemas.CodeStats)
def code_stats(
    code_id: int,
    db: Session = Depends(get_db),
    _current = Depends(require_admin_token),
    since: Optional[datetime] = Query(None, description="фільтр за created_at >= since"),
    until: Optional[datetime] = Query(None, description="фільтр за created_at <= until"),
):
    q = db.query(
        func.count(models.Session.id),
        func.coalesce(func.sum(models.Session.watch_seconds), 0),
        func.coalesce(func.sum(models.Session.bytes_out), 0),
    ).filter(models.Session.code_id == code_id)

    if since:
        q = q.filter(models.Session.created_at >= since)
    if until:
        q = q.filter(models.Session.created_at <= until)

    sessions, watch, traffic = q.one()
    return {"code_id": code_id, "sessions": sessions, "watch_seconds": int(watch), "bytes_out": int(traffic)}
