# backend/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from backend.core.config import settings
from sqlalchemy.engine import make_url

SQLALCHEMY_DATABASE_URL = settings.db_url        # читаємо з .env

url = make_url(SQLALCHEMY_DATABASE_URL)
# якщо використовуємо SQLite — додаємо check_same_thread, інакше — нічого не передаємо
if url.drivername.startswith("sqlite"):
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL
    )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)

Base = declarative_base()


# Dependency для FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
