# start.py
import time
import logging
import uvicorn
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from alembic.config import Config
from alembic import command

from backend.core.config import settings

# Налаштування логування для скрипта запуску
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def wait_for_db():
    """
    Чекає, поки база даних стане доступною, перед запуском міграцій.
    Це вирішує проблему 'Connection refused' при старті docker-compose.
    """
    retries = 30  # Максимум 30 спроб (приблизно 1 хвилина)
    wait_s = 2    # Пауза 2 секунди
    
    logger.info(f"Attempting to connect to DB...")
    
    while retries > 0:
        try:
            # Створюємо тимчасовий engine для перевірки з'єднання
            engine = create_engine(settings.db_url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✅ Database is ready and accepting connections!")
            return
        except OperationalError:
            retries -= 1
            logger.warning(f"⏳ Database not ready yet. Retrying in {wait_s}s... ({retries} attempts left)")
            time.sleep(wait_s)
        except Exception as e:
            logger.error(f"❌ Unexpected error connecting to DB: {e}")
            time.sleep(wait_s)
            retries -= 1
            
    logger.error("🚨 Could not connect to the database after multiple retries. Exiting.")
    sys.exit(1)

def run_migrations():
    logger.info("🔄 Running migrations...")
    try:
        # Вказуємо шлях до конфігу Alembic
        alembic_cfg = Config("migrations/alembic.ini")
        # Примусово встановлюємо URL бази з налаштувань програми
        alembic_cfg.set_main_option("sqlalchemy.url", settings.db_url)
        
        # FIX: Вказуємо явний шлях до папки скриптів alembic, оскільки ми запускаємо з кореня,
        # а alembic.ini налаштований відносно себе або дефолтно.
        # Це виправляє помилку "Path doesn't exist: alembic"
        alembic_cfg.set_main_option("script_location", "migrations/alembic")
        
        command.upgrade(alembic_cfg, "head")
        logger.info("✅ Migrations complete.")
    except Exception as e:
        logger.error(f"🚨 Migration failed: {e}")
        # Не виходимо, щоб дати шанс uvicorn запуститись і показати помилки, 
        # але в продакшені краще sys.exit(1)
        sys.exit(1)

if __name__ == "__main__":
    # 1. Чекаємо готовності бази даних
    wait_for_db()
    
    # 2. Накочуємо міграції структури БД
    run_migrations()
    
    # 3. Стартуємо основний веб-сервер
    logger.info(f"🚀 Starting Uvicorn server (Reload={settings.debug})...")
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        proxy_headers=True,      # Важливо для роботи за Nginx
        forwarded_allow_ips="*"  # Довіряти заголовкам від Nginx
    )