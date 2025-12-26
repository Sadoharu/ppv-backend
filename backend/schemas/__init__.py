# backend/schemas/__init__.py
from __future__ import annotations
from datetime import datetime
from typing import Generic, TypeVar, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, constr, conint, Field

# ───── загальні схеми ─────

class LoginRequest(BaseModel):
    code: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

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

class SessionOut(BaseModel):
    id: str
    code_id: int
    code: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    active: bool
    connected: bool | None = None
    watch_seconds: int = 0
    bytes_out: int = 0
    created_at: datetime
    last_seen: datetime
    model_config = ConfigDict(from_attributes=True)

class CcuPoint(BaseModel):
    ts: datetime
    ccu: int
    model_config = ConfigDict(from_attributes=True)

class CodeStats(BaseModel):
    code_id: int
    sessions: int
    watch_seconds: int
    bytes_out: int

class AdminLogin(BaseModel):
    email: EmailStr
    password: constr(min_length=6)

class AdminToken(BaseModel):
    access_token: str

T = TypeVar("T")

class Page(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: List[T] = Field(default_factory=list)
    model_config = ConfigDict(arbitrary_types_allowed=True)

class BulkDeleteCodes(BaseModel):
    codes: list[str]

class BulkDeleteSessions(BaseModel):
    session_ids: list[str]

# ───── події (реекспорт) ─────
from .events import (
    EventStatus,
    CustomMode,
    EventCreate,
    EventUpdate,
    EventOut,
    EventOutShort,
)

# ───── only-custom pages (адмін) ─────
from .event_page import (
    EventPageUpdate,
    EventPageOut,
)