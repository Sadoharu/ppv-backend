import asyncio

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.orm import Session


from backend.services.authn.passwords import hash_password
from backend.database import Base, engine, SessionLocal

from backend.core.config import settings
from backend.core.logging import setup_logging
from backend.core.redis import close_redis, close_redis_async, get_redis

from backend.api.v1.admin.codes import router as admin_codes_router
from backend.api.v1.admin.analytics import router as analytics_router
from backend.api.v1.admin.auth import router as admin_auth_router
from backend.api.v1.admin.allow_events import router as admin_allow_events_router
from backend.api.v1.admin.events import router as admin_events_router
from backend.api.v1.admin.sessions import router as admin_sessions_router
from backend.api.v1.admin.ws import router as admin_ws_router

from backend.api.v1.client.auth import router as client_auth_router
from backend.api.v1.client.ws import router as client_ws_router
from backend.api.v1.client.events_access import router as events_router

from backend.api.v1.public.events import router as public_events_router
from backend.api.v1.public.custom import router as public_custom_router

from backend.models import AdminUser
from backend.workers.idle_reaper import run_idle_reaper
from backend.workers.session_gc import run_session_gc

from backend.services.authn.bootstrap import ensure_root_user

_idle_task = None
_gc_task = None

# опціонально: якщо цей модуль у тебе є і ти ним користуєшся
try:
    from backend.routers.health import router as health_router  # старий health, якщо існує
except Exception:
    health_router = None



def seed_policy_defaults():
    r = get_redis()
    cur = r.hgetall("policy") or {}
    def missing(k): return (k not in cur) or (cur[k] == "") or (cur[k] is None)
    to_set = {}
    # використовуємо твої settings (из backend/config.py / backend.core.config.py)
    mapping = {
        "access_ttl_minutes":        str(settings.access_ttl_minutes),
        "refresh_ttl_days":          str(settings.refresh_ttl_days),
        "sliding_window_enabled":    "1" if settings.sliding_window_enabled else "0",
        "sliding_extend_seconds":    str(settings.sliding_extend_seconds),
        "access_grace_seconds":      str(settings.access_grace_seconds),
        "reuse_grace_on_disconnect": "1" if settings.reuse_grace_on_disconnect else "0",
        "auto_release_idle_minutes": str(settings.auto_release_idle_minutes),
    }
    for k, v in mapping.items():
        if missing(k):
            to_set[k] = v
    if to_set:
        r.hset("policy", mapping=to_set)


# --- автостворення root-адміна -----------------------------------------------
def ensure_root_admin():
    db: Session = SessionLocal()
    try:
        u = db.query(AdminUser).filter(AdminUser.email == settings.admin_root_email).first()
        if not u:
            u = AdminUser(
                email=settings.admin_root_email,
                hashed_password=hash_password(settings.admin_root_pass),
                role="super"
            )
            db.add(u)
            db.commit()
    finally:
        db.close()
# -----------------------------------------------------------------------------


setup_logging()

app = FastAPI(
    title="Access Code Portal API",
    version="0.6.0",
    debug=settings.debug
)

# PROD-захисти
if not settings.debug:
    app.add_middleware(HTTPSRedirectMiddleware)
    allowed_hosts = getattr(settings, "allowed_hosts_list", None)
    if not allowed_hosts:
        allowed_hosts = [h.strip() for h in getattr(settings, "allowed_hosts", "*").split(",")]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

# CORS
origins = [o.strip() for o in (settings.allowed_origins or "").split(",") if o.strip()]
if not origins:
    # дефолт для деву
    origins = ["http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # фронт під Vite
        # додай сюди інші твої фронтові домени при потребі
    ],
    allow_credentials=True,        # якщо працюємо з куками (так)
    allow_methods=["*"],           # або перелічити: ["GET","POST","PATCH","DELETE","OPTIONS"]
    allow_headers=["*"],           # або перелічити потрібні
)


# --- startup/shutdown ---
@app.on_event("startup")
async def on_startup() -> None:
    # один централізований бутстрап адміна/користувача
    ensure_root_user()
    seed_policy_defaults()

    try:
        if settings.db_url.startswith("sqlite"):
            Base.metadata.create_all(bind=engine)
    except Exception:
        pass

    global _idle_task, _gc_task
    if _idle_task is None:
        _idle_task = asyncio.create_task(run_idle_reaper(poll_seconds=30))
    if _gc_task is None:
        _gc_task = asyncio.create_task(run_session_gc())

@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _idle_task, _gc_task
    for t in (_idle_task, _gc_task):
        if t:
            t.cancel()
            try:
                await t
            except Exception:
                pass
    _idle_task = _gc_task = None
    close_redis()
    await close_redis_async()

# -----------------------------------------------------------------------------
# Routers
if health_router:
    app.include_router(health_router)
app.include_router(client_auth_router, prefix="/api/auth", tags=["client:auth"])
app.include_router(client_ws_router, prefix="/api", tags=["client:ws"])
app.include_router(events_router, prefix="/api/events",  tags=["client:EventAccess"])
app.include_router(admin_sessions_router, prefix="/api/admin", tags=["admin:sessions"])
app.include_router(admin_codes_router, prefix="/api/admin/codes", tags=["admin:codes"])
app.include_router(analytics_router, prefix="/api/admin/analytics", tags=["admin:analytics"])
app.include_router(admin_auth_router, prefix="/api/admin", tags=["admin:auth"])
app.include_router(admin_ws_router, prefix="/api/ws", tags=["admin:ws"])
app.include_router(public_events_router, prefix="/api", tags=["public:events"])
app.include_router(public_custom_router, prefix="/api", tags=["public:custom"])
app.include_router(admin_events_router, prefix="/api/admin/events", tags=["admin:events"])
app.include_router(admin_allow_events_router, prefix="/api/admin/codes", tags=["admin:codes-events"])

