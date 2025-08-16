# backend\api\v1\client\custom_render.py
from fastapi import APIRouter, Depends, Response, HTTPException
from sqlalchemy.orm import Session as DB
from backend.database import get_db
from backend import models
import secrets

router = APIRouter(prefix="/events", tags=["public:custom"])  # фінально: /api/events/...

PUBLIC_STATUSES = {"scheduled", "published", "live", "ended"}
ALLOWED_CUSTOM_MODES = {"html", "sandbox"}  # якщо у тебе в БД лиш "html" — залиш {"html"}

@router.get("/{event_id}/custom", response_class=Response)
def custom_event(event_id: int, db: DB = Depends(get_db)):
    e = db.get(models.Event, event_id)
    if not e:
        raise HTTPException(404, "not_found")

    if e.status not in PUBLIC_STATUSES:
        raise HTTPException(404, "not_found")

    if (e.custom_mode or "none") not in ALLOWED_CUSTOM_MODES:
        raise HTTPException(404, "not_found")

    nonce = secrets.token_urlsafe(16)

    csp = (
        "default-src 'none'; "
        "base-uri 'none'; "
        "form-action 'none'; "
        f"style-src 'nonce-{nonce}'; "
        f"script-src 'nonce-{nonce}'; "
        "img-src 'self' https: data:; "
        "font-src 'self' https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "upgrade-insecure-requests"
    )

    headers = {
        "Content-Security-Policy": csp,
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style nonce="{nonce}">
{e.custom_css or ""}
  </style>
</head>
<body>
{e.custom_html or ""}
<script nonce="{nonce}">
{e.custom_js or ""}
</script>
</body>
</html>"""

    return Response(content=html, media_type="text/html; charset=utf-8", headers=headers)
