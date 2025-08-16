#v0.5
from __future__ import annotations
from typing import List
from sqlalchemy.orm import Session as DB

from backend import models
from backend.services.authn.codes import hash_code
from backend.services.codegen import generate_unique_code
from backend.services.codegen import generate_unique_codes_bulk

def create_access_codes(db: DB, amount: int, allowed_sessions: int) -> list[str]:
    model = models.AccessCode
    plains = generate_unique_codes_bulk(db, model, field_name="code_plain", n=amount)
    objs = [
        model(code_plain=p, code_hash=hash_code(p), allowed_sessions=int(allowed_sessions))
        for p in plains
    ]
    db.add_all(objs)
    try:
        db.commit()
    except IntegrityError:
        # на випадок гонки з іншим процесом — добити бракуючі й повторити
        db.rollback()
        # можна обчислити які саме впали, але простіше — викликати ще раз і докинути
        extra_needed = amount - db.query(model).filter(model.code_plain.in_(plains)).count()
        if extra_needed > 0:
            extra = generate_unique_codes_bulk(db, model, "code_plain", extra_needed)
            db.add_all([model(code_plain=p, code_hash=hash_code(p), allowed_sessions=int(allowed_sessions)) for p in extra])
            db.commit()
        # повертаємо вже наявні + нові (або просто plains, якщо достатньо)
    return plains
