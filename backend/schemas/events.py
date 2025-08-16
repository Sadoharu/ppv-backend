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
    published = "published"   # ← є в БД, щоб не ловити validation error
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
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    thumbnail_url: Optional[HttpUrl | str] = None  # дозволяємо й plain str
    short_description: Optional[str] = None
    player_manifest_url: Optional[str] = None
    custom_mode: CustomMode = CustomMode.none
    custom_html: Optional[str] = None
    custom_css: Optional[str] = None
    custom_js: Optional[str] = None
    theme: Optional[str] = None

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
    hls_url: Optional[str] = None  # fallback для старих клієнтів
    custom_mode: Optional[CustomMode] = None
    custom_html: Optional[str] = None
    custom_css: Optional[str] = None
    custom_js: Optional[str] = None
    theme: Optional[str] = None

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
    custom_mode: CustomMode
    # повна версія:
    custom_html: Optional[str] = None
    custom_css: Optional[str] = None
    custom_js: Optional[str] = None
    theme: Optional[str] = None

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
