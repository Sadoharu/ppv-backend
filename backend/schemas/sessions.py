# backend/schemas/sessions.py
from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict

class SessionOut(BaseModel):
    id: str
    code_id: int
    code: Optional[str] = None
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    active: bool
    connected: Optional[bool] = None
    watch_seconds: int = 0
    bytes_out: int = 0
    created_at: datetime
    last_seen: datetime
    model_config = ConfigDict(from_attributes=True)

class BulkDeleteSessions(BaseModel):
    session_ids: List[str]