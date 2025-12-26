# backend/api/v1/admin/__init__.py

from . import (
    ws,
    analytics,
    sessions,
    auth,
    codes,
    events,         # Додано
    admin_users,    # Додано новий роутер
    event_page_admin
)

__all__ = [
    "ws",
    "analytics",
    "sessions",
    "auth",
    "codes",
    "events",
    "admin_users",
    "event_page_admin"
]