#v0.8
from __future__ import annotations
import secrets
import logging
import sys
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.core.config import settings
from backend.models import AdminUser
from backend.services.authn.passwords import hash_password, verify_password

# Налаштуємо логер
logger = logging.getLogger("uvicorn.error")

def ensure_root_user() -> None:
    """
    Створює root-адміна при старті.
    Логіка:
    1. Якщо юзера немає -> створює + друкує пароль.
    2. Якщо юзер є і в .env заданий пароль -> оновлює пароль в базі.
    3. Якщо юзер є і в .env пусто -> просто пише в лог, що юзер існує.
    """
    db: Session = SessionLocal()
    try:
        target_email = settings.admin_root_email or "admin@ppv.local"
        existing_user = db.query(AdminUser).filter(AdminUser.email == target_email).first()
        
        # 1. Якщо користувач ВЖЕ існує
        if existing_user:
            # Перевіряємо, чи заданий пароль в .env, щоб оновити його (Recovery mode)
            if settings.admin_root_pass:
                # Якщо пароль в базі не співпадає з тим, що в .env -> оновлюємо
                if not verify_password(settings.admin_root_pass, existing_user.hashed_password):
                    logger.warning(f"🔄 Updating existing root admin ({target_email}) password to match .env configuration.")
                    existing_user.hashed_password = hash_password(settings.admin_root_pass)
                    existing_user.role = "super"
                    db.commit()
                else:
                    logger.info(f"✅ Root admin ({target_email}) exists and password matches .env.")
            else:
                # Пароль в .env не заданий (авто-режим), але юзер вже є.
                # Ми не можемо показати пароль, бо він захешований.
                logger.info(f"ℹ️ Root admin ({target_email}) already exists. Skipping creation.")
                logger.info("   To regenerate: run 'docker compose down -v' to wipe DB.")
            return

        # 2. Якщо користувача НЕМАЄ -> Створюємо
        plain_password = settings.admin_root_pass
        if not plain_password:
            plain_password = secrets.token_urlsafe(12)
            is_generated = True
        else:
            is_generated = False

        new_admin = AdminUser(
            email=target_email,
            role="super",
            hashed_password=hash_password(plain_password),
        )
        
        db.add(new_admin)
        db.commit()
        db.refresh(new_admin)

        # 3. ДРУК У ТЕРМІНАЛ
        border = "=" * 60
        msg = (
            f"\n{border}\n"
            f"🚀 ROOT ADMIN CREATED SUCCESSFULLY\n"
            f"{border}\n"
            f"Login:    {target_email}\n"
            f"Password: {plain_password}\n"
        )
        if is_generated:
            msg += f"(Password auto-generated. Save it! It won't be shown again.)\n"
        else:
            msg += f"(Credentials loaded from .env)\n"
            
        msg += f"{border}\n"
        
        # Print з flush=True гарантує, що Docker захопить цей вивід миттєво
        print(msg, flush=True)
        # Також в логер для надійності
        logger.warning("Root admin credentials generated (see logs above).")

    except Exception as e:
        logger.error(f"Failed to ensure root user: {e}")
    finally:
        db.close()