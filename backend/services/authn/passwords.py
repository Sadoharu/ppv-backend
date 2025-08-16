#v0.5
from __future__ import annotations
from passlib.context import CryptContext

# Окремий контекст для ПАРОЛІВ (адмін-кабінет), не плутати з кодами
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return _pwd_ctx.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return _pwd_ctx.verify(password, hashed)
