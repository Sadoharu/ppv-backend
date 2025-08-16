#v0.5
from __future__ import annotations
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.core.config import settings
from backend.models import AdminUser
from backend.services.authn.passwords import hash_password

def ensure_root_user() -> None:
    """
    Ідempotent: створює root-адміна, якщо його нема.
    Викликаємо на старті додатку.
    """
    db: Session = SessionLocal()
    try:
        u = db.query(AdminUser).filter(AdminUser.email == settings.admin_root_email).first()
        if not u:
            u = AdminUser(
                email=settings.admin_root_email,
                role="admin",
                hashed_password=hash_password(settings.admin_root_pass),
            )
            db.add(u)
            db.commit()
    finally:
        db.close()
