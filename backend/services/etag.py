# backend/services/etag.py
from __future__ import annotations
import hashlib
from typing import Any, Iterable, Optional
from datetime import datetime

__all__ = [
    "calc_event_etag",
    "calc_payload_etag",
    "not_modified",
    "set_etag_header",
]

def _to_bytes(x: Any) -> bytes:
    if x is None:
        return b""
    if isinstance(x, bytes):
        return x
    if isinstance(x, (int, float, bool)):
        return str(x).encode("utf-8")
    if isinstance(x, datetime):
        # ISO з таймзоною, щоб детерміновано
        return x.isoformat().encode("utf-8")
    return str(x).encode("utf-8")

def calc_payload_etag(*parts: Any) -> str:
    """
    Обчислює стабільний ETag по набору частин.
    Повертає 40-символьний префікс SHA-256 (opaque strong ETag).
    """
    h = hashlib.sha256()
    sep = b"|"
    for p in parts:
        h.update(_to_bytes(p))
        h.update(sep)
    return h.hexdigest()[:40]

def calc_event_etag(
    event_id: int,
    updated_at: Optional[datetime],
    status: str,
    html: Optional[str],
    css: Optional[str],
    js: Optional[str],
) -> str:
    """
    ETag для сторінки івенту: чутливий до id, оновлення, статусу і вмісту.
    (довжини — достатній проксі, щоб не возити весь текст у геш)
    """
    return calc_payload_etag(
        event_id,
        updated_at or "",
        status or "",
        len(html or ""),
        len(css or ""),
        len(js or ""),
    )

def not_modified(incoming_if_none_match: Optional[str], current_etag: Optional[str]) -> bool:
    """
    Перевіряє, чи збігається If-None-Match з нашим ETag (без лапок).
    Якщо клієнт прислав формат із лапками W/ то знімаємо їх грубо.
    """
    if not incoming_if_none_match or not current_etag:
        return False
    inm = incoming_if_none_match.strip().strip('W/').strip('"').strip()
    return inm == current_etag.strip().strip('"')

def set_etag_header(headers: dict, etag: str) -> dict:
    """Проставляє ETag у словник заголовків (без лапок)."""
    headers["ETag"] = etag
    return headers
