# backend/schemas/access_codes.py
from __future__ import annotations
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, conint, Field

class AccessCodeOut(BaseModel):
    id: int
    code: str
    allowed_sessions: int
    active_sessions: int
    revoked: bool
    created_at: datetime
    batch_label: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class AccessCodeCreate(BaseModel):
    amount: conint(ge=1, le=10000)
    allowed_sessions: int | None = None
    max_concurrent_sessions: int | None = None
    cooldown_seconds: int = 0
    event: str | None = None
    expires_at: datetime | None = None
    allow_all: Optional[bool] = None
    event_ids: Optional[List[int]] = None

class AccessCodePatch(BaseModel):
    allowed_sessions: int | None = None
    revoked: bool | None = None
    expires_at: datetime | None = None

class BulkDeleteCodes(BaseModel):
    codes: list[str]