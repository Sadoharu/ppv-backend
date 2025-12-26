# backend/services/sanitizer.py
from __future__ import annotations
import re
from typing import Optional

try:
    import bleach  # опційно: якщо встановлено, можемо задіяти allowlist-санітизацію
except Exception:  # pragma: no cover
    bleach = None  # type: ignore[assignment]

__all__ = [
    "strip_scripts_and_inline_handlers",
    "sanitize_html",
    "has_inline_event_handlers",
]

# Вирізати <script>...</script>
_SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
# Вирізати on*="" атрибути: onload, onclick, onerror, ...
_ON_ATTR_RE = re.compile(r"\s(on[a-z0-9_-]+)\s*=\s*(\".*?\"|'.*?'|[^\s>]+)", re.IGNORECASE | re.DOTALL)

def strip_scripts_and_inline_handlers(html: Optional[str]) -> str:
    """
    Мінімально-безпечна санація:
    - повністю вирізає <script>...</script>
    - видаляє інлайн-обробники подій (on*)
    НЕ чіпає інший HTML. Придатно для режиму з CSP nonce та окремим user.js.
    """
    if not html:
        return ""
    no_scripts = _SCRIPT_TAG_RE.sub("", html)
    # Забираємо ВСІ on* атрибути; це жорстко, але безпечно
    cleaned = _ON_ATTR_RE.sub("", no_scripts)
    return cleaned

def has_inline_event_handlers(html: Optional[str]) -> bool:
    """Чи містить html інлайн on* атрибути (для діагностики/логів адмінці)."""
    if not html:
        return False
    return bool(_ON_ATTR_RE.search(html))

def sanitize_html(
    html: Optional[str],
    mode: str = "strict",
    allow_basic_formatting: bool = True,
) -> str:
    """
    Розширена санація:
    - mode="strict": застосовує strip_scripts_and_inline_handlers (без зовнішніх залежностей).
    - mode="bleach": якщо є bleach — робить allowlist-санітизацію (і ТЕЖ вирізає <script>/on*).
    Порада: для редактора сторінок достатньо mode="strict" + CSP nonce.
    """
    base = strip_scripts_and_inline_handlers(html)

    if mode == "bleach" and bleach:
        # Мінімальний дозволений набір тегів/атрибутів (безопасно для лендінгів)
        allowed_tags = [
            "a", "abbr", "b", "blockquote", "br", "code", "div", "em", "figure", "figcaption",
            "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p", "pre", "span",
            "strong", "sub", "sup", "table", "thead", "tbody", "tr", "th", "td", "u", "ul",
            "section", "header", "footer", "nav", "main", "article"
        ]
        if not allow_basic_formatting:
            allowed_tags = ["div", "span"]  # максимально жорстко

        allowed_attrs = {
            "*": ["class", "id", "title", "aria-*", "role", "data-*", "style"],  # style ок, але CSP заборонить inline якщо без nonce
            "a": ["href", "target", "rel"],
            "img": ["src", "alt", "width", "height", "loading", "decoding"],
            "table": ["border", "cellpadding", "cellspacing"],
            "td": ["colspan", "rowspan"],
            "th": ["colspan", "rowspan", "scope"],
        }

        # sanitize; уникаємо перетворення в XHTML
        cleaned = bleach.clean(
            base,
            tags=allowed_tags,
            attributes=allowed_attrs,
            protocols=["http", "https", "mailto", "tel", "data"],
            strip=True,
            strip_comments=True,
        )
        return cleaned

    return base
