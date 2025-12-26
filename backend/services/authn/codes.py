#v1.0 - Direct bcrypt implementation for access codes
from __future__ import annotations
import bcrypt
import logging

# Аналогічно до passwords.py, використовуємо bcrypt напряму,
# щоб уникнути помилок сумісності passlib з Python 3.12+

def hash_code(code: str) -> str:
    """
    Хешує код доступу за допомогою bcrypt.
    """
    code_bytes = code.encode('utf-8')
    
    # bcrypt має ліміт 72 байти. Обрізаємо для безпеки (хоча коди зазвичай короткі)
    if len(code_bytes) > 72:
        code_bytes = code_bytes[:72]
        
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(code_bytes, salt)
    return hashed.decode('utf-8')

def verify_code(code: str, hashed: str) -> bool:
    """
    Перевіряє код доступу.
    """
    try:
        code_bytes = code.encode('utf-8')
        
        if len(code_bytes) > 72:
            code_bytes = code_bytes[:72]
            
        # Якщо хеш прийшов як рядок, конвертуємо в байти
        if isinstance(hashed, str):
            hashed_bytes = hashed.encode('utf-8')
        else:
            hashed_bytes = hashed
            
        return bcrypt.checkpw(code_bytes, hashed_bytes)
    except Exception:
        # При будь-якій помилці (бітий хеш тощо) вважаємо перевірку невдалою
        return False