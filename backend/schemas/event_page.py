# backend/schemas/event_page.py
from __future__ import annotations
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, Field
from backend.schemas.events import EventOut  # Імпортуємо EventOut

Status = Literal["draft", "published"]

# --- NEW: Конфігурація плеєра та аналітики ---
class MuxDataConfig(BaseModel):
    env_key: str
    metadata: Dict[str, Any]

class PlayerConfig(BaseModel):
    playback_url: str
    tech_order: list[str] = ["html5"]
    poster: Optional[str] = None
    mux: Optional[MuxDataConfig] = None
# ---------------------------------------------

class EventPageUpdate(BaseModel):
    """Вхідна схема для оновлення кастомної сторінки івенту (admin)."""
    page_html: Optional[str] = Field(default="")
    page_css: Optional[str] = Field(default="")
    page_js: Optional[str] = Field(default="")
    runtime_js_version: Optional[str] = Field(default="latest", min_length=1, max_length=32)
    assets_base_url: Optional[str] = Field(default=None, max_length=512)
    status: Optional[Status] = Field(default=None)

class EventPageOut(BaseModel):
    """Вихідна схема для адмінки (отримати вміст сторінки події)."""
    html: str
    css: str
    js: str
    mode: Literal["only-custom"] = "only-custom"
    runtime_js_version: str
    etag: Optional[str] = None
    updated_at: Optional[str] = None

class EventPageResponse(BaseModel):
    """Схема відповіді для КЛІЄНТА (сторінка події)."""
    event: EventOut
    session_id: str
    
    # Готовий контент сторінки
    html: str
    css: str
    js: str
    runtime_js_version: str
    assets_base_url: Optional[str] = None
    
    # --- NEW: Конфіг плеєра ---
    player_config: Optional[PlayerConfig] = None
