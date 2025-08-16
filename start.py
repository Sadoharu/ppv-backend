# start.py
from pathlib import Path
import os
from alembic import command
from alembic.config import Config
import uvicorn

BASE = Path(__file__).resolve().parent           # /app
ALEMBIC_INI = BASE / "migrations" / "alembic.ini"   # /app/backend/alembic.ini

def run_migrations() -> None:
    """
    Накатує міграції до "head" при кожному старті контейнера.
    Працює як зі staging, так і з prod Postgres.
    """
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option(
        "script_location",
        str(BASE / "migrations" / "alembic"),       # абсолютний шлях
    )
    command.upgrade(cfg, "head")

if __name__ == "__main__":
    run_migrations()                             # ① спершу БД

    # ② запускаємо API-сервер
    is_dev   = os.getenv("ENV", "prod") == "dev"
    workers  = int(os.getenv("UVICORN_WORKERS", "4"))   # можна задати у compose
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        # reload=is_dev,        # лише в dev
        workers=4,
        log_level="info",
    )
