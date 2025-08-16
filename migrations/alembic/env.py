# migrations/alembic/env.py
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# --- Додамо можливі корені проєкту в sys.path ---
# поточний файл: /app/migrations/alembic/env.py
HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]           # /app
CANDIDATES = [
    ROOT,                        # /app
    ROOT / "backend",            # /app/backend
]

for p in CANDIDATES:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# --- Імпорти конфігу та моделей з урахуванням різних структур ---
try:
    # варіант із пакетом backend
    from backend import models
    from backend.core.config import settings
except Exception:
    # плоска структура без backend/
    import models  # type: ignore
    from core.config import settings  # type: ignore

# Alembic config
config = context.config

# URL беремо з settings, не з .ini
config.set_main_option("sqlalchemy.url", settings.db_url)

# Це metadata для автогенерації
target_metadata = models.Base.metadata

# Логування
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=settings.db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
