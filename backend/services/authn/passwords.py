#v1.0 - Direct bcrypt implementation
from __future__ import annotations
import bcrypt
import logging

# Ми використовуємо bcrypt напряму, щоб уникнути проблем сумісності passlib з Python 3.12+ та bcrypt 4.0+
# Це виправляє помилку "AttributeError: ... __about__" та хибні "ValueError: password cannot be longer than 72 bytes"

def hash_password(password: str) -> str:
    """
    Хешує пароль за допомогою bcrypt.
    """
    # bcrypt працює з байтами
    pwd_bytes = password.encode('utf-8')
    
    # bcrypt має ліміт 72 байти на вхід. 
    # Щоб уникнути крашу сервера при дуууже довгих паролях, обрізаємо (безпечний фолбек).
    if len(pwd_bytes) > 72:
        pwd_bytes = pwd_bytes[:72]
        
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """
    Перевіряє пароль.
    """
    try:
        pwd_bytes = password.encode('utf-8')
        
        # Аналогічно обрізаємо при перевірці
        if len(pwd_bytes) > 72:
            pwd_bytes = pwd_bytes[:72]
            
        hashed_bytes = hashed.encode('utf-8')
        
        return bcrypt.checkpw(pwd_bytes, hashed_bytes)
    except Exception as e:
        # Логування помилок (наприклад, якщо хеш в базі пошкоджений)
        # logging.error(f"Auth check failed: {e}")
        return False