# backend/schemas/events.py
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

ALLOWED = {"none", "html", "sandbox", "safe", "iframe"}
ALIASES = {"safe": "sandbox", "iframe": "html"}

class EventStatus(str, Enum):
    draft = "draft"
    scheduled = "scheduled"
    published = "published"
    live = "live"
    ended = "ended"
    archived = "archived"

class CustomMode(str, Enum):
    none = "none"
    html = "html"
    sandbox = "sandbox"

class EventBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=200)
    status: EventStatus = EventStatus.draft

    # таймінги
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None

    # метадані/прев’ю
    thumbnail_url: Optional[HttpUrl | str] = None
    short_description: Optional[str] = None

    # (опційно) маніфест плеєра: публічний URL або fallback
    player_manifest_url: Optional[str] = None
    
    # --- Стрімінг та Аналітика ---
    # Шлях до відео у Bunny CDN
    bunny_video_path: Optional[str] = Field(default=None, max_length=512)
    # Специфічний ключ середовища Mux Data для цієї події (перекриває глобальний)
    mux_env_key: Optional[str] = Field(default=None, max_length=100)
    # -----------------------------

    # [DEPRECATED] старий механізм
    custom_mode: CustomMode = CustomMode.none
    custom_html: Optional[str] = None
    custom_css: Optional[str] = None
    custom_js: Optional[str] = None

    theme: Optional[str] = None

    # ------- ONLY-CUSTOM PAGE -------
    page_html: str = Field(default="")
    page_css: Optional[str] = Field(default="")
    page_js: Optional[str] = Field(default="")
    runtime_js_version: str = Field(default="latest", min_length=1, max_length=32)
    assets_base_url: Optional[str] = Field(default=None, max_length=512)

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("slug required")
        return s

    @field_validator("title")
    @classmethod
    def normalize_title(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("title required")
        return s

    @field_validator("ends_at")
    @classmethod
    def check_dates(cls, ends: datetime | None, info):
        starts = info.data.get("starts_at")
        if starts and ends and ends < starts:
            raise ValueError("ends_at must be >= starts_at")
        return ends

    @field_validator("custom_mode", mode="before")
    @classmethod
    def normalize_mode(cls, v):
        if v is None:
            return "none"
        s = str(v).strip().lower()
        if s not in ALLOWED:
            raise ValueError("invalid custom_mode")
        return ALIASES.get(s, s)

class EventCreate(EventBase):
    pass

class EventUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    status: Optional[EventStatus] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None

    thumbnail_url: Optional[HttpUrl | str] = None
    short_description: Optional[str] = None
    player_manifest_url: Optional[str] = None
    hls_url: Optional[str] = None  # fallback
    
    # --- NEW ---
    bunny_video_path: Optional[str] = None
    mux_env_key: Optional[str] = None
    # -----------

    custom_mode: Optional[CustomMode] = None
    custom_html: Optional[str] = None
    custom_css: Optional[str] = None
    custom_js: Optional[str] = None

    theme: Optional[str] = None

    page_html: Optional[str] = Field(default=None)
    page_css: Optional[str] = Field(default=None)
    page_js: Optional[str] = Field(default=None)
    runtime_js_version: Optional[str] = Field(default=None, min_length=1, max_length=32)
    assets_base_url: Optional[str] = Field(default=None, max_length=512)

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @field_validator("title")
    @classmethod
    def normalize_title(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @field_validator("ends_at")
    @classmethod
    def check_dates(cls, ends, info):
        starts = info.data.get("starts_at")
        if starts and ends and ends < starts:
            raise ValueError("ends_at must be >= starts_at")
        return ends

    @field_validator("custom_mode", mode="before")
    @classmethod
    def normalize_mode(cls, v):
        if v is None:
            return v
        s = str(v).strip().lower()
        if s not in ALLOWED:
            raise ValueError("invalid custom_mode")
        return ALIASES.get(s, s)

class EventOut(BaseModel):
    id: int
    title: str
    slug: str
    status: EventStatus
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None

    thumbnail_url: Optional[str] = None
    short_description: Optional[str] = None
    player_manifest_url: Optional[str] = None
    
    # --- NEW ---
    bunny_video_path: Optional[str] = None
    mux_env_key: Optional[str] = None
    # -----------

    custom_mode: CustomMode
    custom_html: Optional[str] = None
    custom_css: Optional[str] = None
    custom_js: Optional[str] = None

    theme: Optional[str] = None

    # Only-custom fields
    page_html: str
    page_css: Optional[str] = None
    page_js: Optional[str] = None
    runtime_js_version: str
    assets_base_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class EventOutShort(BaseModel):
    id: int
    title: str
    slug: str
    status: EventStatus
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    thumbnail_url: Optional[str] = None
    short_description: Optional[str] = None
    player_manifest_url: Optional[str] = None
    custom_mode: CustomMode

    model_config = ConfigDict(from_attributes=True)