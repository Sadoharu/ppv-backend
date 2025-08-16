#v0.5
from __future__ import annotations
from passlib.hash import bcrypt

def hash_code(code: str) -> str:
    return bcrypt.hash(code)

def verify_code(code: str, code_hash: str) -> bool:
    return bcrypt.verify(code, code_hash)
