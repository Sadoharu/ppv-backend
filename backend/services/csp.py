# backend/services/csp.py
from __future__ import annotations
import secrets
from typing import Dict, Iterable, List, Optional, Union

__all__ = ["gen_nonce", "build_csp_headers"]

SrcList = Union[str, Iterable[str]]

def gen_nonce(length: int = 16) -> str:
    """Генерує URL-safe nonce для CSP."""
    return secrets.token_urlsafe(length)

def _join(srcs: SrcList) -> str:
    if isinstance(srcs, str):
        return srcs
    return " ".join(srcs)

def build_csp_headers(
    mode: str,
    nonce: str,
    *,
    frame_ancestors: Optional[SrcList] = "none",
    connect_src_extra: Optional[List[str]] = None,
    img_src_extra: Optional[List[str]] = None,
    media_src_extra: Optional[List[str]] = None,
    font_src_extra: Optional[List[str]] = None,
    script_src_extra: Optional[List[str]] = None,
    style_src_extra: Optional[List[str]] = None,
) -> Dict[str, str]:
    """
    Повертає dict заголовків CSP залежно від режиму.
    - mode='sandbox'  → максимально строго (рекомендовано за замовчуванням).
    - mode='html'     → трохи ліберальніше (але БЕЗ unsafe-inline/unsafe-eval).
    Усі inline <style>/<script> мають йти з nonce.
    """

    # Базові джерела
    default_src = ["'self'", "https:"]
    # Дозволяємо XHR/WebSocket до self/https
    connect_src = ["'self'", "https:", "wss:"]
    if connect_src_extra:
        connect_src.extend(connect_src_extra)

    # Картинки/шрифти/медіа — стандартно self/https, img також data: (іконки)
    img_src = ["'self'", "https:", "data:"]
    if img_src_extra:
        img_src.extend(img_src_extra)

    media_src = ["'self'", "https:"]
    if media_src_extra:
        media_src.extend(media_src_extra)

    font_src = ["'self'", "https:", "data:"]
    if font_src_extra:
        font_src.extend(font_src_extra)

    # Скрипти/стилі — тільки по nonce; strict-dynamic дозволяє підвантажені скрипти довіреним лоадером
    script_src = [f"'nonce-{nonce}'", "'self'", "https:", "'strict-dynamic'"]
    style_src  = [f"'nonce-{nonce}'", "'self'", "https:"]

    if script_src_extra:
        script_src.extend(script_src_extra)
    if style_src_extra:
        style_src.extend(style_src_extra)

    # Різниця між режимами мінімальна; sandbox=строгішій default-src
    if mode not in {"sandbox", "html"}:
        mode = "sandbox"

    # Керуємо фреймами: за замовчуванням забороняємо вбудовувати нашу сторінку
    if frame_ancestors is None:
        fa = "none"
    else:
        fa = _join(frame_ancestors) if not isinstance(frame_ancestors, str) else frame_ancestors
    frame_ancestors_str = f"frame-ancestors '{fa}';" if fa != "none" else "frame-ancestors 'none';"

    csp = (
        f"default-src {_join(default_src)}; "
        f"script-src {_join(script_src)}; "
        f"style-src {_join(style_src)}; "
        f"img-src {_join(img_src)}; "
        f"font-src {_join(font_src)}; "
        f"connect-src {_join(connect_src)}; "
        f"media-src {_join(media_src)}; "
        f"{frame_ancestors_str}"
    )

    return {"Content-Security-Policy": csp}
