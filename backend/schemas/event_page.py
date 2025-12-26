# backend/schemas/event_page.py
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field

Status = Literal["draft", "published"]

class EventPageUpdate(BaseModel):
    """Вхідна схема для оновлення кастомної сторінки івенту (admin)."""
    page_html: Optional[str] = Field(default="")
    page_css: Optional[str] = Field(default="")
    page_js: Optional[str] = Field(default="")
    runtime_js_version: Optional[str] = Field(default="latest", min_length=1, max_length=32)
    assets_base_url: Optional[str] = Field(default=None, max_length=512)
    # статус міняємо окремими ендпоїнтами /publish /unpublish, але дозволяємо і тут якщо треба
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
